"""Missions: the mission-control view of Sessions — issue #7.

Missions reuse `TaskModel` and `audit_events` rather than introducing a new
entity (see the module docstring in `gateway/app/api/routes/missions.py` and
`docs/api/README.md` "Missions (issue #7)"), so these tests are weighted
towards what issue #7 actually adds: the stage/risk/blocked derivation, the
timeline, and that `cancel` validates transitions and is audited — not
serialization already covered by `tests/integration/test_sessions.py`.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from gateway.app.api.routes import missions as missions_routes
from gateway.app.api.setup import install_api_conventions
from gateway.app.db.base import Base
from gateway.app.db.session import get_session
from gateway.app.services import store
from shared.protocol import (
    ExecutorRegistration,
    ProjectRegistration,
    SubmitTaskRequest,
    TaskMode,
    TaskPriority,
    TaskState,
)


ALICE_TOKEN = "token-alice"          # sees project p1 only
ADMIN_TOKEN = "token-admin"          # sees everything
READER_TOKEN = "token-reader"        # p1, but no cancel scope
EXPIRED_TOKEN = "token-expired"


class _Hub:
    def __init__(self, connected: bool = True) -> None:
        self.connected = connected
        self.sent: list = []
        self.running_tasks: dict[str, set[str]] = {}
        self.dispatch_available_calls: list[str] = []

    def is_connected(self, executor_id: str) -> bool:
        return self.connected

    async def send(self, executor_id: str, envelope) -> None:
        self.sent.append((executor_id, envelope))

    async def mark_task_finished(self, executor_id: str, task_id: str) -> None:
        self.running_tasks.setdefault(executor_id, set()).discard(task_id)

    async def dispatch_available(self, executor_id: str) -> None:
        """`create_mission` (issue #68) calls this to nudge the queue after
        creating a task. The real dispatch (queued -> running, the payload
        sent over the wire) is exercised against the real `AgentHub` in
        `test_decisions.py`/`test_agent_ack_handling.py`; this double only
        needs to record that the call happened without touching the database
        itself, the same "recording double" shape `send` above already uses.
        """
        self.dispatch_available_calls.append(executor_id)


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
                        "scopes": ["codexbridge.read", "codexbridge.task.cancel", "codexbridge.task.submit"],
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
                    allowed_modes=list(TaskMode), max_timeout_seconds=600,
                    sensitive_patterns=[], enabled=True,
                )
                for pid in ("p1", "p2")
            ],
        )
        future = datetime.now(timezone.utc) + timedelta(hours=1)
        for token, user_id, scopes in (
            (ALICE_TOKEN, "alice", ["codexbridge.read", "codexbridge.task.cancel", "codexbridge.task.submit"]),
            (READER_TOKEN, "reader", ["codexbridge.read"]),
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
    app.include_router(missions_routes.router)

    async def override():
        async with factory() as s:
            yield s

    app.dependency_overrides[get_session] = override

    hub = _Hub()
    import gateway.app.main as main_module

    monkeypatch.setattr(main_module, "hub", hub, raising=False)

    client = TestClient(app, raise_server_exceptions=False)
    client.hub = hub          # type: ignore[attr-defined]
    client.factory = factory  # type: ignore[attr-defined]
    yield client
    await engine.dispose()


async def make_task(
    factory,
    project_id: str,
    instruction: str = "analyze it",
    mode: TaskMode = TaskMode.ANALYZE,
    state: str | None = None,
):
    async with factory() as s:
        task = await store.create_task(
            s,
            SubmitTaskRequest(
                executor_id="E1", project_id=project_id, instruction=instruction,
                mode=mode, priority=TaskPriority.NORMAL, timeout_seconds=60,
                expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
            ),
            executor_online=True,
        )
        if state:
            task = await store.update_task_state(s, task.id, TaskState(state))
        return task


def auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


# --------------------------------------------------------------------------
# Authentication and visibility
# --------------------------------------------------------------------------


async def test_missions_require_a_token(api) -> None:
    response = api.get("/api/v1/missions")
    assert response.status_code == 401
    assert response.json()["code"] == "unauthenticated"


async def test_an_expired_token_is_refused(api) -> None:
    assert api.get("/api/v1/missions", headers=auth(EXPIRED_TOKEN)).status_code == 401


async def test_a_mission_in_an_invisible_project_is_not_found_not_forbidden(api) -> None:
    mine = await make_task(api.factory, "p1")
    theirs = await make_task(api.factory, "p2")

    assert api.get(f"/api/v1/missions/{mine.id}", headers=auth(ALICE_TOKEN)).status_code == 200
    response = api.get(f"/api/v1/missions/{theirs.id}", headers=auth(ALICE_TOKEN))
    assert response.status_code == 404
    assert response.json()["code"] == "not_found"


async def test_the_list_is_filtered_before_it_is_paged(api) -> None:
    await make_task(api.factory, "p1")
    await make_task(api.factory, "p2")
    await make_task(api.factory, "p2")

    body = api.get("/api/v1/missions", headers=auth(ALICE_TOKEN)).json()
    assert [item["projectId"] for item in body["items"]] == ["p1"]

    admin = api.get("/api/v1/missions", headers=auth(ADMIN_TOKEN)).json()
    assert len(admin["items"]) == 3


async def test_the_mission_body_never_carries_the_project_path(api) -> None:
    task = await make_task(api.factory, "p1")
    text = api.get(f"/api/v1/missions/{task.id}", headers=auth(ALICE_TOKEN)).text
    assert "/srv/p1" not in text
    assert "path" not in json.loads(text)


# --------------------------------------------------------------------------
# Mission-control framing: stage, risk, blocked
# --------------------------------------------------------------------------


async def test_objective_and_assigned_agent_are_the_instruction_and_the_executor(api) -> None:
    task = await make_task(api.factory, "p1", instruction="implement the thing")
    body = api.get(f"/api/v1/missions/{task.id}", headers=auth(ALICE_TOKEN)).json()
    assert body["objective"] == "implement the thing"
    assert body["assignedAgent"] == "E1"


@pytest.mark.parametrize(
    ("state", "stage"),
    [
        ("queued", "pending"),
        ("waiting_executor", "pending"),
        ("running", "active"),
        ("awaiting_approval", "active"),
        ("completed", "done"),
        ("failed", "done"),
        ("cancelled", "done"),
        ("expired", "done"),
        ("lost", "done"),
    ],
)
async def test_stage_groups_state_into_three_phases(api, state: str, stage: str) -> None:
    task = await make_task(api.factory, "p1", state=state)
    body = api.get(f"/api/v1/missions/{task.id}", headers=auth(ALICE_TOKEN)).json()
    assert body["state"] == state
    assert body["stage"] == stage


@pytest.mark.parametrize(
    ("mode", "risk"),
    [
        (TaskMode.ANALYZE, "read"),
        (TaskMode.REVIEW, "read"),
        (TaskMode.TEST, "read"),
        (TaskMode.EDIT, "controlled_write"),
        (TaskMode.IMPLEMENT, "controlled_write"),
    ],
)
async def test_risk_is_derived_from_mode(api, mode: TaskMode, risk: str) -> None:
    task = await make_task(api.factory, "p1", mode=mode)
    body = api.get(f"/api/v1/missions/{task.id}", headers=auth(ALICE_TOKEN)).json()
    assert body["risk"] == risk


async def test_a_sensitive_instruction_overrides_risk_to_sensitive(api) -> None:
    """The keyword-escalation path recorded on `approval_state` at creation."""
    task = await make_task(api.factory, "p1", instruction="run terraform apply now", mode=TaskMode.IMPLEMENT)
    body = api.get(f"/api/v1/missions/{task.id}", headers=auth(ALICE_TOKEN)).json()
    assert body["state"] == "awaiting_approval"
    assert body["risk"] == "sensitive"


async def test_a_mission_awaiting_approval_is_blocked_with_a_reason(api) -> None:
    task = await make_task(api.factory, "p1", instruction="deploy to production", mode=TaskMode.IMPLEMENT)
    body = api.get(f"/api/v1/missions/{task.id}", headers=auth(ALICE_TOKEN)).json()
    assert body["blocked"] is True
    assert body["blockedReason"]["code"] == "awaiting_approval"
    assert body["blockedReason"]["summary"]


async def test_a_running_mission_is_not_blocked(api) -> None:
    task = await make_task(api.factory, "p1", state="running")
    body = api.get(f"/api/v1/missions/{task.id}", headers=auth(ALICE_TOKEN)).json()
    assert body["blocked"] is False
    assert body["blockedReason"] is None


# --------------------------------------------------------------------------
# Filters
# --------------------------------------------------------------------------


async def test_stage_filter_restricts_the_list(api) -> None:
    await make_task(api.factory, "p1", state="queued")
    await make_task(api.factory, "p1", state="running")
    await make_task(api.factory, "p1", state="completed")

    body = api.get(
        "/api/v1/missions", headers=auth(ALICE_TOKEN), params={"stage": "done"}
    ).json()
    assert [item["state"] for item in body["items"]] == ["completed"]


async def test_state_and_stage_together_intersect(api) -> None:
    await make_task(api.factory, "p1", state="queued")
    await make_task(api.factory, "p1", state="running")

    body = api.get(
        "/api/v1/missions",
        headers=auth(ALICE_TOKEN),
        params={"stage": "pending", "state": "running"},
    ).json()
    assert body["items"] == []
    assert body["page"]["hasMore"] is False


async def test_risk_filter_restricts_the_list(api) -> None:
    await make_task(api.factory, "p1", mode=TaskMode.ANALYZE)
    await make_task(api.factory, "p1", mode=TaskMode.IMPLEMENT)

    body = api.get(
        "/api/v1/missions", headers=auth(ALICE_TOKEN), params={"risk": "controlled_write"}
    ).json()
    assert len(body["items"]) == 1
    assert body["items"][0]["risk"] == "controlled_write"


async def test_blocked_filter_restricts_the_list(api) -> None:
    await make_task(api.factory, "p1", instruction="run rm -rf now", mode=TaskMode.IMPLEMENT)
    await make_task(api.factory, "p1", mode=TaskMode.ANALYZE)

    blocked = api.get(
        "/api/v1/missions", headers=auth(ALICE_TOKEN), params={"blocked": "true"}
    ).json()
    assert len(blocked["items"]) == 1
    assert blocked["items"][0]["blocked"] is True

    not_blocked = api.get(
        "/api/v1/missions", headers=auth(ALICE_TOKEN), params={"blocked": "false"}
    ).json()
    assert len(not_blocked["items"]) == 1
    assert not_blocked["items"][0]["blocked"] is False


async def test_project_filter_is_intersected_with_visibility(api) -> None:
    await make_task(api.factory, "p1")
    await make_task(api.factory, "p2")

    admin_p1 = api.get(
        "/api/v1/missions", headers=auth(ADMIN_TOKEN), params={"projectId": "p1"}
    ).json()
    assert [item["projectId"] for item in admin_p1["items"]] == ["p1"]

    alice_p2 = api.get(
        "/api/v1/missions", headers=auth(ALICE_TOKEN), params={"projectId": "p2"}
    ).json()
    assert alice_p2["items"] == [], "alice cannot see p2, so asking for it returns nothing, not an error"


async def test_the_cursor_walks_every_mission_once(api) -> None:
    for index in range(7):
        await make_task(api.factory, "p1", instruction=f"task {index}")

    seen: list[str] = []
    cursor = None
    for _ in range(10):
        params = {"limit": 3}
        if cursor:
            params["cursor"] = cursor
        body = api.get("/api/v1/missions", headers=auth(ALICE_TOKEN), params=params).json()
        seen.extend(item["id"] for item in body["items"])
        cursor = body["page"]["nextCursor"]
        if not body["page"]["hasMore"]:
            break

    assert len(seen) == 7
    assert len(set(seen)) == 7


# --------------------------------------------------------------------------
# Timeline
# --------------------------------------------------------------------------


async def test_timeline_of_an_invisible_mission_is_not_found(api) -> None:
    theirs = await make_task(api.factory, "p2")
    response = api.get(f"/api/v1/missions/{theirs.id}/timeline", headers=auth(ALICE_TOKEN))
    assert response.status_code == 404


async def test_timeline_reports_creation_and_state_changes_oldest_first(api) -> None:
    task = await make_task(api.factory, "p1", state="running")
    async with api.factory() as s:
        await store.update_task_state(s, task.id, TaskState.COMPLETED)

    body = api.get(f"/api/v1/missions/{task.id}/timeline", headers=auth(ALICE_TOKEN)).json()
    types = [item["type"] for item in body["items"]]
    assert types == ["task.created", "task.state_changed", "task.state_changed"]
    ats = [item["at"] for item in body["items"]]
    assert ats == sorted(ats), "timeline must read oldest first"
    assert body["items"][0]["summary"] == "Mission created."


async def test_timeline_pages_by_cursor(api) -> None:
    task = await make_task(api.factory, "p1")
    async with api.factory() as s:
        for _ in range(4):
            await store.update_task_state(s, task.id, TaskState.RUNNING)

    seen: list[str] = []
    cursor = None
    for _ in range(10):
        params = {"limit": 2}
        if cursor:
            params["cursor"] = cursor
        body = api.get(
            f"/api/v1/missions/{task.id}/timeline", headers=auth(ALICE_TOKEN), params=params
        ).json()
        seen.extend(f"{item['type']}:{item['at']}" for item in body["items"])
        cursor = body["page"]["nextCursor"]
        if not body["page"]["hasMore"]:
            break

    # If pagination repeated or dropped a row, this count would not land on
    # exactly created + 4 state_changed.
    assert len(seen) == 5


async def test_a_mission_timeline_cursor_is_not_valid_for_another_mission(api) -> None:
    a = await make_task(api.factory, "p1", state="running")
    b = await make_task(api.factory, "p1")

    page = api.get(
        f"/api/v1/missions/{a.id}/timeline", headers=auth(ALICE_TOKEN), params={"limit": 1}
    ).json()
    cursor = page["page"]["nextCursor"]

    response = api.get(
        f"/api/v1/missions/{b.id}/timeline", headers=auth(ALICE_TOKEN), params={"cursor": cursor}
    )
    assert response.status_code == 400


async def test_timeline_entries_are_redacted(api) -> None:
    task = await make_task(api.factory, "p1", state="running")
    async with api.factory() as s:
        await store.update_task_state(
            s, task.id, TaskState.FAILED, error="failed reading /home/esteban/secret.py"
        )

    text = api.get(f"/api/v1/missions/{task.id}/timeline", headers=auth(ALICE_TOKEN)).text
    assert "/home/esteban" not in text


# --------------------------------------------------------------------------
# Cancel
# --------------------------------------------------------------------------


async def test_a_token_without_the_scope_cannot_cancel(api) -> None:
    task = await make_task(api.factory, "p1", state="running")
    response = api.post(
        f"/api/v1/missions/{task.id}/cancel",
        headers={**auth(READER_TOKEN), "If-Match": f'"{task.revision}"'},
    )
    assert response.status_code == 403
    assert response.json()["code"] == "permission_denied"


async def test_cancel_requires_if_match(api) -> None:
    task = await make_task(api.factory, "p1", state="running")
    response = api.post(f"/api/v1/missions/{task.id}/cancel", headers=auth(ALICE_TOKEN))
    assert response.status_code == 428


async def test_cancel_with_a_stale_etag_is_refused(api) -> None:
    task = await make_task(api.factory, "p1", state="running")
    response = api.post(
        f"/api/v1/missions/{task.id}/cancel",
        headers={**auth(ALICE_TOKEN), "If-Match": '"1"'},
    )
    assert response.status_code == 412
    assert response.json()["code"] == "stale_write"


async def test_cancel_transitions_a_running_mission_and_notifies_the_executor(api) -> None:
    task = await make_task(api.factory, "p1", state="running")
    detail = api.get(f"/api/v1/missions/{task.id}", headers=auth(ALICE_TOKEN))
    etag = detail.headers["ETag"]

    response = api.post(
        f"/api/v1/missions/{task.id}/cancel", headers={**auth(ALICE_TOKEN), "If-Match": etag}
    )
    assert response.status_code == 200
    body = response.json()
    assert body["state"] == TaskState.CANCELLED.value
    assert body["stage"] == "done"
    assert body["executorNotified"] is True
    assert response.headers["ETag"] != etag
    assert api.hub.sent and api.hub.sent[0][0] == "E1"


async def test_cancelling_a_finished_mission_is_a_conflict(api) -> None:
    """State-transition validation — issue #7's acceptance criterion."""
    task = await make_task(api.factory, "p1", state="completed")
    detail = api.get(f"/api/v1/missions/{task.id}", headers=auth(ALICE_TOKEN))
    response = api.post(
        f"/api/v1/missions/{task.id}/cancel",
        headers={**auth(ALICE_TOKEN), "If-Match": detail.headers["ETag"]},
    )
    assert response.status_code == 409
    assert response.json()["code"] == "conflict"


async def test_cancel_an_already_cancelled_mission_is_also_a_conflict(api) -> None:
    task = await make_task(api.factory, "p1", state="cancelled")
    detail = api.get(f"/api/v1/missions/{task.id}", headers=auth(ALICE_TOKEN))
    response = api.post(
        f"/api/v1/missions/{task.id}/cancel",
        headers={**auth(ALICE_TOKEN), "If-Match": detail.headers["ETag"]},
    )
    assert response.status_code == 409


async def test_a_disconnected_executor_does_not_block_cancel(api) -> None:
    api.hub.connected = False
    task = await make_task(api.factory, "p1", state="running")
    detail = api.get(f"/api/v1/missions/{task.id}", headers=auth(ALICE_TOKEN))
    response = api.post(
        f"/api/v1/missions/{task.id}/cancel",
        headers={**auth(ALICE_TOKEN), "If-Match": detail.headers["ETag"]},
    )
    assert response.status_code == 200
    assert response.json()["executorNotified"] is False


async def test_a_retried_cancel_replays_instead_of_acting_twice(api) -> None:
    task = await make_task(api.factory, "p1", state="running")
    detail = api.get(f"/api/v1/missions/{task.id}", headers=auth(ALICE_TOKEN))
    headers = {**auth(ALICE_TOKEN), "If-Match": detail.headers["ETag"], "Idempotency-Key": "k-1"}

    first = api.post(f"/api/v1/missions/{task.id}/cancel", headers=headers)
    second = api.post(f"/api/v1/missions/{task.id}/cancel", headers=headers)

    assert first.status_code == 200
    assert second.status_code == 200
    assert second.headers.get("Idempotent-Replay") == "true"
    assert second.json() == first.json()
    assert len(api.hub.sent) == 1


async def test_cancel_is_audited_with_the_actor(api) -> None:
    """Destructive commands require authenticated actor context and are audited."""
    from sqlalchemy import select

    from gateway.app.models.entities import AuditEventModel

    task = await make_task(api.factory, "p1", state="running")
    detail = api.get(f"/api/v1/missions/{task.id}", headers=auth(ALICE_TOKEN))
    api.post(
        f"/api/v1/missions/{task.id}/cancel",
        headers={**auth(ALICE_TOKEN), "If-Match": detail.headers["ETag"]},
    )

    async with api.factory() as s:
        rows = (
            await s.execute(
                select(AuditEventModel).where(
                    AuditEventModel.entity_id == task.id,
                    AuditEventModel.event_type == "task.stopped_by_actor",
                )
            )
        ).scalars().all()
    assert len(rows) == 1
    payload = json.loads(rows[0].payload_json)
    assert payload["actor_id"] == "alice"
    assert payload["via"] == "missions_api"


async def test_cancel_accepts_no_body_exactly_as_before(api) -> None:
    """Issue #36 is additive: a client that sends no body at all must still work."""
    task = await make_task(api.factory, "p1", state="running")
    detail = api.get(f"/api/v1/missions/{task.id}", headers=auth(ALICE_TOKEN))
    response = api.post(
        f"/api/v1/missions/{task.id}/cancel",
        headers={**auth(ALICE_TOKEN), "If-Match": detail.headers["ETag"]},
    )
    assert response.status_code == 200
    assert response.json()["state"] == TaskState.CANCELLED.value


async def test_cancel_records_an_operator_typed_reason(api) -> None:
    """Issue #36: the reason has somewhere to go, on the same audit event."""
    from sqlalchemy import select

    from gateway.app.models.entities import AuditEventModel

    task = await make_task(api.factory, "p1", state="running")
    detail = api.get(f"/api/v1/missions/{task.id}", headers=auth(ALICE_TOKEN))
    response = api.post(
        f"/api/v1/missions/{task.id}/cancel",
        headers={**auth(ALICE_TOKEN), "If-Match": detail.headers["ETag"]},
        json={"reason": "Duplicate of another running mission."},
    )
    assert response.status_code == 200

    async with api.factory() as s:
        rows = (
            await s.execute(
                select(AuditEventModel).where(
                    AuditEventModel.entity_id == task.id,
                    AuditEventModel.event_type == "task.stopped_by_actor",
                )
            )
        ).scalars().all()
    assert len(rows) == 1
    payload = json.loads(rows[0].payload_json)
    assert payload["reason"] == "Duplicate of another running mission."


async def test_cancel_with_no_reason_records_none(api) -> None:
    """No `reason` is sent — the field must not silently default to something else."""
    from sqlalchemy import select

    from gateway.app.models.entities import AuditEventModel

    task = await make_task(api.factory, "p1", state="running")
    detail = api.get(f"/api/v1/missions/{task.id}", headers=auth(ALICE_TOKEN))
    api.post(
        f"/api/v1/missions/{task.id}/cancel",
        headers={**auth(ALICE_TOKEN), "If-Match": detail.headers["ETag"]},
    )

    async with api.factory() as s:
        rows = (
            await s.execute(
                select(AuditEventModel).where(
                    AuditEventModel.entity_id == task.id,
                    AuditEventModel.event_type == "task.stopped_by_actor",
                )
            )
        ).scalars().all()
    assert json.loads(rows[0].payload_json)["reason"] is None


async def test_the_cancel_reason_appears_on_the_timeline(api) -> None:
    task = await make_task(api.factory, "p1", state="running")
    detail = api.get(f"/api/v1/missions/{task.id}", headers=auth(ALICE_TOKEN))
    api.post(
        f"/api/v1/missions/{task.id}/cancel",
        headers={**auth(ALICE_TOKEN), "If-Match": detail.headers["ETag"]},
        json={"reason": "Operator changed their mind."},
    )

    timeline = api.get(f"/api/v1/missions/{task.id}/timeline", headers=auth(ALICE_TOKEN)).json()
    entry = next(item for item in timeline["items"] if item["type"] == "task.stopped_by_actor")
    assert entry["summary"] == "Cancelled by an operator. Operator changed their mind."


async def test_a_reused_idempotency_key_with_a_different_reason_is_a_conflict(api) -> None:
    """Same shape as `routes/decisions.py`'s reason-in-fingerprint: a reused key
    with a different payload is a client bug, reported rather than silently
    dropping the second write's reason."""
    task = await make_task(api.factory, "p1", state="running")
    detail = api.get(f"/api/v1/missions/{task.id}", headers=auth(ALICE_TOKEN))
    headers = {**auth(ALICE_TOKEN), "If-Match": detail.headers["ETag"], "Idempotency-Key": "k-reason"}

    first = api.post(f"/api/v1/missions/{task.id}/cancel", headers=headers, json={"reason": "A"})
    second = api.post(f"/api/v1/missions/{task.id}/cancel", headers=headers, json={"reason": "B"})

    assert first.status_code == 200
    assert second.status_code == 409


async def test_cancel_releases_the_executor_slot(api) -> None:
    task = await make_task(api.factory, "p1", state="running")
    api.hub.running_tasks["E1"] = {task.id}
    detail = api.get(f"/api/v1/missions/{task.id}", headers=auth(ALICE_TOKEN))

    response = api.post(
        f"/api/v1/missions/{task.id}/cancel",
        headers={**auth(ALICE_TOKEN), "If-Match": detail.headers["ETag"]},
    )
    assert response.status_code == 200
    assert api.hub.running_tasks["E1"] == set()


# --------------------------------------------------------------------------
# Explain
# --------------------------------------------------------------------------


async def test_explain_reports_mission_control_fields_alongside_evidence(api) -> None:
    task = await make_task(api.factory, "p1", state="running")
    async with api.factory() as s:
        await store.append_log(s, task.id, 0, "stderr", "boom at /opt/codex-bridge/x.py")
        await store.update_task_state(s, task.id, TaskState.FAILED, error="exit code 1")

    body = api.post(f"/api/v1/missions/{task.id}/explain", headers=auth(ALICE_TOKEN)).json()
    assert body["missionId"] == task.id
    assert body["stage"] == "done"
    assert body["risk"] == "read"
    assert body["blocked"] is False
    assert body["reasons"]
    assert body["lastError"] == "exit code 1"
    assert "/opt/codex-bridge" not in json.dumps(body)


async def test_explain_on_a_blocked_mission_reports_it(api) -> None:
    task = await make_task(api.factory, "p1", instruction="run kubectl apply now", mode=TaskMode.IMPLEMENT)
    body = api.post(f"/api/v1/missions/{task.id}/explain", headers=auth(ALICE_TOKEN)).json()
    assert body["blocked"] is True
    assert body["blockedReason"]["code"] == "awaiting_approval"
    assert "The mission is held for approval" in " ".join(body["reasons"])


async def test_explain_of_an_invisible_mission_is_not_found(api) -> None:
    theirs = await make_task(api.factory, "p2")
    response = api.post(f"/api/v1/missions/{theirs.id}/explain", headers=auth(ALICE_TOKEN))
    assert response.status_code == 404


# --------------------------------------------------------------------------
# Create — issue #68
# --------------------------------------------------------------------------


async def test_a_token_without_the_submit_scope_cannot_create_a_mission(api) -> None:
    response = api.post(
        "/api/v1/missions",
        headers=auth(READER_TOKEN),
        json={"projectId": "p1", "objective": "analyze the repo"},
    )
    assert response.status_code == 403
    assert response.json()["code"] == "permission_denied"


async def test_creating_a_mission_and_reading_it_back(api) -> None:
    """Issue #68's Definition of Done, verbatim: create, then GET the same id."""
    response = api.post(
        "/api/v1/missions",
        headers=auth(ALICE_TOKEN),
        json={"projectId": "p1", "objective": "implement the thing", "mode": "implement", "timeoutSeconds": 60},
    )
    assert response.status_code == 201
    created = response.json()
    assert created["projectId"] == "p1"
    assert created["objective"] == "implement the thing"
    assert created["assignedAgent"] == "E1"
    assert created["engine"] == "codex"
    assert created["issueRef"] is None
    assert created["delivery"] is None
    assert "ETag" in response.headers

    fetched = api.get(f"/api/v1/missions/{created['id']}", headers=auth(ALICE_TOKEN)).json()
    assert fetched == created


async def test_create_does_not_reopen_the_identity_question(api) -> None:
    """F01 (issue #68's own ARO): no new id space, no new TaskState.

    The created row is readable through the exact same id `GET
    /api/v1/sessions/{id}` and `GET /api/v1/decisions/{id}` would use for the
    same `TaskModel` row — this test only asserts the mission side, since the
    row itself (not a parallel one) is the whole claim.
    """
    from shared.protocol import TaskState as _TaskState

    created = api.post(
        "/api/v1/missions",
        headers=auth(ALICE_TOKEN),
        json={"projectId": "p1", "objective": "analyze it", "mode": "analyze", "timeoutSeconds": 60},
    ).json()
    assert created["state"] in {s.value for s in _TaskState}

    async with api.factory() as s:
        task = await store.get_task(s, created["id"])
    assert task is not None
    assert task.project_id == "p1"


async def test_a_retried_create_replays_instead_of_creating_twice(api) -> None:
    headers = {**auth(ALICE_TOKEN), "Idempotency-Key": "create-1"}
    payload = {"projectId": "p1", "objective": "analyze it", "mode": "analyze", "timeoutSeconds": 60}

    first = api.post("/api/v1/missions", headers=headers, json=payload)
    second = api.post("/api/v1/missions", headers=headers, json=payload)

    assert first.status_code == 201
    assert second.status_code == 201
    assert second.headers.get("Idempotent-Replay") == "true"
    assert second.json() == first.json()

    async with api.factory() as s:
        from sqlalchemy import select

        from gateway.app.models.entities import TaskModel

        rows = (await s.execute(select(TaskModel).where(TaskModel.project_id == "p1"))).scalars().all()
    assert len(rows) == 1


async def test_create_resolves_an_executor_automatically_when_none_is_named(api) -> None:
    response = api.post(
        "/api/v1/missions",
        headers=auth(ALICE_TOKEN),
        json={"projectId": "p1", "objective": "analyze it", "mode": "analyze", "timeoutSeconds": 60},
    )
    assert response.status_code == 201
    assert response.json()["assignedAgent"] == "E1"


async def test_an_executor_not_onboarded_for_the_project_is_a_conflict(api) -> None:
    async with api.factory() as s:
        await store.upsert_registry(
            s,
            executors=[
                ExecutorRegistration(
                    executor_id="E1", display_name="E1", machine_token="t",
                    allowed_projects=["p1", "p2"], enabled=True,
                ),
                ExecutorRegistration(
                    executor_id="E2", display_name="E2", machine_token="t2",
                    allowed_projects=["p2"], enabled=True,
                ),
            ],
            projects=[
                ProjectRegistration(
                    project_id=pid, name=pid, path=f"/srv/{pid}",
                    allowed_modes=list(TaskMode), max_timeout_seconds=600,
                    sensitive_patterns=[], enabled=True,
                )
                for pid in ("p1", "p2")
            ],
        )
    response = api.post(
        "/api/v1/missions",
        headers=auth(ALICE_TOKEN),
        json={"projectId": "p1", "executorId": "E2", "objective": "analyze it", "mode": "analyze"},
    )
    assert response.status_code == 409
    assert response.json()["code"] == "conflict"


async def test_a_mission_in_an_invisible_project_cannot_be_created(api) -> None:
    response = api.post(
        "/api/v1/missions",
        headers=auth(ALICE_TOKEN),
        json={"projectId": "p2", "objective": "analyze it", "mode": "analyze"},
    )
    assert response.status_code == 404
    assert response.json()["code"] == "not_found"


async def test_engine_choice_is_accepted_and_returned(api) -> None:
    response = api.post(
        "/api/v1/missions",
        headers=auth(ALICE_TOKEN),
        json={"projectId": "p1", "objective": "analyze it", "mode": "analyze", "engine": "claude", "timeoutSeconds": 60},
    )
    assert response.status_code == 201
    assert response.json()["engine"] == "claude"


async def test_an_unimplemented_engine_is_refused(api) -> None:
    response = api.post(
        "/api/v1/missions",
        headers=auth(ALICE_TOKEN),
        json={"projectId": "p1", "objective": "analyze it", "mode": "analyze", "engine": "gemini"},
    )
    assert response.status_code == 400
    assert response.json()["code"] == "validation_failed"


async def test_a_local_issue_ref_is_stored_and_returned(api) -> None:
    async with api.factory() as s:
        issue = await store.create_issue(
            s, project_id="p1", epic_id=None, title="Fix the thing", description=None,
            status=None, priority=None, labels=None, assignee_user_id=None, assignee_email=None,
            dependencies=None, blocked_reason=None, actor_user_id="alice", actor_email="alice@example.com",
        )
    response = api.post(
        "/api/v1/missions",
        headers=auth(ALICE_TOKEN),
        json={
            "projectId": "p1", "objective": "resolve it", "mode": "implement",
            "issueRef": f"local:{issue.id}", "timeoutSeconds": 60,
        },
    )
    assert response.status_code == 201
    assert response.json()["issueRef"] == f"local:{issue.id}"


async def test_a_local_issue_ref_from_another_project_is_not_found(api) -> None:
    async with api.factory() as s:
        issue = await store.create_issue(
            s, project_id="p2", epic_id=None, title="Not yours", description=None,
            status=None, priority=None, labels=None, assignee_user_id=None, assignee_email=None,
            dependencies=None, blocked_reason=None, actor_user_id="alice", actor_email="alice@example.com",
        )
    response = api.post(
        "/api/v1/missions",
        headers=auth(ALICE_TOKEN),
        json={
            "projectId": "p1", "objective": "resolve it", "mode": "implement",
            "issueRef": f"local:{issue.id}",
        },
    )
    assert response.status_code == 404


async def test_a_github_issue_ref_is_not_supported_yet(api) -> None:
    response = api.post(
        "/api/v1/missions",
        headers=auth(ALICE_TOKEN),
        json={"projectId": "p1", "objective": "resolve it", "mode": "implement", "issueRef": "gh:42"},
    )
    assert response.status_code == 400
    assert response.json()["code"] == "validation_failed"


async def test_delivery_with_allow_push_requires_approval_authority(api) -> None:
    """No separate, weaker authorization path for the HTTP surface (issue #68).

    Alice carries `codexbridge.task.submit` but not `codexbridge.task.approve`
    and is not `can_approve_sensitive` — exactly the caller
    `start_development_task` (MCP) refuses for the identical request shape.
    """
    response = api.post(
        "/api/v1/missions",
        headers=auth(ALICE_TOKEN),
        json={
            "projectId": "p1", "objective": "ship it", "mode": "implement",
            "delivery": {"branch": "feature/x", "allowPush": True},
        },
    )
    assert response.status_code == 403
    assert response.json()["code"] == "permission_denied"


async def test_delivery_with_a_non_pushable_branch_is_refused(api) -> None:
    response = api.post(
        "/api/v1/missions",
        headers=auth(ADMIN_TOKEN),
        json={
            "projectId": "p1", "objective": "ship it", "mode": "implement",
            "delivery": {"branch": "main", "allowPush": True},
        },
    )
    assert response.status_code == 400
    assert response.json()["code"] == "validation_failed"


async def test_delivery_pre_authorization_flows_through_like_the_mcp_path(api) -> None:
    """The same `push_preauthorized_by_request` path `store.create_task`
    resolves for `submit_codex_task`/`start_development_task` (MCP) — a
    caller who may approve sensitive tasks gets an already-approved mission
    back, not one sitting in `awaiting_approval`.
    """
    response = api.post(
        "/api/v1/missions",
        headers=auth(ADMIN_TOKEN),
        json={
            "projectId": "p1", "objective": "ship it", "mode": "implement", "timeoutSeconds": 60,
            "delivery": {"branch": "feature/ship-it", "allowPush": True, "baseBranch": "development"},
        },
    )
    assert response.status_code == 201
    body = response.json()
    assert body["approvalState"] == "approved"
    assert body["state"] != "awaiting_approval"
    assert body["delivery"] == {
        "branch": "feature/ship-it",
        "allowPush": True,
        "baseBranch": "development",
        "remote": "origin",
        "commitSubject": None,
    }


async def test_a_delivery_without_allow_push_needs_no_approval_authority(api) -> None:
    """`allow_push` is the gate, not `delivery` on its own: a caller may still
    hand the executor a branch to work on without asking for a push."""
    response = api.post(
        "/api/v1/missions",
        headers=auth(ALICE_TOKEN),
        json={
            "projectId": "p1", "objective": "prep the branch", "mode": "implement", "timeoutSeconds": 60,
            "delivery": {"branch": "feature/prep", "allowPush": False},
        },
    )
    assert response.status_code == 201
    assert response.json()["delivery"]["allowPush"] is False


async def test_missions_list_reports_engine_and_issue_ref_too(api) -> None:
    """Issue #68: `_mission_dto` is shared, so the additive fields are not
    exclusive to the create response — `docs/api/README.md` says as much."""
    api.post(
        "/api/v1/missions",
        headers=auth(ALICE_TOKEN),
        json={"projectId": "p1", "objective": "analyze it", "mode": "analyze", "engine": "claude", "timeoutSeconds": 60},
    )
    body = api.get("/api/v1/missions", headers=auth(ALICE_TOKEN)).json()
    assert body["items"][0]["engine"] == "claude"
