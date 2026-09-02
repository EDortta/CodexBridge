"""Operational decisions — issue #6.

A "decision" is a session held for approval, reshaped for the mobile Decision
Center; `gateway/app/api/routes/decisions.py`'s module docstring has the full
mapping. These tests are weighted toward the acceptance criteria the issue
names explicitly: rejection needs a reason, a critical approval needs an
explicit confirmation, repeated submissions are idempotent, and a resolved or
stale decision answers with a clear conflict rather than acting again.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from gateway.app.api.routes import decisions as decisions_routes
from gateway.app.api.setup import install_api_conventions
from gateway.app.db.base import Base
from gateway.app.db.session import get_session
from gateway.app.models.entities import AuditEventModel, ForgeOperationModel
from gateway.app.services import store
from gateway.app.services.agent_hub import AgentHub
from shared.protocol import (
    ApprovalDecision,
    ExecutorRegistration,
    ForgeOperationKind,
    ForgeOperationRequest,
    ProjectRegistration,
    SubmitTaskRequest,
    TaskMode,
    TaskPriority,
    TaskState,
)


class _DummyWebSocket:
    """Stands in for the executor's websocket in `AgentHub.register` — real
    enough that `AgentHub.send` (`connection.websocket.send_json(...)`) works
    without an actual socket, same pattern as
    `tests/integration/test_agent_ack_handling.py`'s own `_DummyWebSocket`.
    """

    def __init__(self) -> None:
        self.sent: list[dict] = []

    async def send_json(self, payload: dict) -> None:
        self.sent.append(payload)


ALICE_TOKEN = "token-alice"              # sees project p1 only; no approve scope
READER_TOKEN = "token-reader"            # p1; read-only
APPROVER_TOKEN = "token-approver"        # p1 + p2; can decide sensitive tasks
UNTRUSTED_APPROVER_TOKEN = "token-untrusted-approver"  # has the scope, not the flag
ADMIN_TOKEN = "token-admin"              # sees everything, can decide
EXPIRED_TOKEN = "token-expired"

# A sensitive-keyword instruction is enough to force `evaluate_task_policy` to
# SENSITIVE regardless of mode (`shared/policy.py:SENSITIVE_KEYWORDS`), which
# is what puts a task into `awaiting_approval` — the only way to create a
# decision at all.
SENSITIVE_INSTRUCTION = "deploy the release to production"


@pytest.fixture
def users_file(tmp_path):
    path = tmp_path / "users.json"
    path.write_text(
        json.dumps(
            {
                "users": [
                    {
                        "user_id": "alice",
                        "email": "alice@example.com",
                        "password_hash": "x",
                        "roles": [],
                        "allowed_projects": ["p1"],
                        "scopes": ["codexbridge.read"],
                        "enabled": True,
                    },
                    {
                        "user_id": "reader",
                        "email": "reader@example.com",
                        "password_hash": "x",
                        "roles": [],
                        "allowed_projects": ["p1"],
                        "scopes": ["codexbridge.read"],
                        "enabled": True,
                    },
                    {
                        "user_id": "approver",
                        "email": "approver@example.com",
                        "password_hash": "x",
                        "roles": [],
                        "allowed_projects": ["p1", "p2"],
                        "scopes": ["codexbridge.read", "codexbridge.task.approve"],
                        "enabled": True,
                        "can_approve_sensitive": True,
                    },
                    {
                        "user_id": "untrusted",
                        "email": "untrusted@example.com",
                        "password_hash": "x",
                        "roles": [],
                        "allowed_projects": ["p1"],
                        "scopes": ["codexbridge.read", "codexbridge.task.approve"],
                        "enabled": True,
                        "can_approve_sensitive": False,
                    },
                    {
                        "user_id": "admin",
                        "email": "admin@example.com",
                        "password_hash": "x",
                        "roles": ["admin"],
                        "allowed_projects": [],
                        "scopes": ["codexbridge.admin"],
                        "enabled": True,
                    },
                ]
            }
        ),
        encoding="utf-8",
    )
    return str(path)


@pytest.fixture
async def api(users_file, monkeypatch):
    """A real app over a real database, seeded with two projects."""
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
                    executor_id="E1", display_name="E1", machine_token="t",
                    allowed_projects=["p1", "p2"], enabled=True,
                )
            ],
            projects=[
                ProjectRegistration(
                    project_id=pid, name=pid, path=f"/srv/{pid}",
                    allowed_modes=[TaskMode.ANALYZE], max_timeout_seconds=600,
                    sensitive_patterns=[], enabled=True,
                )
                for pid in ("p1", "p2")
            ],
        )
        future = datetime.now(timezone.utc) + timedelta(hours=1)
        for token, user_id, scopes in (
            (ALICE_TOKEN, "alice", ["codexbridge.read"]),
            (READER_TOKEN, "reader", ["codexbridge.read"]),
            (APPROVER_TOKEN, "approver", ["codexbridge.read", "codexbridge.task.approve"]),
            (UNTRUSTED_APPROVER_TOKEN, "untrusted", ["codexbridge.read", "codexbridge.task.approve"]),
            (ADMIN_TOKEN, "admin", ["codexbridge.admin"]),
        ):
            await store.create_oauth_access_token(
                seed, token=token, client_id="c", user_id=user_id,
                scopes=scopes, expires_at=future,
            )
        await store.create_oauth_access_token(
            seed, token=EXPIRED_TOKEN, client_id="c", user_id="alice",
            scopes=["codexbridge.read"],
            expires_at=datetime.now(timezone.utc) - timedelta(hours=1),
        )

    app = FastAPI(openapi_url=None, docs_url=None, redoc_url=None)
    install_api_conventions(app)
    app.include_router(decisions_routes.router)

    async def override():
        async with factory() as s:
            yield s

    app.dependency_overrides[get_session] = override

    # A real AgentHub (issues #18/#20's DoD: tested against the real hub, not
    # a stub) over this test's own in-memory DB. `_resolve()` reaches it via
    # `from gateway.app.main import hub` — a late import, same convention as
    # `routes/sessions.py` — so it must be `gateway.app.main.hub` specifically
    # that gets replaced, or the route would touch the real production hub
    # (bound to a different database) instead of this test's.
    #
    # No executor is registered as connected by default: every test that
    # predates issues #18/#20 asserts an approval leaves the task at
    # `waiting_executor`, which is only still true when nothing dispatches it
    # — i.e. E1 offline, the same as before this fixture wired a hub in at
    # all. Tests exercising the new dispatch behaviour connect E1 themselves.
    hub = AgentHub(factory)
    import gateway.app.main as main_module

    monkeypatch.setattr(main_module, "hub", hub, raising=False)

    client = TestClient(app, raise_server_exceptions=False)
    client.factory = factory  # type: ignore[attr-defined]
    client.hub = hub          # type: ignore[attr-defined]
    yield client
    await engine.dispose()


async def make_decision(
    factory,
    project_id: str = "p1",
    instruction: str = SENSITIVE_INSTRUCTION,
    requested_by_user_id: str = "alice",
    requested_by_email: str = "alice@example.com",
):
    async with factory() as s:
        task = await store.create_task(
            s,
            SubmitTaskRequest(
                executor_id="E1", project_id=project_id, instruction=instruction,
                mode=TaskMode.ANALYZE, priority=TaskPriority.NORMAL, timeout_seconds=60,
                expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
            ),
            executor_online=True,
            requested_by_user_id=requested_by_user_id,
            requested_by_email=requested_by_email,
        )
        assert task.state == TaskState.AWAITING_APPROVAL.value, "fixture must produce a decision"
        return task


async def make_plain_task(factory, project_id: str = "p1"):
    """A task nobody was ever asked to decide on — not a decision."""
    async with factory() as s:
        return await store.create_task(
            s,
            SubmitTaskRequest(
                executor_id="E1", project_id=project_id, instruction="analyze it",
                mode=TaskMode.ANALYZE, priority=TaskPriority.NORMAL, timeout_seconds=60,
                expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
            ),
            executor_online=True,
        )


async def make_forge_decision(
    factory,
    project_id: str = "p1",
    repo_identity: str = "acme/widgets",
    title: str = "Bug found",
    body: str = "Steps to reproduce",
) -> ForgeOperationModel:
    """A forge WRITE — born `awaiting_approval` — issue #79/#80 (PR B4)."""
    async with factory() as s:
        row = await store.create_forge_operation(
            s,
            executor_id="E1",
            project_id=project_id,
            operation=ForgeOperationRequest(
                kind=ForgeOperationKind.ISSUE_OPEN, repo_identity=repo_identity, title=title, body=body
            ),
        )
        assert row.state == "awaiting_approval", "fixture must produce a forge decision"
        return row


async def make_forge_read(factory, project_id: str = "p1", repo_identity: str = "acme/widgets") -> ForgeOperationModel:
    """A forge READ (`issue_list`) — born `approved`, never a decision."""
    async with factory() as s:
        row = await store.create_forge_operation(
            s,
            executor_id="E1",
            project_id=project_id,
            operation=ForgeOperationRequest(kind=ForgeOperationKind.ISSUE_LIST, repo_identity=repo_identity),
        )
        assert row.state == "approved"
        return row


def auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


async def audit_events(factory, event_type: str) -> list[AuditEventModel]:
    async with factory() as s:
        rows = await s.execute(select(AuditEventModel).where(AuditEventModel.event_type == event_type))
        return list(rows.scalars())


# --------------------------------------------------------------------------
# Authentication and visibility
# --------------------------------------------------------------------------


async def test_decisions_require_a_token(api) -> None:
    response = api.get("/api/v1/decisions")
    assert response.status_code == 401
    assert response.json()["code"] == "unauthenticated"


async def test_an_expired_token_is_refused(api) -> None:
    assert api.get("/api/v1/decisions", headers=auth(EXPIRED_TOKEN)).status_code == 401


async def test_a_decision_in_an_invisible_project_is_not_found_not_forbidden(api) -> None:
    mine = await make_decision(api.factory, "p1")
    theirs = await make_decision(api.factory, "p2")

    assert api.get(f"/api/v1/decisions/{mine.id}", headers=auth(ALICE_TOKEN)).status_code == 200
    response = api.get(f"/api/v1/decisions/{theirs.id}", headers=auth(ALICE_TOKEN))
    assert response.status_code == 404
    assert response.json()["code"] == "not_found"


async def test_a_plain_task_is_not_a_decision(api) -> None:
    """A session id that exists but never needed approval is not found here."""
    task = await make_plain_task(api.factory, "p1")
    response = api.get(f"/api/v1/decisions/{task.id}", headers=auth(ALICE_TOKEN))
    assert response.status_code == 404


async def test_the_list_is_filtered_before_it_is_paged(api) -> None:
    await make_decision(api.factory, "p1")
    await make_decision(api.factory, "p2")
    await make_decision(api.factory, "p2")
    await make_plain_task(api.factory, "p1")

    body = api.get("/api/v1/decisions", headers=auth(ALICE_TOKEN)).json()
    assert [item["projectId"] for item in body["items"]] == ["p1"]

    admin = api.get("/api/v1/decisions", headers=auth(ADMIN_TOKEN)).json()
    assert len(admin["items"]) == 3


async def test_the_cursor_walks_every_decision_once(api) -> None:
    """`list_decisions_page` reuses `pagination.paginate`'s over-fetch-by-one
    scheme (`gateway/app/services/store.py`) — pin the round trip actually
    works end to end, the same way `test_sessions.py`'s sibling test does for
    `/api/v1/sessions`.
    """
    for index in range(7):
        await make_decision(api.factory, "p1", instruction=f"{SENSITIVE_INSTRUCTION} {index}")

    seen: list[str] = []
    cursor = None
    for _ in range(10):
        params = {"limit": 3}
        if cursor:
            params["cursor"] = cursor
        body = api.get("/api/v1/decisions", headers=auth(ADMIN_TOKEN), params=params).json()
        seen.extend(item["id"] for item in body["items"])
        cursor = body["page"]["nextCursor"]
        if not body["page"]["hasMore"]:
            break

    assert len(seen) == 7
    assert len(set(seen)) == 7, "a decision was returned twice"


async def test_the_project_filter_only_narrows_never_widens(api) -> None:
    await make_decision(api.factory, "p1")
    await make_decision(api.factory, "p2")

    response = api.get(
        "/api/v1/decisions", headers=auth(ALICE_TOKEN), params={"project": "p2"}
    )
    assert response.json()["items"] == [], "alice cannot see p2 no matter what she asks for"

    response = api.get(
        "/api/v1/decisions", headers=auth(APPROVER_TOKEN), params={"project": "p2"}
    )
    assert [item["projectId"] for item in response.json()["items"]] == ["p2"]


async def test_the_decision_body_never_carries_the_project_path(api) -> None:
    task = await make_decision(api.factory, "p1")
    text = api.get(f"/api/v1/decisions/{task.id}", headers=auth(ALICE_TOKEN)).text
    assert "/srv/p1" not in text


async def test_the_request_field_is_redacted(api) -> None:
    task = await make_decision(
        api.factory, "p1", instruction="deploy with token=abcdef1234567890 from /home/esteban/app"
    )
    body = api.get(f"/api/v1/decisions/{task.id}", headers=auth(ALICE_TOKEN)).json()
    assert "abcdef1234567890" not in body["request"]
    assert "/home/esteban" not in body["request"]


# --------------------------------------------------------------------------
# Filters
# --------------------------------------------------------------------------


async def test_state_filter_separates_pending_from_resolved(api) -> None:
    pending = await make_decision(api.factory, "p1")
    resolved = await make_decision(api.factory, "p1")
    etag = api.get(f"/api/v1/decisions/{resolved.id}", headers=auth(APPROVER_TOKEN)).headers["ETag"]
    api.post(
        f"/api/v1/decisions/{resolved.id}/approve",
        headers={**auth(APPROVER_TOKEN), "If-Match": etag},
        json={"confirm": True},
    )

    only_pending = api.get(
        "/api/v1/decisions", headers=auth(APPROVER_TOKEN), params={"state": "pending"}
    ).json()
    assert [item["id"] for item in only_pending["items"]] == [pending.id]

    only_approved = api.get(
        "/api/v1/decisions", headers=auth(APPROVER_TOKEN), params={"state": "approved"}
    ).json()
    assert [item["id"] for item in only_approved["items"]] == [resolved.id]


async def test_risk_and_urgency_filters(api) -> None:
    decision = await make_decision(api.factory, "p1")
    assert decision.priority == TaskPriority.NORMAL.value

    hit = api.get(
        "/api/v1/decisions", headers=auth(APPROVER_TOKEN),
        params={"risk": "sensitive", "urgency": "normal"},
    ).json()
    assert [item["id"] for item in hit["items"]] == [decision.id]

    miss = api.get(
        "/api/v1/decisions", headers=auth(APPROVER_TOKEN), params={"risk": "read"}
    ).json()
    assert miss["items"] == []


async def test_deadline_filters(api) -> None:
    near = await make_decision(api.factory, "p1")
    async with api.factory() as s:
        from sqlalchemy import update
        from gateway.app.models.entities import TaskModel

        await s.execute(
            update(TaskModel).where(TaskModel.id == near.id).values(
                expires_at=datetime(2026, 1, 1, tzinfo=timezone.utc)
            )
        )
        await s.commit()
    far = await make_decision(api.factory, "p1")

    before = api.get(
        "/api/v1/decisions", headers=auth(APPROVER_TOKEN),
        params={"deadlineBefore": "2026-06-01T00:00:00Z"},
    ).json()
    assert [item["id"] for item in before["items"]] == [near.id]

    after = api.get(
        "/api/v1/decisions", headers=auth(APPROVER_TOKEN),
        params={"deadlineAfter": "2026-06-01T00:00:00Z"},
    ).json()
    assert [item["id"] for item in after["items"]] == [far.id]


# --------------------------------------------------------------------------
# Authorization to decide
# --------------------------------------------------------------------------


async def test_reading_needs_no_approval_scope(api) -> None:
    task = await make_decision(api.factory, "p1")
    assert api.get(f"/api/v1/decisions/{task.id}", headers=auth(READER_TOKEN)).status_code == 200


async def test_deciding_needs_the_approve_scope(api) -> None:
    task = await make_decision(api.factory, "p1")
    response = api.post(
        f"/api/v1/decisions/{task.id}/approve",
        headers={**auth(READER_TOKEN), "If-Match": f'"{task.revision}"'},
        json={"confirm": True},
    )
    assert response.status_code == 403
    assert response.json()["code"] == "permission_denied"


async def test_the_scope_alone_is_not_enough_for_a_sensitive_decision(api) -> None:
    """`can_approve_sensitive` is checked on top of `codexbridge.task.approve`.

    Mirrors the MCP transport's own `approve_codex_task` check
    (`gateway/app/mcp/server.py`) — a token carrying the scope for a user the
    operator never trusted with a sensitive call must still be refused.
    """
    task = await make_decision(api.factory, "p1")
    response = api.post(
        f"/api/v1/decisions/{task.id}/approve",
        headers={**auth(UNTRUSTED_APPROVER_TOKEN), "If-Match": f'"{task.revision}"'},
        json={"confirm": True},
    )
    assert response.status_code == 403


async def test_auth_me_agrees_with_the_untrusted_approver_gate(api) -> None:
    """`GET /auth/me` is not mounted in this fixture; assert the function it calls."""
    from gateway.app.api import permissions
    from gateway.app.core.users import AuthenticatedPrincipal

    untrusted = AuthenticatedPrincipal(
        user_id="untrusted", email="untrusted@example.com",
        scopes=["codexbridge.task.approve"], can_approve_sensitive=False,
    )
    assert permissions.is_allowed(untrusted, permissions.DECISIONS_DECIDE) is False

    trusted = AuthenticatedPrincipal(
        user_id="approver", email="approver@example.com",
        scopes=["codexbridge.task.approve"], can_approve_sensitive=True,
    )
    assert permissions.is_allowed(trusted, permissions.DECISIONS_DECIDE) is True


# --------------------------------------------------------------------------
# Approve
# --------------------------------------------------------------------------


async def test_approve_requires_if_match(api) -> None:
    task = await make_decision(api.factory, "p1")
    response = api.post(
        f"/api/v1/decisions/{task.id}/approve", headers=auth(APPROVER_TOKEN), json={"confirm": True}
    )
    assert response.status_code == 428


async def test_approve_with_a_stale_etag_is_refused(api) -> None:
    task = await make_decision(api.factory, "p1")
    response = api.post(
        f"/api/v1/decisions/{task.id}/approve",
        headers={**auth(APPROVER_TOKEN), "If-Match": '"999"'},
        json={"confirm": True},
    )
    assert response.status_code == 412
    assert response.json()["code"] == "stale_write"


async def test_approving_a_critical_decision_without_confirm_is_refused(api) -> None:
    task = await make_decision(api.factory, "p1")
    response = api.post(
        f"/api/v1/decisions/{task.id}/approve",
        headers={**auth(APPROVER_TOKEN), "If-Match": f'"{task.revision}"'},
        json={},
    )
    assert response.status_code == 400
    assert response.json()["code"] == "validation_failed"
    assert response.json()["details"][0]["field"] == "/confirm"

    # The task must be untouched: a refused approval is not a partial one.
    async with api.factory() as s:
        unchanged = await store.get_task(s, task.id)
    assert unchanged.state == TaskState.AWAITING_APPROVAL.value


async def test_approving_with_confirm_resolves_the_decision(api) -> None:
    task = await make_decision(api.factory, "p1")
    response = api.post(
        f"/api/v1/decisions/{task.id}/approve",
        headers={**auth(APPROVER_TOKEN), "If-Match": f'"{task.revision}"'},
        json={"confirm": True, "reason": "looks safe"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["state"] == "approved"
    assert body["rationale"] == "looks safe"
    assert response.headers["ETag"] != f'"{task.revision}"'

    async with api.factory() as s:
        updated = await store.get_task(s, task.id)
    assert updated.state == TaskState.WAITING_EXECUTOR.value


async def test_approving_an_already_resolved_decision_is_a_conflict(api) -> None:
    task = await make_decision(api.factory, "p1")
    first = api.post(
        f"/api/v1/decisions/{task.id}/approve",
        headers={**auth(APPROVER_TOKEN), "If-Match": f'"{task.revision}"'},
        json={"confirm": True},
    )
    etag = first.headers["ETag"]

    second = api.post(
        f"/api/v1/decisions/{task.id}/approve",
        headers={**auth(APPROVER_TOKEN), "If-Match": etag},
        json={"confirm": True},
    )
    assert second.status_code == 409
    assert second.json()["code"] == "conflict"


async def test_a_retried_approve_replays_instead_of_acting_twice(api) -> None:
    task = await make_decision(api.factory, "p1")
    headers = {
        **auth(APPROVER_TOKEN),
        "If-Match": f'"{task.revision}"',
        "Idempotency-Key": "k-approve-1",
    }

    first = api.post(f"/api/v1/decisions/{task.id}/approve", headers=headers, json={"confirm": True})
    second = api.post(f"/api/v1/decisions/{task.id}/approve", headers=headers, json={"confirm": True})

    assert first.status_code == 200
    assert second.status_code == 200
    assert second.headers.get("Idempotent-Replay") == "true"
    assert second.json() == first.json()

    async with api.factory() as s:
        updated = await store.get_task(s, task.id)
    assert updated.revision == task.revision + 1, "the write must not have happened twice"


async def test_approve_records_the_deciding_actor(api) -> None:
    task = await make_decision(api.factory, "p1")
    api.post(
        f"/api/v1/decisions/{task.id}/approve",
        headers={**auth(APPROVER_TOKEN), "If-Match": f'"{task.revision}"'},
        json={"confirm": True},
    )
    events = await audit_events(api.factory, "task.decision_resolved_by_actor")
    assert len(events) == 1
    payload = json.loads(events[0].payload_json)
    assert payload["actor_id"] == "approver"
    assert payload["outcome"] == "approved"


# --------------------------------------------------------------------------
# Dispatch on approve — issue #20 (duplicate: #18)
#
# `POST .../approve` used to call `store.decide_task_approval` and stop,
# leaving an approved task sitting in `waiting_executor` even when its
# executor was connected and idle — nothing woke the queue for it until an
# unrelated event happened to. These exercise the real `AgentHub`
# (`api.hub`), not a stub, per the issue's own DoD.
# --------------------------------------------------------------------------


async def test_approving_dispatches_to_a_connected_idle_executor(api) -> None:
    task = await make_decision(api.factory, "p1")
    await api.hub.register("E1", _DummyWebSocket())

    response = api.post(
        f"/api/v1/decisions/{task.id}/approve",
        headers={**auth(APPROVER_TOKEN), "If-Match": f'"{task.revision}"'},
        json={"confirm": True},
    )
    assert response.status_code == 200

    async with api.factory() as s:
        updated = await store.get_task(s, task.id)
    # Dispatched, not just approved: `AgentHub.dispatch_next` moves a
    # dispatched task straight to RUNNING. Left at `waiting_executor` would
    # mean the fix's own bug — the exact failure #18/#20 describe.
    assert updated.state == TaskState.RUNNING.value

    connection = api.hub.connections["E1"]
    sent_types = [msg["type"] for msg in connection.websocket.sent]
    assert "task.dispatch" in sent_types


async def test_approve_response_revision_matches_the_post_dispatch_task_after_same_request_dispatch(
    api,
) -> None:
    """Council round-1 finding on this issue: `_resolve` fetches `updated`
    before `hub.dispatch_available` runs, and `dispatch_available` bumps
    `revision` again through its own session (`AgentHub.session_factory`) —
    same-request dispatch, not a later event, moves the task to `running`.
    Without refreshing `updated` afterward, the response body's `revision`
    and its `ETag` header both report the pre-dispatch revision while the
    task's real DB revision is one higher, so a client trusting that ETag
    for its next `If-Match` gets a spurious 409 on a revision it was just
    handed as current.
    """
    task = await make_decision(api.factory, "p1")
    await api.hub.register("E1", _DummyWebSocket())

    response = api.post(
        f"/api/v1/decisions/{task.id}/approve",
        headers={**auth(APPROVER_TOKEN), "If-Match": f'"{task.revision}"'},
        json={"confirm": True},
    )
    assert response.status_code == 200

    async with api.factory() as s:
        updated = await store.get_task(s, task.id)
    # Same-request dispatch happened (state is running, not waiting_executor,
    # confirming the queue was nudged before the response was built) — so the
    # response must reflect *that* revision, not the pre-dispatch one.
    assert updated.state == TaskState.RUNNING.value
    assert response.json()["revision"] == updated.revision
    assert response.headers["ETag"] == f'"{updated.revision}"'


async def test_approving_leaves_the_task_waiting_when_the_executor_is_offline(api) -> None:
    """No regression on the pre-existing (disconnected) case: `api.hub` has
    no registered executor, matching every other test in this file."""
    task = await make_decision(api.factory, "p1")

    response = api.post(
        f"/api/v1/decisions/{task.id}/approve",
        headers={**auth(APPROVER_TOKEN), "If-Match": f'"{task.revision}"'},
        json={"confirm": True},
    )
    assert response.status_code == 200

    async with api.factory() as s:
        updated = await store.get_task(s, task.id)
    assert updated.state == TaskState.WAITING_EXECUTOR.value
    assert api.hub.connections == {}


async def test_approving_when_the_executor_is_at_capacity_does_not_bypass_the_concurrency_gate(api) -> None:
    task = await make_decision(api.factory, "p1")
    await api.hub.register("E1", _DummyWebSocket())
    # E1's `max_concurrent_tasks` is the default (1) — occupy that one slot
    # with an unrelated task before approving.
    api.hub.running_tasks["E1"] = {"some-other-task-already-running"}

    response = api.post(
        f"/api/v1/decisions/{task.id}/approve",
        headers={**auth(APPROVER_TOKEN), "If-Match": f'"{task.revision}"'},
        json={"confirm": True},
    )
    assert response.status_code == 200

    async with api.factory() as s:
        updated = await store.get_task(s, task.id)
    assert updated.state == TaskState.WAITING_EXECUTOR.value, "the fix must not bypass the capacity check"

    # Unchanged behaviour once the slot frees: the existing
    # `mark_task_finished` path (issue #17) still picks it up.
    await api.hub.mark_task_finished("E1", "some-other-task-already-running")
    async with api.factory() as s:
        after_slot_freed = await store.get_task(s, task.id)
    assert after_slot_freed.state == TaskState.RUNNING.value


async def test_reject_never_dispatches(api) -> None:
    task = await make_decision(api.factory, "p1")
    await api.hub.register("E1", _DummyWebSocket())

    response = api.post(
        f"/api/v1/decisions/{task.id}/reject",
        headers={**auth(APPROVER_TOKEN), "If-Match": f'"{task.revision}"'},
        json={"reason": "not now"},
    )
    assert response.status_code == 200
    assert api.hub.connections["E1"].websocket.sent == []


async def test_request_revision_never_dispatches(api) -> None:
    task = await make_decision(api.factory, "p1")
    await api.hub.register("E1", _DummyWebSocket())

    response = api.post(
        f"/api/v1/decisions/{task.id}/request-revision",
        headers={**auth(APPROVER_TOKEN), "If-Match": f'"{task.revision}"'},
        json={"reason": "needs another pass"},
    )
    assert response.status_code == 200
    assert api.hub.connections["E1"].websocket.sent == []


# --------------------------------------------------------------------------
# Reject
# --------------------------------------------------------------------------


async def test_reject_requires_a_non_empty_reason(api) -> None:
    task = await make_decision(api.factory, "p1")
    response = api.post(
        f"/api/v1/decisions/{task.id}/reject",
        headers={**auth(APPROVER_TOKEN), "If-Match": f'"{task.revision}"'},
        json={"reason": ""},
    )
    assert response.status_code == 422
    assert response.json()["code"] == "validation_failed"


async def test_reject_with_no_body_is_refused(api) -> None:
    task = await make_decision(api.factory, "p1")
    response = api.post(
        f"/api/v1/decisions/{task.id}/reject",
        headers={**auth(APPROVER_TOKEN), "If-Match": f'"{task.revision}"'},
        json={},
    )
    assert response.status_code == 422


async def test_rejecting_cancels_the_underlying_session(api) -> None:
    task = await make_decision(api.factory, "p1")
    response = api.post(
        f"/api/v1/decisions/{task.id}/reject",
        headers={**auth(APPROVER_TOKEN), "If-Match": f'"{task.revision}"'},
        json={"reason": "not needed anymore"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["state"] == "rejected"
    assert body["rationale"] == "not needed anymore"

    async with api.factory() as s:
        updated = await store.get_task(s, task.id)
    assert updated.state == TaskState.CANCELLED.value


async def test_rejecting_an_already_resolved_decision_is_a_conflict(api) -> None:
    task = await make_decision(api.factory, "p1")
    etag = f'"{task.revision}"'
    api.post(
        f"/api/v1/decisions/{task.id}/reject",
        headers={**auth(APPROVER_TOKEN), "If-Match": etag},
        json={"reason": "first"},
    )
    second = api.post(
        f"/api/v1/decisions/{task.id}/reject",
        headers={**auth(APPROVER_TOKEN), "If-Match": etag},
        json={"reason": "second"},
    )
    assert second.status_code in (409, 412)


# --------------------------------------------------------------------------
# Request revision
# --------------------------------------------------------------------------


async def test_request_revision_requires_a_non_empty_reason(api) -> None:
    task = await make_decision(api.factory, "p1")
    response = api.post(
        f"/api/v1/decisions/{task.id}/request-revision",
        headers={**auth(APPROVER_TOKEN), "If-Match": f'"{task.revision}"'},
        json={"reason": ""},
    )
    assert response.status_code == 422


async def test_request_revision_is_a_distinct_outcome_from_reject(api) -> None:
    task = await make_decision(api.factory, "p1")
    response = api.post(
        f"/api/v1/decisions/{task.id}/request-revision",
        headers={**auth(APPROVER_TOKEN), "If-Match": f'"{task.revision}"'},
        json={"reason": "please narrow the blast radius first"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["state"] == "revision_requested"
    assert body["state"] != "rejected"

    # It still cancels the session — there is no protocol capability to hold
    # a task open for a resubmission. See the router's module docstring.
    async with api.factory() as s:
        updated = await store.get_task(s, task.id)
    assert updated.state == TaskState.CANCELLED.value


async def test_request_revision_on_a_resolved_decision_is_a_conflict(api) -> None:
    task = await make_decision(api.factory, "p1")
    etag = f'"{task.revision}"'
    api.post(
        f"/api/v1/decisions/{task.id}/approve",
        headers={**auth(APPROVER_TOKEN), "If-Match": etag},
        json={"confirm": True},
    )
    response = api.post(
        f"/api/v1/decisions/{task.id}/request-revision",
        headers={**auth(APPROVER_TOKEN), "If-Match": etag},
        json={"reason": "too late"},
    )
    assert response.status_code in (409, 412)


# --------------------------------------------------------------------------
# Forge decisions -- issue #79/#80, WK-20260902-forge-binding (PR B4). One
# inbox, two sources: `/api/v1/decisions` now projects `ForgeOperationModel`
# rows alongside `TaskModel` ones. See `routes/decisions.py`'s own module
# docstring for the full reasoning; these tests are weighted toward what
# that docstring promises explicitly: a forge READ never shows up here, a
# forge WRITE does with an honest discriminator, ids from the two sources
# never collide, and approving a forge decision actually dispatches it —
# issue #20 does not get to happen a second time on a different table.
# --------------------------------------------------------------------------


async def test_a_forge_read_is_not_a_decision(api) -> None:
    """`issue_list` is born `approved` — it never needed a human, so it must

    never appear here, the same way a READ-mode task does not."""
    read = await make_forge_read(api.factory, "p1")
    response = api.get(f"/api/v1/decisions/{read.id}", headers=auth(ALICE_TOKEN))
    assert response.status_code == 404

    listed = api.get("/api/v1/decisions", headers=auth(ADMIN_TOKEN)).json()
    assert read.id not in [item["id"] for item in listed["items"]]


async def test_a_forge_write_appears_as_a_decision_with_an_honest_discriminator(api) -> None:
    row = await make_forge_decision(api.factory, "p1", repo_identity="acme/widgets", title="Bug found")

    response = api.get(f"/api/v1/decisions/forge:{row.id}", headers=auth(ALICE_TOKEN))
    assert response.status_code == 200
    body = response.json()
    assert body["id"] == f"forge:{row.id}"
    assert body["decisionType"] == "forge_operation"
    assert body["forgeKind"] == "issue_open"
    assert body["repoIdentity"] == "acme/widgets"
    assert body["state"] == "pending"
    assert body["risk"] == "sensitive"
    assert body["projectId"] == "p1"
    # The DTO shape a mobile client already reads for a task decision is
    # present here too, just null where the concept does not apply — never
    # simply absent.
    assert body["mode"] is None
    assert body["urgency"] is None
    assert body["deadline"] is None
    assert "Bug found" in body["request"]


async def test_a_task_decisions_shape_is_unchanged_when_forge_rows_also_exist(api) -> None:
    """The exact regression this PR must never cause: a task decision's DTO

    gains new, additive, null-for-tasks keys, but every field that existed
    before this PR is present and byte-for-byte the same."""
    task = await make_decision(api.factory, "p1")
    await make_forge_decision(api.factory, "p1")  # presence alone must not change the task's own shape

    body = api.get(f"/api/v1/decisions/{task.id}", headers=auth(ALICE_TOKEN)).json()
    assert body["id"] == task.id  # never prefixed
    assert body["decisionType"] == "task"
    assert body["forgeKind"] is None
    assert body["repoIdentity"] is None
    assert body["issueNumber"] is None
    assert body["mode"] == task.mode
    assert body["risk"] == task.policy_level


async def test_forge_and_task_decisions_share_one_sorted_list(api) -> None:
    task_row = await make_decision(api.factory, "p1")
    forge_row = await make_forge_decision(api.factory, "p1")

    body = api.get("/api/v1/decisions", headers=auth(APPROVER_TOKEN)).json()
    ids = [item["id"] for item in body["items"]]
    assert task_row.id in ids
    assert f"forge:{forge_row.id}" in ids
    # Newest first, across both sources, same as within one.
    created_ats = [item["createdAt"] for item in body["items"]]
    assert created_ats == sorted(created_ats, reverse=True)


async def test_forge_and_task_decision_ids_never_collide(api) -> None:
    task_row = await make_decision(api.factory, "p1")
    forge_row = await make_forge_decision(api.factory, "p1")
    assert task_row.id != forge_row.id  # true by uuid4() chance alone, but --
    assert not task_row.id.startswith("forge:")
    assert f"forge:{forge_row.id}" != task_row.id
    # The real guarantee: a forge decision's exposed id ALWAYS carries the
    # prefix, and a raw uuid4() string can never contain the ":" that makes
    # it one -- so the two id spaces this endpoint serves are disjoint by
    # construction, not by the odds of a random collision.
    assert ":" not in task_row.id
    assert ":" in f"forge:{forge_row.id}"


async def test_forge_risk_and_urgency_filters(api) -> None:
    """A forge decision has no `urgency` — an active `urgency` filter must

    exclude it, not error or silently include it."""
    forge_row = await make_forge_decision(api.factory, "p1")

    by_risk = api.get(
        "/api/v1/decisions", headers=auth(APPROVER_TOKEN), params={"risk": "sensitive"}
    ).json()
    assert f"forge:{forge_row.id}" in [item["id"] for item in by_risk["items"]]

    by_read_risk = api.get(
        "/api/v1/decisions", headers=auth(APPROVER_TOKEN), params={"risk": "read"}
    ).json()
    assert f"forge:{forge_row.id}" not in [item["id"] for item in by_read_risk["items"]]

    by_urgency = api.get(
        "/api/v1/decisions", headers=auth(APPROVER_TOKEN), params={"urgency": "normal"}
    ).json()
    assert f"forge:{forge_row.id}" not in [item["id"] for item in by_urgency["items"]]


async def test_approving_a_critical_forge_decision_without_confirm_is_refused(api) -> None:
    row = await make_forge_decision(api.factory, "p1")
    response = api.post(
        f"/api/v1/decisions/forge:{row.id}/approve",
        headers={**auth(APPROVER_TOKEN), "If-Match": f'"{row.revision}"'},
        json={},
    )
    assert response.status_code == 400


async def test_approving_a_forge_decision_dispatches(api) -> None:
    """The forge sibling of issue #20's own regression test above

    (`test_approving_dispatches_to_a_connected_idle_executor`): approving a
    forge decision through the Decision Center must not leave it sitting
    `approved`-but-never-sent the way a pre-#20 task approval used to."""
    row = await make_forge_decision(api.factory, "p1")
    await api.hub.register("E1", _DummyWebSocket())

    response = api.post(
        f"/api/v1/decisions/forge:{row.id}/approve",
        headers={**auth(APPROVER_TOKEN), "If-Match": f'"{row.revision}"'},
        json={"confirm": True},
    )
    assert response.status_code == 200
    assert response.json()["state"] == "approved"

    async with api.factory() as s:
        updated = await store.get_forge_operation(s, row.id)
    assert updated.state == "dispatched"
    assert response.json()["revision"] == updated.revision
    assert response.headers["ETag"] == f'"{updated.revision}"'

    connection = api.hub.connections["E1"]
    sent_types = [msg["type"] for msg in connection.websocket.sent]
    assert "forge.operation" in sent_types


async def test_approving_a_forge_decision_leaves_it_approved_when_the_executor_is_offline(api) -> None:
    row = await make_forge_decision(api.factory, "p1")

    response = api.post(
        f"/api/v1/decisions/forge:{row.id}/approve",
        headers={**auth(APPROVER_TOKEN), "If-Match": f'"{row.revision}"'},
        json={"confirm": True},
    )
    assert response.status_code == 200

    async with api.factory() as s:
        updated = await store.get_forge_operation(s, row.id)
    assert updated.state == "approved"  # not "dispatched" -- no envelope could have been sent


async def test_rejecting_a_forge_decision_never_dispatches(api) -> None:
    row = await make_forge_decision(api.factory, "p1")
    await api.hub.register("E1", _DummyWebSocket())

    response = api.post(
        f"/api/v1/decisions/forge:{row.id}/reject",
        headers={**auth(APPROVER_TOKEN), "If-Match": f'"{row.revision}"'},
        json={"reason": "not now"},
    )
    assert response.status_code == 200
    assert response.json()["state"] == "rejected"

    async with api.factory() as s:
        updated = await store.get_forge_operation(s, row.id)
    assert updated.state == "rejected"

    connection = api.hub.connections["E1"]
    sent_types = [msg["type"] for msg in connection.websocket.sent]
    assert "forge.operation" not in sent_types


async def test_approve_records_the_deciding_actor_for_a_forge_decision(api) -> None:
    row = await make_forge_decision(api.factory, "p1")
    api.post(
        f"/api/v1/decisions/forge:{row.id}/approve",
        headers={**auth(APPROVER_TOKEN), "If-Match": f'"{row.revision}"'},
        json={"confirm": True},
    )
    events = await audit_events(api.factory, "forge_operation.decision_resolved_by_actor")
    assert len(events) == 1
    assert events[0].payload_json is not None
    assert '"actor_id": "approver"' in events[0].payload_json
