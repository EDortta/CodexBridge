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
async def test_stale_disconnect_does_not_unregister_reconnected_executor(factory) -> None:
    hub = AgentHub(factory)
    previous = DummyWebSocket()
    replacement = DummyWebSocket()
    await hub.register("E1", previous)
    await hub.register("E1", replacement)

    await hub.unregister("E1", previous)
    assert hub.is_connected("E1")
    assert hub.connections["E1"].websocket is replacement
    async with factory() as session:
        assert (await session.get(store.ExecutorModel, "E1")).connected is True

    await hub.unregister("E1", replacement)
    assert not hub.is_connected("E1")
    async with factory() as session:
        assert (await session.get(store.ExecutorModel, "E1")).connected is False


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


@pytest.mark.asyncio
async def test_reconnect_replays_only_running_file_task_and_preserves_slot(factory) -> None:
    """Only an outstanding deterministic TEST file task is redelivered."""
    running_file = await _make_task(
        factory, instruction='{"schemaVersion":1,"requestId":"reconnect-001"}',
        state=TaskState.RUNNING,
    )
    running_codex = await _make_task(
        factory, instruction="not safe to replay", state=TaskState.RUNNING
    )
    await _make_task(factory, instruction="already completed", state=TaskState.COMPLETED)
    async with factory() as session:
        file_task = await session.get(store.TaskModel, running_file)
        file_task.engine = "file"
        file_task.mode = "test"
        await session.commit()

    hub = AgentHub(factory)
    ws = DummyWebSocket()
    await hub.register("E1", ws)

    assert len(ws.sent) == 1
    dispatched = ws.sent[0]
    assert dispatched["type"] == "task.dispatch"
    assert dispatched["payload"]["task_id"] == running_file
    assert dispatched["payload"]["engine"] == "file"
    assert dispatched["payload"]["mode"] == "test"
    assert dispatched["payload"]["instruction"] == file_task.instruction
    assert running_file in hub.running_tasks["E1"]
    assert running_codex not in hub.running_tasks["E1"]
    assert await hub.dispatch_next("E1") is None


@pytest.mark.asyncio
async def test_reconnect_orphan_finishes_gateway_task_without_second_execution(
    factory, tmp_path
) -> None:
    """Gateway replay + real Agent handler + durable receipt + terminal DB state."""
    import json
    import subprocess
    import sys

    from agent.codex_bridge_agent.config import AgentSettings
    from agent.codex_bridge_agent.service import AgentService
    from shared.protocol import AgentEnvelope

    root = tmp_path / "repo"
    root.mkdir()
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    subprocess.run(["git", "-C", str(root), "checkout", "-q", "-b", "feature/test"],
                   check=True)
    marker = tmp_path / "must-not-execute"
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps({
        "project": "p1", "branch": "feature/test", "root": str(root),
        "profiles": {"verify": {"argv": [sys.executable, "-c",
            "from pathlib import Path; Path(" + repr(str(marker)) + ").touch()"],
            "timeout_seconds": 10}},
    }))
    config_path.chmod(0o600)
    inbox = tmp_path / "inbox"
    inbox.mkdir(mode=0o700)
    request = json.dumps({
        "schemaVersion": 1, "requestId": "orphan-001",
        "project": "p1", "branch": "feature/test", "profile": "verify",
    })
    (inbox / "orphan-001.running").write_text(request)
    task_id = await _make_task(factory, instruction=request, state=TaskState.RUNNING)
    async with factory() as session:
        task = await session.get(store.TaskModel, task_id)
        task.engine = "file"
        task.mode = "test"
        await session.commit()

    hub = AgentHub(factory)
    gateway_ws = DummyWebSocket()
    await hub.register("E1", gateway_ws)
    assert len(gateway_ws.sent) == 1
    assert gateway_ws.sent[0]["payload"]["task_id"] == task_id

    class AgentSocket:
        def __init__(self):
            self.sent = []
        async def send(self, message):
            self.sent.append(AgentEnvelope.model_validate_json(message))

    service = AgentService(AgentSettings(
        executor_id="E1",
        file_executor_config_file=str(config_path),
        file_executor_inbox=str(inbox),
    ))
    service.projects = {"p1": ProjectRegistration(
        project_id="p1", name="Project", path=str(root),
    )}
    agent_ws = AgentSocket()
    await service._handle_dispatch(
        agent_ws, AgentEnvelope.model_validate(gateway_ws.sent[0])
    )

    assert [item.type.value for item in agent_ws.sent] == [
        "task.ack", "task.result"
    ]
    result = agent_ws.sent[-1].payload
    assert result["task_id"] == task_id
    assert result["final_state"] == "failed"
    assert result["file_receipt"]["reason"] == "interrupted"
    assert not marker.exists()
    assert (inbox / "orphan-001[DONE].json").exists()

    async with factory() as session:
        updated = await store.store_result(
            session, task_id, result, TaskState.FAILED
        )
        assert updated.state == TaskState.FAILED.value
        assert json.loads(updated.result_json)["file_receipt"]["reason"] == "interrupted"
    await hub.mark_task_finished("E1", task_id)
    assert task_id not in hub.running_tasks["E1"]

    repeated = AgentSocket()
    await service._handle_dispatch(
        repeated, AgentEnvelope.model_validate(gateway_ws.sent[0])
    )
    assert repeated.sent[-1].payload["file_receipt"] == result["file_receipt"]
    assert not marker.exists()
