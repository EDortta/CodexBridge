from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from gateway.app.api.routes import missions as missions_routes
from gateway.app.api.setup import install_api_conventions
from gateway.app.db.base import Base
from gateway.app.db.session import get_session
from gateway.app.models.entities import IssueModel, MissionIssueSnapshotModel
from gateway.app.services import store
from gateway.app.services.issue_resolution import build_issue_snapshot
from shared.protocol import ExecutorRegistration, ProjectRegistration, TaskMode, TaskState


ALICE_TOKEN = "token-alice"
READER_TOKEN = "token-reader"


class _Hub:
    def __init__(self) -> None:
        self.dispatch_available_calls: list[str] = []

    def is_connected(self, executor_id: str) -> bool:
        return True

    async def dispatch_available(self, executor_id: str) -> None:
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
                        "scopes": ["codexbridge.read", "codexbridge.task.submit"],
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
                ]
            }
        ),
        encoding="utf-8",
    )
    return str(path)


@pytest.fixture
async def api(users_file, monkeypatch):
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
                    executor_id="E1",
                    display_name="E1",
                    machine_token="t",
                    allowed_projects=["p1"],
                    enabled=True,
                )
            ],
            projects=[
                ProjectRegistration(
                    project_id="p1",
                    name="Project One",
                    path="/srv/p1",
                    allowed_modes=list(TaskMode),
                    max_timeout_seconds=3600,
                    sensitive_patterns=[],
                    enabled=True,
                )
            ],
        )
        future = datetime.now(timezone.utc) + timedelta(hours=1)
        await store.create_oauth_access_token(
            seed,
            token=ALICE_TOKEN,
            client_id="c",
            user_id="alice",
            scopes=["codexbridge.read", "codexbridge.task.submit"],
            expires_at=future,
        )
        await store.create_oauth_access_token(
            seed,
            token=READER_TOKEN,
            client_id="c",
            user_id="reader",
            scopes=["codexbridge.read"],
            expires_at=future,
        )
        await store.create_issue(
            seed,
            project_id="p1",
            epic_id=None,
            title="Fix sync",
            description="The sync button does not refresh state.",
            status=None,
            priority=None,
            labels=["bug", "mobile"],
            assignee_user_id=None,
            assignee_email=None,
            dependencies=[],
            blocked_reason=None,
            actor_user_id="alice",
            actor_email="alice@example.com",
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
    client.factory = factory  # type: ignore[attr-defined]
    client.hub = hub  # type: ignore[attr-defined]
    yield client
    await engine.dispose()


def auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


async def _issue_id(factory) -> str:
    async with factory() as session:
        result = await session.execute(select(IssueModel))
        return result.scalars().first().id


def _resolve(api, issue: str, **extra):
    payload = {"projectId": "p1", "issue": issue, **extra}
    return api.post("/api/v1/missions/resolve-issue", headers=auth(ALICE_TOKEN), json=payload)


@pytest.mark.asyncio
async def test_snapshot_hash_is_deterministic_and_ordered(api) -> None:
    async with api.factory() as session:
        issue = (await session.execute(select(IssueModel))).scalars().first()
        first = build_issue_snapshot(issue)
        issue.labels_json = json.dumps(["mobile", "bug"])
        second = build_issue_snapshot(issue)
    assert first.canonical_hash == second.canonical_hash
    assert first.canonical["comments"] == []


@pytest.mark.asyncio
async def test_resolve_issue_creates_traceable_mission_and_immutable_snapshot(api) -> None:
    issue_id = await _issue_id(api.factory)
    response = _resolve(api, f"local:{issue_id}")
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["sourceIssue"]["issueId"] == issue_id
    assert body["reused"] is False
    assert body["driftDetected"] is False
    assert "/srv/p1" not in response.text
    assert api.hub.dispatch_available_calls == ["E1"]

    async with api.factory() as session:
        snapshot = (
            await session.execute(
                select(MissionIssueSnapshotModel).where(MissionIssueSnapshotModel.mission_id == body["id"])
            )
        ).scalar_one()
        issue = await session.get(IssueModel, issue_id)
        await store.update_issue(
            session,
            issue_id,
            title="Changed after planning",
            actor_user_id="alice",
            actor_email="alice@example.com",
        )
        unchanged = await session.get(MissionIssueSnapshotModel, snapshot.id)
        assert unchanged.title == "Fix sync"
        assert issue.status == "open"


@pytest.mark.asyncio
async def test_equivalent_request_reuses_active_mission(api) -> None:
    issue_id = await _issue_id(api.factory)
    first = _resolve(api, issue_id).json()
    second = _resolve(api, issue_id).json()
    assert second["id"] == first["id"]
    assert second["reused"] is True


@pytest.mark.asyncio
async def test_force_new_creates_an_explicit_new_run(api) -> None:
    issue_id = await _issue_id(api.factory)
    first = _resolve(api, issue_id).json()
    second = _resolve(api, issue_id, forceNew=True).json()
    assert second["id"] != first["id"]
    assert second["reused"] is False


@pytest.mark.asyncio
async def test_issue_drift_holds_existing_mission_for_human(api) -> None:
    issue_id = await _issue_id(api.factory)
    first = _resolve(api, issue_id).json()
    async with api.factory() as session:
        await store.update_issue(
            session,
            issue_id,
            title="Materially changed",
            actor_user_id="alice",
            actor_email="alice@example.com",
        )

    drift = _resolve(api, issue_id).json()
    assert drift["id"] == first["id"]
    assert drift["reused"] is True
    assert drift["driftDetected"] is True
    assert drift["state"] == "waiting_human"
    assert drift["blockedReason"]["code"] == "issue_drift"

    timeline = api.get(f"/api/v1/missions/{first['id']}/timeline", headers=auth(ALICE_TOKEN)).json()
    assert "mission.issue_drift_detected" in [item["type"] for item in timeline["items"]]


@pytest.mark.asyncio
async def test_resolve_issue_requires_submit_scope_and_visible_project(api) -> None:
    issue_id = await _issue_id(api.factory)
    forbidden = api.post(
        "/api/v1/missions/resolve-issue",
        headers=auth(READER_TOKEN),
        json={"projectId": "p1", "issue": issue_id},
    )
    assert forbidden.status_code == 403

    hidden = api.post(
        "/api/v1/missions/resolve-issue",
        headers=auth(ALICE_TOKEN),
        json={"projectId": "p2", "issue": issue_id},
    )
    assert hidden.status_code == 404


@pytest.mark.asyncio
async def test_agent_success_does_not_close_source_issue(api) -> None:
    issue_id = await _issue_id(api.factory)
    body = _resolve(api, issue_id).json()
    async with api.factory() as session:
        await store.store_result(
            session,
            body["id"],
            {"task_id": body["id"], "final_state": "completed", "tests_ran": ["pytest focused"]},
            TaskState.COMPLETED,
        )
        issue = await session.get(IssueModel, issue_id)
        assert issue.status == "open"


@pytest.mark.asyncio
async def test_implement_mission_waits_for_completion_gate_when_validation_is_missing(api) -> None:
    issue_id = await _issue_id(api.factory)
    body = _resolve(api, issue_id).json()
    async with api.factory() as session:
        await store.update_task_state(session, body["id"], TaskState.RUNNING)
        await store.store_result(
            session,
            body["id"],
            {"task_id": body["id"], "final_state": "completed"},
            TaskState.COMPLETED,
        )

    detail = api.get(f"/api/v1/missions/{body['id']}", headers=auth(ALICE_TOKEN)).json()
    assert detail["state"] == "reviewing"
    assert "missing_validation:test" in detail["lastError"]


@pytest.mark.asyncio
async def test_validated_operator_review_mission_completes_and_exposes_evidence(api) -> None:
    issue_id = await _issue_id(api.factory)
    body = _resolve(api, issue_id).json()
    async with api.factory() as session:
        await store.update_task_state(session, body["id"], TaskState.RUNNING)
        await store.store_result(
            session,
            body["id"],
            {
                "task_id": body["id"],
                "final_state": "completed",
                "tests_ran": [{"name": "pytest focused", "passed": True}],
            },
            TaskState.COMPLETED,
        )

    detail = api.get(f"/api/v1/missions/{body['id']}", headers=auth(ALICE_TOKEN)).json()
    assert detail["state"] == "completed"
    async with api.factory() as session:
        events = await store.list_mission_events_page(
            session, body["id"], after=None, limit=100, include_attempt_events=True
        )
        completed = [event for event in events if event.event_type == "mission.attempt_completed"][-1]
        payload = json.loads(completed.payload_json)
    assert payload["completion_evidence"]["validated"] is True
    assert payload["completion_evidence"]["delivered"] is True
    assert payload["completion_gate"] == {"complete": True, "reasons": []}
