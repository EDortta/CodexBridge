"""The epics/issues MCP tools -- issue #78.

Exposes the epics/issues store already tested via REST
(`tests/integration/test_epics_issues.py`) over the MCP/ChatGPT transport, for
a project that may have no forge at all -- "plan conversing in ChatGPT". This
file does not re-prove store validation (that belongs to
`tests/unit`/`tests/integration/test_epics_issues.py`); it proves the tools
reach the SAME store, apply the same authorization catalogue
(`gateway/app/api/permissions.py`) the REST routes use, add idempotency on the
two creators and on `move_issue_to_epic` (mirroring the REST pair and the
link endpoint, since `PATCH /issues|epics/{id}` has none), and return the
`issue_ref` shape `start_development_task` already resolves.

`update_issue`, `update_epic` and `move_issue_to_epic`
(WK-20260902-epic-update-and-move) additionally require `expected_revision`:
the MCP equivalent of `If-Match`, and just as mandatory -- absent is
`expected_revision_required` (400), stale is `stale_write` (409). Each has a
happy-path test as its positive control, in this same file.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from gateway.app.api.routes import epics as epics_routes
from gateway.app.api.routes import issues as issues_routes
from gateway.app.api.setup import install_api_conventions
from gateway.app.core.users import AuthenticatedPrincipal
from gateway.app.db.base import Base
from gateway.app.db.session import get_session
from gateway.app.mcp.server import handle_mcp_call
from gateway.app.services import store
from shared.protocol import AgentMessageType, ISSUE_REF_PATTERN, ExecutorRegistration, ProjectRegistration


class DummyHub:
    def is_connected(self, executor_id: str) -> bool:
        return False

    async def dispatch_next(self, executor_id: str):
        return None

    async def send(self, executor_id: str, envelope):
        pass


class RecordingHub:
    """A hub with a caller-controlled set of connected executors, recording

    every `send`. Used only by the `publish_epic_to_repo` tests below --
    every other tool in this file is indifferent to `is_connected`, so the
    module-wide `DummyHub` (always disconnected) stays the default.
    """

    def __init__(self, connected: set[str]):
        self.connected = set(connected)
        self.sent: list[tuple[str, object]] = []

    def is_connected(self, executor_id: str) -> bool:
        return executor_id in self.connected

    async def dispatch_next(self, executor_id: str):
        return None

    async def send(self, executor_id: str, envelope) -> None:
        self.sent.append((executor_id, envelope))


# p1 only, holds codexbridge.issues.write -- the ISSUES_WRITE_SCOPE both
# EPICS_CREATE and ISSUES_CREATE require (gateway/app/api/permissions.py).
ALICE = AuthenticatedPrincipal(
    user_id="alice",
    email="alice@example.com",
    allowed_projects=["p1"],
    scopes=["codexbridge.read", "codexbridge.issues.write"],
)

# p1 only, read-only -- no ISSUES_WRITE_SCOPE.
READER = AuthenticatedPrincipal(
    user_id="reader",
    email="reader@example.com",
    allowed_projects=["p1"],
    scopes=["codexbridge.read"],
)

# Holds the write scope but p1 is not in its allowed_projects: p2 only.
OUTSIDER = AuthenticatedPrincipal(
    user_id="outsider",
    email="outsider@example.com",
    allowed_projects=["p2"],
    scopes=["codexbridge.read", "codexbridge.issues.write"],
)


@pytest.fixture
def users_file(tmp_path):
    path = tmp_path / "users.json"
    path.write_text(
        json.dumps(
            {
                "users": [
                    {
                        "user_id": "admin", "email": "admin@example.com", "password_hash": "x",
                        "roles": ["admin"], "allowed_projects": [],
                        "scopes": ["codexbridge.admin"], "enabled": True,
                    },
                ]
            }
        ),
        encoding="utf-8",
    )
    return str(path)


@pytest.fixture
async def env(users_file, monkeypatch):
    """One database, two doors onto it: `handle_mcp_call` directly, and a REST

    `TestClient` mounting the real `epics`/`issues` routers -- so test #8 below
    can prove they are the same storage, not a parallel one.
    """
    from gateway.app.core.config import settings

    monkeypatch.setattr(settings, "user_registry_file", users_file)

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with factory() as seed:
        await store.upsert_registry(
            seed,
            executors=[
                ExecutorRegistration(
                    executor_id="T1", display_name="T1", machine_token="t",
                    allowed_projects=["p1", "p2"], max_concurrent_tasks=5,
                )
            ],
            projects=[
                ProjectRegistration(project_id="p1", name="Projeto Um", path="/srv/p1", max_timeout_seconds=3600),
                ProjectRegistration(project_id="p2", name="Projeto Dois", path="/srv/p2", max_timeout_seconds=3600),
            ],
        )
        future = datetime.now(timezone.utc) + timedelta(hours=1)
        await store.create_oauth_access_token(
            seed, token="admin-tok", client_id="c", user_id="admin",
            scopes=["codexbridge.admin"], expires_at=future,
        )

    app = FastAPI(openapi_url=None, docs_url=None, redoc_url=None)
    install_api_conventions(app)
    app.include_router(epics_routes.router)
    app.include_router(issues_routes.router)

    async def override():
        async with factory() as s:
            yield s

    app.dependency_overrides[get_session] = override

    class Env:
        def __init__(self):
            self.factory = factory
            self.client = TestClient(app, raise_server_exceptions=False)
            self.admin_headers = {"Authorization": "Bearer admin-tok"}

    yield Env()
    await engine.dispose()


async def _call(env, principal, tool_name: str, arguments: dict, hub=None) -> dict:
    async with env.factory() as session:
        response = await handle_mcp_call(
            {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": tool_name, "arguments": arguments}},
            session, hub if hub is not None else DummyHub(), principal,
        )
    return response["result"]["structuredContent"]


# --------------------------------------------------------------------------
# 1. Epic, two issues on it, list both -- all through MCP.
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_epic_two_issues_and_list_them(env):
    epic = await _call(env, ALICE, "create_epic", {"project": "p1", "title": "Q3 planning"})
    assert epic["project_id"] == "p1"
    assert epic["status"] == "open"

    issue_a = await _call(env, ALICE, "create_issue", {
        "project": "p1", "epic_id": epic["epic_id"], "title": "First slice",
    })
    issue_b = await _call(env, ALICE, "create_issue", {
        "project": "p1", "epic_id": epic["epic_id"], "title": "Second slice",
    })

    listed = await _call(env, ALICE, "list_issues", {"project": "p1", "epic_id": epic["epic_id"]})
    assert listed["has_more"] is False
    ids = {item["issue_id"] for item in listed["issues"]}
    assert ids == {issue_a["issue_id"], issue_b["issue_id"]}

    epics_listed = await _call(env, ALICE, "list_epics", {"project": "p1"})
    assert [e["epic_id"] for e in epics_listed["epics"]] == [epic["epic_id"]]


# --------------------------------------------------------------------------
# 2/3. Idempotency on create_epic.
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_retried_create_epic_with_same_key_returns_the_same_epic(env):
    first = await _call(env, ALICE, "create_epic", {
        "project": "p1", "title": "Once only", "idempotency_key": "epic-key-1",
    })
    second = await _call(env, ALICE, "create_epic", {
        "project": "p1", "title": "Once only", "idempotency_key": "epic-key-1",
    })
    assert second["epic_id"] == first["epic_id"]

    listed = await _call(env, ALICE, "list_epics", {"project": "p1"})
    assert len(listed["epics"]) == 1


@pytest.mark.asyncio
async def test_same_idempotency_key_with_a_different_body_is_a_conflict(env):
    await _call(env, ALICE, "create_epic", {
        "project": "p1", "title": "Body A", "idempotency_key": "epic-key-2",
    })
    with pytest.raises(HTTPException) as raised:
        await _call(env, ALICE, "create_epic", {
            "project": "p1", "title": "Body B (different)", "idempotency_key": "epic-key-2",
        })
    assert raised.value.status_code == 409


# --------------------------------------------------------------------------
# 4. A principal without the project in allowed_projects gets a typed error,
#    never a silently empty list that looks like success.
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_principal_without_project_access_gets_a_typed_error_not_an_empty_list(env):
    await _call(env, ALICE, "create_issue", {"project": "p1", "title": "Visible to Alice only"})

    with pytest.raises(HTTPException) as raised:
        await _call(env, OUTSIDER, "list_issues", {"project": "p1"})
    assert raised.value.status_code == 403
    assert raised.value.detail == "project_access_denied"

    with pytest.raises(HTTPException) as raised:
        await _call(env, OUTSIDER, "create_issue", {"project": "p1", "title": "Should not land"})
    assert raised.value.status_code == 403
    assert raised.value.detail == "project_access_denied"


# --------------------------------------------------------------------------
# 5. A principal without the write scope is refused with missing_scope, not a
#    generic 403.
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_principal_without_write_scope_gets_missing_scope(env):
    with pytest.raises(HTTPException) as raised:
        await _call(env, READER, "create_issue", {"project": "p1", "title": "Reader cannot write"})
    assert raised.value.status_code == 403
    assert raised.value.detail == "missing_scope:codexbridge.issues.write"

    with pytest.raises(HTTPException) as raised:
        await _call(env, READER, "create_epic", {"project": "p1", "title": "Reader cannot write"})
    assert raised.value.status_code == 403
    assert raised.value.detail == "missing_scope:codexbridge.issues.write"

    # READER still holds codexbridge.read, so listing is unaffected.
    listed = await _call(env, READER, "list_issues", {"project": "p1"})
    assert listed["issues"] == []


# --------------------------------------------------------------------------
# 6. create_issue returns issue_ref in the exact shape start_development_task
#    already resolves.
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_issue_returns_an_issue_ref_matching_the_shared_pattern(env):
    issue = await _call(env, ALICE, "create_issue", {"project": "p1", "title": "Resolvable from chat"})
    assert issue["issue_ref"] == f"local:{issue['issue_id']}"
    assert ISSUE_REF_PATTERN.match(issue["issue_ref"])

    listed = await _call(env, ALICE, "list_issues", {"project": "p1"})
    assert listed["issues"][0]["issue_ref"] == issue["issue_ref"]


# --------------------------------------------------------------------------
# 7. Unknown status/priority are translated store validation, not a raw 500.
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_unknown_status_or_priority_is_a_typed_validation_error(env):
    with pytest.raises(HTTPException) as raised:
        await _call(env, ALICE, "create_issue", {"project": "p1", "title": "x", "status": "not-a-status"})
    assert raised.value.status_code == 400
    assert raised.value.detail == "validation_failed:/status:invalid_status"

    with pytest.raises(HTTPException) as raised:
        await _call(env, ALICE, "create_issue", {"project": "p1", "title": "x", "priority": "not-a-priority"})
    assert raised.value.status_code == 400
    assert raised.value.detail == "validation_failed:/priority:invalid_priority"

    with pytest.raises(HTTPException) as raised:
        await _call(env, ALICE, "create_epic", {"project": "p1", "title": "x", "status": "not-a-status"})
    assert raised.value.status_code == 400
    assert raised.value.detail == "validation_failed:/status:invalid_status"


@pytest.mark.asyncio
async def test_an_epic_id_from_another_project_is_unknown_epic(env):
    other = await _call(env, AuthenticatedPrincipal(
        user_id="admin", email="admin@example.com", roles=["admin"],
        allowed_projects=[], scopes=["codexbridge.admin"],
    ), "create_epic", {"project": "p2", "title": "Lives in p2"})

    with pytest.raises(HTTPException) as raised:
        await _call(env, ALICE, "create_issue", {
            "project": "p1", "epic_id": other["epic_id"], "title": "Cross-project link",
        })
    assert raised.value.status_code == 404
    assert raised.value.detail == "unknown_epic"


# --------------------------------------------------------------------------
# 8. The same rows, unchanged, through the REST surface #8 already ships --
#    proving one store, not a parallel one.
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_rows_created_via_mcp_appear_unchanged_via_rest(env):
    epic = await _call(env, ALICE, "create_epic", {"project": "p1", "title": "Seen from both sides"})
    issue = await _call(env, ALICE, "create_issue", {
        "project": "p1", "epic_id": epic["epic_id"], "title": "Same row, two doors",
        "priority": "high", "labels": ["backend"],
    })

    rest_epics = env.client.get("/api/v1/projects/p1/epics", headers=env.admin_headers).json()
    assert len(rest_epics["items"]) == 1
    rest_epic = rest_epics["items"][0]
    assert rest_epic["id"] == epic["epic_id"]
    assert rest_epic["title"] == epic["title"]
    assert rest_epic["status"] == epic["status"]

    rest_issue_resp = env.client.get(f"/api/v1/issues/{issue['issue_id']}", headers=env.admin_headers)
    assert rest_issue_resp.status_code == 200
    rest_issue = rest_issue_resp.json()
    assert rest_issue["id"] == issue["issue_id"]
    assert rest_issue["epicId"] == epic["epic_id"]
    assert rest_issue["title"] == issue["title"]
    assert rest_issue["priority"] == "high"
    assert rest_issue["labels"] == ["backend"]


# --------------------------------------------------------------------------
# 9. update_issue -- WK-20260902-epic-update-and-move.
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_update_issue_changes_only_the_mentioned_fields(env):
    """Positive control for the two expected_revision negatives below."""
    issue = await _call(env, ALICE, "create_issue", {
        "project": "p1", "title": "Original", "priority": "low", "labels": ["a"],
    })
    updated = await _call(env, ALICE, "update_issue", {
        "issue_id": issue["issue_id"], "status": "in_progress", "expected_revision": issue["revision"],
    })
    assert updated["status"] == "in_progress"
    assert updated["title"] == "Original"
    assert updated["priority"] == "low"
    assert updated["labels"] == ["a"]
    assert updated["revision"] == issue["revision"] + 1


@pytest.mark.asyncio
async def test_update_issue_accepts_the_bare_id_or_the_local_prefixed_ref(env):
    issue = await _call(env, ALICE, "create_issue", {"project": "p1", "title": "x"})

    via_bare = await _call(env, ALICE, "update_issue", {
        "issue_id": issue["issue_id"], "status": "in_progress", "expected_revision": issue["revision"],
    })
    via_ref = await _call(env, ALICE, "update_issue", {
        "issue_id": issue["issue_ref"], "status": "blocked", "expected_revision": via_bare["revision"],
    })
    assert via_ref["status"] == "blocked"
    assert via_ref["issue_id"] == issue["issue_id"]


@pytest.mark.asyncio
async def test_update_issue_without_expected_revision_is_refused(env):
    issue = await _call(env, ALICE, "create_issue", {"project": "p1", "title": "x"})
    with pytest.raises(HTTPException) as raised:
        await _call(env, ALICE, "update_issue", {"issue_id": issue["issue_id"], "status": "in_progress"})
    assert raised.value.status_code == 400
    assert raised.value.detail == "expected_revision_required"


@pytest.mark.asyncio
async def test_update_issue_with_a_stale_expected_revision_is_refused(env):
    issue = await _call(env, ALICE, "create_issue", {"project": "p1", "title": "x"})
    with pytest.raises(HTTPException) as raised:
        await _call(env, ALICE, "update_issue", {
            "issue_id": issue["issue_id"], "status": "in_progress", "expected_revision": issue["revision"] + 1,
        })
    assert raised.value.status_code == 409
    assert raised.value.detail == "stale_write"


@pytest.mark.asyncio
async def test_update_issue_with_an_unknown_status_is_a_typed_validation_error(env):
    issue = await _call(env, ALICE, "create_issue", {"project": "p1", "title": "x"})
    with pytest.raises(HTTPException) as raised:
        await _call(env, ALICE, "update_issue", {
            "issue_id": issue["issue_id"], "status": "not-a-status", "expected_revision": issue["revision"],
        })
    assert raised.value.status_code == 400
    assert raised.value.detail == "validation_failed:/status:invalid_status"


@pytest.mark.asyncio
async def test_update_issue_on_another_projects_issue_is_unknown_issue(env):
    theirs = await _call(env, AuthenticatedPrincipal(
        user_id="admin", email="admin@example.com", roles=["admin"],
        allowed_projects=[], scopes=["codexbridge.admin"],
    ), "create_issue", {"project": "p2", "title": "Lives in p2"})

    with pytest.raises(HTTPException) as raised:
        await _call(env, ALICE, "update_issue", {
            "issue_id": theirs["issue_id"], "status": "in_progress", "expected_revision": theirs["revision"],
        })
    assert raised.value.status_code == 404
    assert raised.value.detail == "unknown_issue"


# --------------------------------------------------------------------------
# 10. update_epic -- WK-20260902-epic-update-and-move.
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_update_epic_changes_only_the_mentioned_fields(env):
    """Positive control for the two expected_revision negatives below."""
    epic = await _call(env, ALICE, "create_epic", {"project": "p1", "title": "Original"})
    updated = await _call(env, ALICE, "update_epic", {
        "epic_id": epic["epic_id"], "status": "cancelled", "expected_revision": epic["revision"],
    })
    assert updated["status"] == "cancelled"
    assert updated["title"] == "Original"
    assert updated["revision"] == epic["revision"] + 1


@pytest.mark.asyncio
async def test_update_epic_without_expected_revision_is_refused(env):
    epic = await _call(env, ALICE, "create_epic", {"project": "p1", "title": "x"})
    with pytest.raises(HTTPException) as raised:
        await _call(env, ALICE, "update_epic", {"epic_id": epic["epic_id"], "status": "cancelled"})
    assert raised.value.status_code == 400
    assert raised.value.detail == "expected_revision_required"


@pytest.mark.asyncio
async def test_update_epic_with_a_stale_expected_revision_is_refused(env):
    epic = await _call(env, ALICE, "create_epic", {"project": "p1", "title": "x"})
    with pytest.raises(HTTPException) as raised:
        await _call(env, ALICE, "update_epic", {
            "epic_id": epic["epic_id"], "status": "cancelled", "expected_revision": epic["revision"] + 1,
        })
    assert raised.value.status_code == 409
    assert raised.value.detail == "stale_write"


@pytest.mark.asyncio
async def test_update_epic_with_an_unknown_status_is_a_typed_validation_error(env):
    epic = await _call(env, ALICE, "create_epic", {"project": "p1", "title": "x"})
    with pytest.raises(HTTPException) as raised:
        await _call(env, ALICE, "update_epic", {
            "epic_id": epic["epic_id"], "status": "orbiting", "expected_revision": epic["revision"],
        })
    assert raised.value.status_code == 400
    assert raised.value.detail == "validation_failed:/status:invalid_status"


# --------------------------------------------------------------------------
# 11. move_issue_to_epic -- WK-20260902-epic-update-and-move.
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_move_issue_to_epic_changes_the_issues_epic(env):
    """Positive control for the two expected_revision negatives below."""
    origin = await _call(env, ALICE, "create_epic", {"project": "p1", "title": "Origin"})
    target = await _call(env, ALICE, "create_epic", {"project": "p1", "title": "Target"})
    issue = await _call(env, ALICE, "create_issue", {
        "project": "p1", "epic_id": origin["epic_id"], "title": "Movable",
    })

    moved = await _call(env, ALICE, "move_issue_to_epic", {
        "issue_id": issue["issue_id"], "epic_id": target["epic_id"], "expected_revision": issue["revision"],
    })
    assert moved["epic_id"] == target["epic_id"]
    assert moved["revision"] == issue["revision"] + 1

    listed = await _call(env, ALICE, "list_issues", {"project": "p1", "epic_id": target["epic_id"]})
    assert [i["issue_id"] for i in listed["issues"]] == [issue["issue_id"]]


@pytest.mark.asyncio
async def test_move_issue_to_epic_without_expected_revision_is_refused(env):
    epic = await _call(env, ALICE, "create_epic", {"project": "p1", "title": "x"})
    issue = await _call(env, ALICE, "create_issue", {"project": "p1", "title": "x"})
    with pytest.raises(HTTPException) as raised:
        await _call(env, ALICE, "move_issue_to_epic", {"issue_id": issue["issue_id"], "epic_id": epic["epic_id"]})
    assert raised.value.status_code == 400
    assert raised.value.detail == "expected_revision_required"


@pytest.mark.asyncio
async def test_move_issue_to_epic_with_a_stale_expected_revision_is_refused(env):
    epic = await _call(env, ALICE, "create_epic", {"project": "p1", "title": "x"})
    issue = await _call(env, ALICE, "create_issue", {"project": "p1", "title": "x"})
    with pytest.raises(HTTPException) as raised:
        await _call(env, ALICE, "move_issue_to_epic", {
            "issue_id": issue["issue_id"], "epic_id": epic["epic_id"], "expected_revision": issue["revision"] + 1,
        })
    assert raised.value.status_code == 409
    assert raised.value.detail == "stale_write"


@pytest.mark.asyncio
async def test_move_issue_to_epic_from_a_foreign_project_is_unknown_epic(env):
    foreign_epic = await _call(env, AuthenticatedPrincipal(
        user_id="admin", email="admin@example.com", roles=["admin"],
        allowed_projects=[], scopes=["codexbridge.admin"],
    ), "create_epic", {"project": "p2", "title": "Lives in p2"})
    issue = await _call(env, ALICE, "create_issue", {"project": "p1", "title": "x"})

    with pytest.raises(HTTPException) as raised:
        await _call(env, ALICE, "move_issue_to_epic", {
            "issue_id": issue["issue_id"], "epic_id": foreign_epic["epic_id"], "expected_revision": issue["revision"],
        })
    assert raised.value.status_code == 404
    assert raised.value.detail == "unknown_epic"


@pytest.mark.asyncio
async def test_a_retried_move_does_not_move_the_issue_twice(env):
    epic = await _call(env, ALICE, "create_epic", {"project": "p1", "title": "x"})
    issue = await _call(env, ALICE, "create_issue", {"project": "p1", "title": "x"})
    arguments = {
        "issue_id": issue["issue_id"], "epic_id": epic["epic_id"],
        "expected_revision": issue["revision"], "idempotency_key": "move-1",
    }

    first = await _call(env, ALICE, "move_issue_to_epic", arguments)
    second = await _call(env, ALICE, "move_issue_to_epic", arguments)
    assert second == first

    listed = await _call(env, ALICE, "list_issues", {"project": "p1", "epic_id": epic["epic_id"]})
    assert len(listed["issues"]) == 1, "the move must not have applied twice"
    assert listed["issues"][0]["revision"] == issue["revision"] + 1


# --------------------------------------------------------------------------
# 12. Extracting the idempotency helpers (review debt on A1, Tarefa 0) must
#     not change what create_epic/create_issue's own idempotency tests prove
#     -- see this module's tests #2/#3 above, left unmodified by this PR.
# --------------------------------------------------------------------------


# --------------------------------------------------------------------------
# 13. publish_epic_to_repo -- issue #78, WK-20260902-issue-materialize.
#     Covers `permissions.EPICS_PUBLISH` for
#     tests/integration/test_auth.py::test_epics_publish_is_exercised_over_mcp.
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_publish_epic_to_repo_dispatches_to_a_connected_executor(env):
    """Positive control for the two `_not_connected`/`_not_onboarded` tests below."""
    epic = await _call(env, ALICE, "create_epic", {"project": "p1", "title": "Bridge epic"})
    await _call(env, ALICE, "create_issue", {
        "project": "p1", "epic_id": epic["epic_id"], "title": "First slice",
    })
    assert epic["materialized_path"] is None
    assert epic["materialized_revision"] is None

    hub = RecordingHub(connected={"T1"})
    result = await _call(env, ALICE, "publish_epic_to_repo", {"epic_id": epic["epic_id"]}, hub=hub)

    assert result["status"] == "dispatched"
    assert result["executor_id"] == "T1"
    assert result["existing_path"] is None
    assert result["file_count"] == 3  # README.md + epic.md + one issue file

    assert len(hub.sent) == 1
    sent_executor_id, envelope = hub.sent[0]
    assert sent_executor_id == "T1"
    assert envelope.type == AgentMessageType.ISSUE_MATERIALIZE
    assert envelope.payload["epic_id"] == epic["epic_id"]
    assert envelope.payload["project_id"] == "p1"
    assert envelope.payload["existing_path"] is None
    assert set(envelope.payload["files"]) == {
        "README.md", "epic.md",
    } | {k for k in envelope.payload["files"] if k.startswith("issues/")}
    assert any(k.startswith("issues/") for k in envelope.payload["files"])


@pytest.mark.asyncio
async def test_publish_epic_to_repo_with_no_connected_executor_is_a_typed_error(env):
    epic = await _call(env, ALICE, "create_epic", {"project": "p1", "title": "Bridge epic"})

    hub = RecordingHub(connected=set())  # T1 allows p1 but is not connected
    with pytest.raises(HTTPException) as raised:
        await _call(env, ALICE, "publish_epic_to_repo", {"epic_id": epic["epic_id"]}, hub=hub)
    assert raised.value.status_code == 409
    assert raised.value.detail.startswith("executor_not_connected")
    assert hub.sent == []


@pytest.mark.asyncio
async def test_publish_epic_to_repo_for_a_project_no_executor_allows_is_project_not_onboarded(env):
    # p3 is registered but no executor's allowed_projects names it -- T1 (the
    # only executor in this fixture) allows only p1/p2.
    unclaimed = AuthenticatedPrincipal(
        user_id="carol", email="carol@example.com",
        allowed_projects=["p3"], scopes=["codexbridge.read", "codexbridge.issues.write"],
    )
    async with env.factory() as session:
        await store.upsert_registry(
            session, executors=[],
            projects=[ProjectRegistration(project_id="p3", name="Projeto Tres", path="/srv/p3", max_timeout_seconds=3600)],
        )
    epic = await _call(env, unclaimed, "create_epic", {"project": "p3", "title": "Bridge epic"})

    hub = RecordingHub(connected={"T1"})
    with pytest.raises(HTTPException) as raised:
        await _call(env, unclaimed, "publish_epic_to_repo", {"epic_id": epic["epic_id"]}, hub=hub)
    assert raised.value.status_code == 409
    assert raised.value.detail.startswith("project_not_onboarded")
    assert hub.sent == []


@pytest.mark.asyncio
async def test_publish_epic_to_repo_unknown_epic_is_404(env):
    hub = RecordingHub(connected={"T1"})
    with pytest.raises(HTTPException) as raised:
        await _call(env, ALICE, "publish_epic_to_repo", {"epic_id": "does-not-exist"}, hub=hub)
    assert raised.value.status_code == 404
    assert raised.value.detail == "unknown_epic"


@pytest.mark.asyncio
async def test_publish_epic_to_repo_republish_carries_existing_path(env):
    epic = await _call(env, ALICE, "create_epic", {"project": "p1", "title": "Bridge epic"})
    async with env.factory() as session:
        await store.apply_epic_materialization(
            session,
            epic_id=epic["epic_id"],
            epic_path="docs/issues/078-bridge-epic-[ready]",
            epic_revision=epic["revision"],
            written_paths={},
            issue_revisions={},
        )

    hub = RecordingHub(connected={"T1"})
    result = await _call(env, ALICE, "publish_epic_to_repo", {"epic_id": epic["epic_id"]}, hub=hub)

    assert result["existing_path"] == "docs/issues/078-bridge-epic-[ready]"
    _, envelope = hub.sent[0]
    assert envelope.payload["existing_path"] == "docs/issues/078-bridge-epic-[ready]"


@pytest.mark.asyncio
async def test_publish_epic_to_repo_requires_write_scope(env):
    epic = await _call(env, ALICE, "create_epic", {"project": "p1", "title": "Bridge epic"})
    hub = RecordingHub(connected={"T1"})
    with pytest.raises(HTTPException) as raised:
        await _call(env, READER, "publish_epic_to_repo", {"epic_id": epic["epic_id"]}, hub=hub)
    assert raised.value.status_code == 403
    assert raised.value.detail == "missing_scope:codexbridge.issues.write"
    assert hub.sent == []
