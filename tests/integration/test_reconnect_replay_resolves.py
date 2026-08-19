"""Issue #17 council round 1 — the headline scenario named by findings 1, 4
and 7: an executor with `max_concurrent_tasks=1` restarts (its `CodexRunner`
comes back empty), a task it was running gets cancelled while it is
disconnected, and it reconnects.

Before this round's fix, `AgentHub.register()` replayed `task.cancel` and put
the task id back into `hub.running_tasks`, but a fresh `CodexRunner` returning
`False` from `cancel()` meant the agent's old `if cancelled:` guard sent
nothing back — no `task.cancelled`, ever. `hub.mark_task_finished` is the only
thing that ever discards from `running_tasks`, and nothing ever called it, so
the executor's one concurrency slot stayed pinned for the life of the gateway
process: `dispatch_next` returned `None` forever even though a queued task was
waiting and the executor looked healthy and connected.

These tests wire the real production units together (`AgentHub`, the real
`AgentService`/`CodexRunner` pair, and the gateway's `handle_task_cancelled`)
through in-memory sockets, the same pattern already used by
`tests/unit/test_agent_service.py` and `tests/integration/test_sessions.py`.
Only the actual network transport is faked.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import gateway.app.main as main_module
from agent.codex_bridge_agent.codex_runner import CodexRunner
from agent.codex_bridge_agent.config import AgentSettings
from agent.codex_bridge_agent.service import AgentService
from gateway.app.db.base import Base
from gateway.app.main import handle_task_cancelled
from gateway.app.services import store
from gateway.app.services.agent_hub import AgentHub
from shared.protocol import (
    AgentEnvelope,
    ApprovalDecision,
    ExecutorRegistration,
    ProjectRegistration,
    SubmitTaskRequest,
    TaskMode,
    TaskPriority,
    TaskState,
)


class DummyGatewaySocket:
    def __init__(self) -> None:
        self.sent: list[dict] = []

    async def send_json(self, payload: dict) -> None:
        self.sent.append(payload)


class _FakeAgentSocket:
    def __init__(self, incoming: list[str]) -> None:
        self._incoming = list(incoming)
        self.sent: list[str] = []

    async def __aenter__(self) -> "_FakeAgentSocket":
        return self

    async def __aexit__(self, *_: object) -> bool:
        return False

    async def send(self, payload: str) -> None:
        self.sent.append(payload)

    def __aiter__(self) -> "_FakeAgentSocket":
        return self

    async def __anext__(self) -> str:
        if not self._incoming:
            raise StopAsyncIteration
        return self._incoming.pop(0)


class _FakeConnect:
    def __init__(self, socket: _FakeAgentSocket) -> None:
        self._socket = socket

    def __call__(self, url: str, **kwargs: object) -> "_FakeConnect":
        return self

    async def __aenter__(self) -> _FakeAgentSocket:
        return self._socket

    async def __aexit__(self, *_: object) -> bool:
        return False


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


async def _submit(factory, *, instruction: str) -> str:
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
        return task.id


async def _run_agent_over(hub: AgentHub, executor_id: str, sent_from_gateway: list[dict]) -> list[str]:
    """Feeds what `AgentHub.register` sent into a real `AgentService`
    running a real, empty `CodexRunner` (an executor that just restarted),
    and returns whatever the agent sent back."""
    service = AgentService(AgentSettings(executor_id=executor_id))
    service.runner = CodexRunner(AgentSettings())
    incoming = [
        AgentEnvelope.model_validate(envelope).model_dump_json() for envelope in sent_from_gateway
    ]
    socket = _FakeAgentSocket(incoming)

    import agent.codex_bridge_agent.service as service_module

    original_connect = service_module.websockets.connect
    service_module.websockets.connect = _FakeConnect(socket)
    try:
        await service._run_once()
    finally:
        service_module.websockets.connect = original_connect
    return socket.sent


@pytest.mark.asyncio
async def test_issue_17_headline_scenario_no_longer_stalls_the_queue(factory, monkeypatch) -> None:
    running_id = await _submit(factory, instruction="running when the host restarts")
    queued_id = await _submit(factory, instruction="queued behind it")

    async with factory() as session:
        # The task was dispatched before the executor host restarted: it
        # occupies the one concurrency slot, same as a real `dispatch_next`
        # would leave it.
        await store.update_task_state(session, running_id, TaskState.RUNNING)

    hub = AgentHub(factory, cancel_replay_max_age_seconds=86400)
    hub.running_tasks["E1"] = {running_id}
    monkeypatch.setattr(main_module, "hub", hub, raising=False)

    async with factory() as session:
        # The operator stops the session (HTTP /stop) while E1 is offline.
        await store.update_task_state(session, running_id, TaskState.CANCELLED)

    gateway_socket = DummyGatewaySocket()
    await hub.register("E1", gateway_socket)
    assert [p["type"] for p in gateway_socket.sent] == ["task.cancel"]
    assert running_id in hub.running_tasks["E1"]

    agent_replies = await _run_agent_over(hub, "E1", gateway_socket.sent)
    cancel_acks = [
        AgentEnvelope.model_validate_json(payload)
        for payload in agent_replies
        if AgentEnvelope.model_validate_json(payload).type.value == "task.cancelled"
    ]
    assert len(cancel_acks) == 1
    ack_envelope = cancel_acks[0]

    async with factory() as session:
        await handle_task_cancelled(session, ack_envelope)

    assert running_id not in hub.running_tasks["E1"]
    # `handle_task_cancelled` -> `hub.mark_task_finished` now dispatches the
    # next queued task itself (finding 10, council round 2): the slot is
    # already filled by the time this test asks, so a further
    # `dispatch_next` correctly finds nothing left to hand out.
    assert queued_id in hub.running_tasks["E1"]
    assert await hub.dispatch_next("E1") is None


@pytest.mark.asyncio
async def test_rejected_approval_of_a_never_dispatched_task_does_not_pin_the_slot(
    factory, monkeypatch
) -> None:
    """The second scenario in finding 1: a task that was never dispatched at
    all (still `waiting_executor`) gets rejected via approval, writing
    CANCELLED directly. `hub.running_tasks` never held this id from a real
    dispatch — only `AgentHub.register`'s replay ever added it — so this
    exercises the same pinning path from a colder start."""
    rejected_id = await _submit(factory, instruction="awaiting approval, then rejected")
    queued_id = await _submit(factory, instruction="queued behind it")

    async with factory() as session:
        await store.update_task_state(session, rejected_id, TaskState.AWAITING_APPROVAL)
        await store.decide_task_approval(session, rejected_id, ApprovalDecision.REJECTED)

    hub = AgentHub(factory, cancel_replay_max_age_seconds=86400)
    monkeypatch.setattr(main_module, "hub", hub, raising=False)

    gateway_socket = DummyGatewaySocket()
    await hub.register("E1", gateway_socket)
    assert [p["type"] for p in gateway_socket.sent] == ["task.cancel"]

    agent_replies = await _run_agent_over(hub, "E1", gateway_socket.sent)
    cancel_acks = [
        AgentEnvelope.model_validate_json(payload)
        for payload in agent_replies
        if AgentEnvelope.model_validate_json(payload).type.value == "task.cancelled"
    ]
    assert len(cancel_acks) == 1
    ack_envelope = cancel_acks[0]

    async with factory() as session:
        await handle_task_cancelled(session, ack_envelope)

    assert rejected_id not in hub.running_tasks["E1"]
    # Same as the headline test above: mark_task_finished dispatches on its
    # own now, so the slot is already filled here.
    assert queued_id in hub.running_tasks["E1"]
    assert await hub.dispatch_next("E1") is None


@pytest.mark.asyncio
async def test_cancel_ack_immediately_dispatches_the_next_queued_task(factory, monkeypatch) -> None:
    """finding 10 (council round 2 on #17, "the sweep skeptic"): the two tests
    above call `hub.dispatch_next` themselves after `handle_task_cancelled` —
    the one call production never makes at that moment. `handle_task_cancelled`
    only freed the slot; nothing re-dispatched, so a connected, idle executor
    sat on queued work until an unrelated event nudged the queue. This asserts
    only the call production actually makes on the `task.cancelled` path.
    """
    running_id = await _submit(factory, instruction="running when the host restarts")
    queued_id = await _submit(factory, instruction="queued behind it")

    async with factory() as session:
        await store.update_task_state(session, running_id, TaskState.RUNNING)

    hub = AgentHub(factory, cancel_replay_max_age_seconds=86400)
    hub.running_tasks["E1"] = {running_id}
    monkeypatch.setattr(main_module, "hub", hub, raising=False)

    async with factory() as session:
        await store.update_task_state(session, running_id, TaskState.CANCELLED)

    gateway_socket = DummyGatewaySocket()
    await hub.register("E1", gateway_socket)

    agent_replies = await _run_agent_over(hub, "E1", gateway_socket.sent)
    cancel_acks = [
        AgentEnvelope.model_validate_json(payload)
        for payload in agent_replies
        if AgentEnvelope.model_validate_json(payload).type.value == "task.cancelled"
    ]
    ack_envelope = cancel_acks[0]

    async with factory() as session:
        await handle_task_cancelled(session, ack_envelope)  # the only call production makes

    assert running_id not in hub.running_tasks["E1"]
    assert queued_id in hub.running_tasks["E1"]  # dispatched automatically, not by this test
    dispatch_messages = [payload for payload in gateway_socket.sent if payload["type"] == "task.dispatch"]
    assert len(dispatch_messages) == 1
    assert dispatch_messages[0]["payload"]["task_id"] == queued_id
