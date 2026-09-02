"""The `create_epic`/`list_epics`/`create_issue`/`list_issues` MCP tools -- issue #78.

Exposes the epics/issues store already tested via REST
(`tests/integration/test_epics_issues.py`) over the MCP/ChatGPT transport, for
a project that may have no forge at all -- "plan conversing in ChatGPT". This
file does not re-prove store validation (that belongs to
`tests/unit`/`tests/integration/test_epics_issues.py`); it proves the four
tools reach the SAME store, apply the same authorization catalogue
(`gateway/app/api/permissions.py`) the REST routes use, add idempotency on the
two creators only (mirroring the REST pair, since `PATCH /issues/{id}` has
none), and return the `issue_ref` shape `start_development_task` already
resolves.
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
from shared.protocol import ISSUE_REF_PATTERN, ExecutorRegistration, ProjectRegistration


class DummyHub:
    def is_connected(self, executor_id: str) -> bool:
        return False

    async def dispatch_next(self, executor_id: str):
        return None

    async def send(self, executor_id: str, envelope):
        pass


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


async def _call(env, principal, tool_name: str, arguments: dict) -> dict:
    async with env.factory() as session:
        response = await handle_mcp_call(
            {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": tool_name, "arguments": arguments}},
            session, DummyHub(), principal,
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
