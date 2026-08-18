"""`task.ack` handling in the `/agent/ws` message loop — issue #16 council.

An executor's `task.ack` used to be trusted on three counts nothing verified:
that it named a task the acking executor actually owns, that its `state` was
one of the enum's own values, and that a rejection (`accepted: false`) needed
any handling at all. All three are exercised here against
`gateway.app.main.handle_task_ack` directly — the function the `/agent/ws`
message loop calls for every `task.ack` — rather than through a live
websocket: an earlier version of this file drove it through
`TestClient.websocket_connect`, and every assertion passed vacuously because
nothing in that setup guaranteed the server had actually processed a sent
message before the test went on to read the database (`send_json` only
enqueues; there is no reply to wait on for `task.ack` or `heartbeat`, so nothing
synchronized the two sides). Calling the handler directly removes the need for
that synchronization entirely.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from gateway.app.db.base import Base
from gateway.app.main import handle_task_ack
from gateway.app.models.entities import AuditEventModel
from gateway.app.services import store
from shared.protocol import (
    AgentEnvelope,
    AgentMessageType,
    ExecutorRegistration,
    ProjectRegistration,
    SubmitTaskRequest,
    TaskMode,
    TaskPriority,
    TaskState,
)


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
                    executor_id="E1", display_name="E1", machine_token="s1",
                    allowed_projects=["p1"], max_concurrent_tasks=1,
                ),
                ExecutorRegistration(
                    executor_id="E2", display_name="E2", machine_token="s2",
                    allowed_projects=["p2"], max_concurrent_tasks=1,
                ),
            ],
            projects=[
                ProjectRegistration(project_id="p1", name="P1", path="/srv/p1", allowed_modes=[TaskMode.ANALYZE], max_timeout_seconds=600),
                ProjectRegistration(project_id="p2", name="P2", path="/srv/p2", allowed_modes=[TaskMode.ANALYZE], max_timeout_seconds=600),
            ],
        )
    yield session_factory
    await engine.dispose()


async def _make_task(factory, *, executor_id: str, project_id: str, state: TaskState) -> str:
    async with factory() as session:
        task = await store.create_task(
            session,
            SubmitTaskRequest(
                executor_id=executor_id, project_id=project_id, instruction="do it",
                mode=TaskMode.ANALYZE, priority=TaskPriority.NORMAL, timeout_seconds=60,
                expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
            ),
            executor_online=True,
        )
        task = await store.update_task_state(session, task.id, state)
        return task.id


def _ack_envelope(*, executor_id: str, task_id: str, control: str, accepted: bool, state: str | None) -> AgentEnvelope:
    return AgentEnvelope(
        message_id=f"{control}-{task_id}",
        executor_id=executor_id,
        sent_at=datetime.now(timezone.utc),
        type=AgentMessageType.TASK_ACK,
        payload={"task_id": task_id, "control": control, "accepted": accepted, "state": state},
    )


@pytest.mark.asyncio
async def test_an_executor_cannot_ack_a_task_it_does_not_own(factory) -> None:
    task_id = await _make_task(factory, executor_id="E1", project_id="p1", state=TaskState.PAUSING)

    async with factory() as session:
        await handle_task_ack(
            session,
            _ack_envelope(executor_id="E2", task_id=task_id, control="pause", accepted=True, state="paused"),
        )

    async with factory() as session:
        task = await store.get_task(session, task_id)
        events = (
            await session.execute(select(AuditEventModel).where(AuditEventModel.entity_id == task_id))
        ).scalars().all()

    assert task.state == TaskState.PAUSING.value  # untouched by E2's forged ack
    assert "task.ack_refused" in [e.event_type for e in events]


@pytest.mark.asyncio
async def test_an_ack_with_no_task_id_is_logged_not_raised(factory) -> None:
    """council 2026-08-18, round 2, "the adversarial user": the same class of
    bug round 1's invalid-`state` fix closed — an uncaught exception in
    handle_task_ack kills the /agent/ws loop before it ever reaches
    hub.unregister — had a sibling round 1 missed: `task_id` was still read
    with a direct subscript, one line above the guarded fields."""
    envelope = AgentEnvelope(
        message_id="no-task-id-1",
        executor_id="E1",
        sent_at=datetime.now(timezone.utc),
        type=AgentMessageType.TASK_ACK,
        payload={"control": "pause", "accepted": True, "state": "paused"},
    )

    async with factory() as session:
        # Would have raised an uncaught KeyError before this fix.
        await handle_task_ack(session, envelope)


@pytest.mark.asyncio
async def test_an_ack_with_an_unknown_state_is_refused_not_raised(factory) -> None:
    task_id = await _make_task(factory, executor_id="E1", project_id="p1", state=TaskState.PAUSING)

    async with factory() as session:
        # Would have raised an uncaught ValueError before this council's fix.
        await handle_task_ack(
            session,
            _ack_envelope(executor_id="E1", task_id=task_id, control="pause", accepted=True, state="not-a-real-state"),
        )

    async with factory() as session:
        task = await store.get_task(session, task_id)
        events = (
            await session.execute(select(AuditEventModel).where(AuditEventModel.entity_id == task_id))
        ).scalars().all()

    assert task.state == TaskState.PAUSING.value
    assert "task.ack_refused" in [e.event_type for e in events]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("pending", "control", "expected_state"),
    [
        (TaskState.PAUSING, "pause", TaskState.RUNNING),
        (TaskState.RESUMING, "resume", TaskState.PAUSED),
    ],
)
async def test_a_rejected_pause_or_resume_reverts_to_the_state_it_assumed(
    factory, pending, control, expected_state
) -> None:
    task_id = await _make_task(factory, executor_id="E1", project_id="p1", state=pending)

    async with factory() as session:
        await handle_task_ack(
            session,
            _ack_envelope(executor_id="E1", task_id=task_id, control=control, accepted=False, state=None),
        )

    async with factory() as session:
        task = await store.get_task(session, task_id)

    assert task.state == expected_state.value


@pytest.mark.asyncio
async def test_a_rejected_restart_is_reported_as_failed_not_left_pending(factory) -> None:
    task_id = await _make_task(factory, executor_id="E1", project_id="p1", state=TaskState.RESTARTING)

    async with factory() as session:
        await handle_task_ack(
            session,
            _ack_envelope(executor_id="E1", task_id=task_id, control="restart", accepted=False, state=None),
        )

    async with factory() as session:
        task = await store.get_task(session, task_id)

    assert task.state == TaskState.FAILED.value
    assert task.last_error


@pytest.mark.asyncio
async def test_an_accepted_ack_updates_state_and_is_recorded(factory) -> None:
    task_id = await _make_task(factory, executor_id="E1", project_id="p1", state=TaskState.PAUSING)

    async with factory() as session:
        await handle_task_ack(
            session,
            _ack_envelope(executor_id="E1", task_id=task_id, control="pause", accepted=True, state="paused"),
        )

    async with factory() as session:
        task = await store.get_task(session, task_id)
        events = (
            await session.execute(select(AuditEventModel).where(AuditEventModel.entity_id == task_id))
        ).scalars().all()

    assert task.state == TaskState.PAUSED.value
    assert "task.control_acknowledged" in [e.event_type for e in events]
