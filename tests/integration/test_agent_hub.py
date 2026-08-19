from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from gateway.app.db.base import Base
from gateway.app.models.entities import AuditEventModel
from gateway.app.services import store
from gateway.app.services.audit import record_event
from gateway.app.services.agent_hub import AgentHub
from shared.protocol import ExecutorRegistration, ProjectRegistration, SubmitTaskRequest, TaskMode, TaskPriority, TaskState


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
                    executor_id="E1",
                    display_name="Executor 1",
                    machine_token="secret",
                    allowed_projects=["p1"],
                    max_concurrent_tasks=1,
                )
            ],
            projects=[
                ProjectRegistration(
                    project_id="p1",
                    name="Projeto 1",
                    path="/srv/p1",
                    allowed_modes=[TaskMode.ANALYZE],
                    max_timeout_seconds=600,
                )
            ],
        )
    yield session_factory
    await engine.dispose()


async def _make_task(factory, *, instruction: str, state: TaskState) -> str:
    async with factory() as session:
        task = await store.create_task(
            session,
            SubmitTaskRequest(
                executor_id="E1",
                project_id="p1",
                instruction=instruction,
                mode=TaskMode.ANALYZE,
                priority=TaskPriority.NORMAL,
                timeout_seconds=60,
                run_when_available=True,
                expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
            ),
            executor_online=True,
        )
        task = await store.update_task_state(session, task.id, state)
        return task.id


@pytest.mark.asyncio
async def test_register_replays_pending_cancel_before_dispatch(factory) -> None:
    cancelled_id = await _make_task(factory, instruction="cancel me", state=TaskState.CANCELLED)
    await _make_task(factory, instruction="queued next", state=TaskState.WAITING_EXECUTOR)
    hub = AgentHub(factory)
    websocket = DummyWebSocket()

    await hub.register("E1", websocket)

    assert [payload["type"] for payload in websocket.sent] == ["task.cancel"]
    assert websocket.sent[0]["payload"] == {"task_id": cancelled_id}
    assert cancelled_id in hub.running_tasks["E1"]
    assert await hub.dispatch_next("E1") is None


@pytest.mark.asyncio
async def test_register_replays_a_pending_pause_that_never_got_an_ack(factory) -> None:
    """council 2026-08-18, "the sweep skeptic" / "the second caller": a task
    stuck in PAUSING because its executor disconnected before task.ack arrived
    used to be replayed nowhere — only CANCELLED had this path. This is the
    same test as `test_register_replays_pending_cancel_before_dispatch` for
    the three states `list_tasks_requiring_control_replay` covers."""
    pausing_id = await _make_task(factory, instruction="pause me", state=TaskState.PAUSING)
    hub = AgentHub(factory)
    websocket = DummyWebSocket()

    await hub.register("E1", websocket)

    assert [payload["type"] for payload in websocket.sent] == ["task.pause"]
    assert websocket.sent[0]["payload"] == {"task_id": pausing_id}
    assert pausing_id in hub.running_tasks["E1"]


@pytest.mark.asyncio
async def test_register_replays_pending_resume_and_restart_too(factory) -> None:
    resuming_id = await _make_task(factory, instruction="resume me", state=TaskState.RESUMING)
    restarting_id = await _make_task(factory, instruction="restart me", state=TaskState.RESTARTING)
    hub = AgentHub(factory)
    websocket = DummyWebSocket()

    await hub.register("E1", websocket)

    sent_by_task = {payload["payload"]["task_id"]: payload["type"] for payload in websocket.sent}
    assert sent_by_task[resuming_id] == "task.resume"
    assert sent_by_task[restarting_id] == "task.restart"


@pytest.mark.asyncio
async def test_acknowledged_cancel_is_not_replayed_and_allows_dispatch(factory) -> None:
    cancelled_id = await _make_task(factory, instruction="cancel me", state=TaskState.CANCELLED)
    queued_id = await _make_task(factory, instruction="queued next", state=TaskState.WAITING_EXECUTOR)
    async with factory() as session:
        await record_event(
            session,
            "task",
            cancelled_id,
            "task.cancel_acknowledged",
            {"executor_id": "E1"},
        )
        await session.commit()
    hub = AgentHub(factory)
    websocket = DummyWebSocket()

    await hub.register("E1", websocket)
    dispatch = await hub.dispatch_next("E1")

    assert websocket.sent == []
    assert dispatch is not None
    assert dispatch["task_id"] == queued_id


@pytest.mark.asyncio
async def test_cancel_replay_expires_after_max_age(factory) -> None:
    """A cancellation issued long ago is not chased on reconnect (issue #17):
    the executor that reappears a week later has almost certainly already
    finished the run, so replaying `task.cancel` past the configured window
    would just be stale noise, not a correctness fix."""
    cancelled_id = await _make_task(factory, instruction="cancel me", state=TaskState.CANCELLED)
    async with factory() as session:
        task = await session.get(store.TaskModel, cancelled_id)
        task.completed_at = datetime.now(timezone.utc) - timedelta(days=2)
        await session.commit()
    hub = AgentHub(factory, cancel_replay_max_age_seconds=86400)
    websocket = DummyWebSocket()

    await hub.register("E1", websocket)

    assert websocket.sent == []
    assert cancelled_id not in hub.running_tasks["E1"]


@pytest.mark.asyncio
async def test_cancel_replay_still_happens_within_max_age(factory) -> None:
    cancelled_id = await _make_task(factory, instruction="cancel me", state=TaskState.CANCELLED)
    async with factory() as session:
        task = await session.get(store.TaskModel, cancelled_id)
        task.completed_at = datetime.now(timezone.utc) - timedelta(hours=1)
        await session.commit()
    hub = AgentHub(factory, cancel_replay_max_age_seconds=86400)
    websocket = DummyWebSocket()

    await hub.register("E1", websocket)

    assert [payload["payload"]["task_id"] for payload in websocket.sent] == [cancelled_id]


@pytest.mark.asyncio
async def test_control_replay_expires_after_max_age(factory) -> None:
    """issue #17 council round 1, "the sweep skeptic": unlike cancel replay,
    `list_tasks_requiring_control_replay` had no age bound at all — a task
    stuck in PAUSING a year ago was replayed on every single reconnect,
    forever."""
    pausing_id = await _make_task(factory, instruction="pause me", state=TaskState.PAUSING)
    async with factory() as session:
        events = (
            await session.execute(select(AuditEventModel).where(AuditEventModel.entity_id == pausing_id))
        ).scalars().all()
        for event in events:
            event.created_at = datetime.now(timezone.utc) - timedelta(days=365)
        await session.commit()
    hub = AgentHub(factory, control_replay_max_age_seconds=86400)
    websocket = DummyWebSocket()

    await hub.register("E1", websocket)

    assert websocket.sent == []
    assert pausing_id not in hub.running_tasks["E1"]


@pytest.mark.asyncio
async def test_control_replay_still_happens_within_max_age(factory) -> None:
    pausing_id = await _make_task(factory, instruction="pause me", state=TaskState.PAUSING)
    hub = AgentHub(factory, control_replay_max_age_seconds=86400)
    websocket = DummyWebSocket()

    await hub.register("E1", websocket)

    assert [payload["payload"]["task_id"] for payload in websocket.sent] == [pausing_id]
