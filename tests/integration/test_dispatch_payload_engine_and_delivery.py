"""`AgentHub.dispatch_next` forwards engine/issue_ref/delivery to the executor.

WK-20260830-chatgpt-entry-provider-and-delivery. `engine` is always present
(the column default is "codex"), so an executor reading
`payload.get("engine", "codex")` behaves identically whether or not this
migration ever ran on the gateway it talks to -- an old-shaped dispatch (no
key at all) and a new-shaped one (`"engine": "codex"` explicit) both resolve
to the same runner.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from gateway.app.db.base import Base
from gateway.app.services import store
from gateway.app.services.agent_hub import AgentHub
from shared.protocol import (
    AgentEngine,
    DeliveryRequest,
    ExecutorRegistration,
    ProjectRegistration,
    SubmitTaskRequest,
    TaskMode,
    TaskPriority,
)


class DummyWebSocket:
    def __init__(self) -> None:
        self.sent: list[dict] = []

    async def send_json(self, payload: dict) -> None:
        self.sent.append(payload)


@pytest.fixture
async def factory():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with session_factory() as session:
        await store.upsert_registry(
            session,
            executors=[
                ExecutorRegistration(
                    executor_id="E1", display_name="E1", machine_token="t",
                    allowed_projects=["p1"], max_concurrent_tasks=5,
                )
            ],
            projects=[ProjectRegistration(project_id="p1", name="Projeto 1", path="/srv/p1", max_timeout_seconds=600)],
        )
    yield session_factory
    await engine.dispose()


@pytest.mark.asyncio
async def test_dispatch_omits_delivery_and_issue_ref_when_neither_was_requested(factory) -> None:
    async with factory() as session:
        await store.create_task(
            session,
            SubmitTaskRequest(
                executor_id="E1", project_id="p1", instruction="do the thing", mode=TaskMode.ANALYZE,
                priority=TaskPriority.NORMAL, timeout_seconds=60, run_when_available=True,
                expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
            ),
            executor_online=True,
        )

    hub = AgentHub(factory)
    await hub.register("E1", DummyWebSocket())
    payload = await hub.dispatch_next("E1")

    assert payload["engine"] == "codex"
    assert payload["issue_ref"] is None
    assert "delivery" not in payload


@pytest.mark.asyncio
async def test_dispatch_forwards_engine_issue_ref_and_delivery_when_requested(factory) -> None:
    async with factory() as session:
        await store.create_task(
            session,
            SubmitTaskRequest(
                executor_id="E1", project_id="p1", instruction="resolve the issue", mode=TaskMode.IMPLEMENT,
                priority=TaskPriority.NORMAL, timeout_seconds=60, run_when_available=True,
                expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
                engine=AgentEngine.CLAUDE, issue_ref="65",
                delivery=DeliveryRequest(branch="feature/uc-1", allow_push=False),
            ),
            executor_online=True,
            can_approve_push=True,
        )

    hub = AgentHub(factory)
    await hub.register("E1", DummyWebSocket())
    payload = await hub.dispatch_next("E1")

    assert payload["engine"] == "claude"
    assert payload["issue_ref"] == "65"
    assert payload["delivery"] == {
        "branch": "feature/uc-1", "allow_push": False, "base_branch": "development",
        "remote": "origin", "commit_subject": None,
    }
