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

    def is_connected(self, executor_id: str) -> bool:
        return self.connected

    async def send(self, executor_id: str, envelope) -> None:
        self.sent.append((executor_id, envelope))

    async def mark_task_finished(self, executor_id: str, task_id: str) -> None:
        self.running_tasks.setdefault(executor_id, set()).discard(task_id)


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
                        "scopes": ["codexbridge.read", "codexbridge.task.cancel"],
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
            (ALICE_TOKEN, "alice", ["codexbridge.read", "codexbridge.task.cancel"]),
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
