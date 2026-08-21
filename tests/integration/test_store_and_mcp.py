from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from sqlalchemy import select

from gateway.app.core.users import AuthenticatedPrincipal
from gateway.app.db.base import Base
from gateway.app.mcp.server import handle_mcp_call
from gateway.app.models.entities import AuditEventModel
from gateway.app.services import store
from gateway.app.services.agent_hub import AgentHub
from shared.protocol import ApprovalDecision, ExecutorRegistration, ProjectRegistration, SubmitTaskRequest, TaskMode, TaskPriority, TaskState


class DummyHub:
    def __init__(self):
        self.connected: set[str] = set()
        self.sent: list[tuple[str, object]] = []
        self.finished: list[tuple[str, str]] = []

    def is_connected(self, executor_id: str) -> bool:
        return executor_id in self.connected

    async def dispatch_next(self, executor_id: str):
        return None

    async def send(self, executor_id: str, envelope):
        self.sent.append((executor_id, envelope))

    async def mark_task_finished(self, executor_id: str, task_id: str) -> None:
        self.finished.append((executor_id, task_id))


ADMIN = AuthenticatedPrincipal(
    user_id="admin",
    email="admin@example.com",
    roles=["admin"],
    allowed_projects=["p1", "p2"],
    scopes=[
        "codexbridge.read",
        "codexbridge.task.submit",
        "codexbridge.task.cancel",
        "codexbridge.task.approve",
        "codexbridge.admin",
    ],
    can_approve_sensitive=True,
)


USER_P1 = AuthenticatedPrincipal(
    user_id="alice",
    email="alice@example.com",
    allowed_projects=["p1"],
    scopes=[
        "codexbridge.read",
        "codexbridge.task.submit",
        "codexbridge.task.cancel",
    ],
)


USER_P2 = AuthenticatedPrincipal(
    user_id="bob",
    email="bob@example.com",
    allowed_projects=["p2"],
    scopes=[
        "codexbridge.read",
        "codexbridge.task.submit",
        "codexbridge.task.cancel",
    ],
)


@pytest.fixture
async def db_session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with session_factory() as session:
        await store.upsert_registry(
            session,
            executors=[
                ExecutorRegistration(
                    executor_id="T610",
                    display_name="T610",
                    machine_token="token-1",
                    allowed_projects=["p1"],
                    max_concurrent_tasks=1,
                )
            ],
            projects=[
                ProjectRegistration(
                    project_id="p1",
                    name="Projeto 1",
                    path="/srv/p1",
                    max_timeout_seconds=600,
                ),
                ProjectRegistration(
                    project_id="p2",
                    name="Projeto 2",
                    path="/srv/p2",
                    max_timeout_seconds=600,
                ),
            ],
        )
        yield session
    await engine.dispose()


def _submit(run_when_available: bool, project_id: str = "p1") -> SubmitTaskRequest:
    return SubmitTaskRequest(
        executor_id="T610",
        project_id=project_id,
        instruction="analisar o repositorio",
        mode=TaskMode.ANALYZE,
        timeout_seconds=300,
        priority=TaskPriority.NORMAL,
        run_when_available=run_when_available,
        expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
    )


@pytest.mark.asyncio
async def test_offline_task_rejected_without_queue(db_session: AsyncSession):
    with pytest.raises(ValueError, match="executor_offline"):
        await store.create_task(db_session, _submit(run_when_available=False), executor_online=False)


@pytest.mark.asyncio
async def test_offline_task_queued_when_allowed(db_session: AsyncSession):
    task = await store.create_task(db_session, _submit(run_when_available=True), executor_online=False)
    assert task.state == TaskState.WAITING_EXECUTOR.value


@pytest.mark.asyncio
async def test_project_allowlist_enforced(db_session: AsyncSession):
    with pytest.raises(ValueError, match="project_not_allowed_for_executor"):
        await store.create_task(db_session, _submit(run_when_available=True, project_id="p2"), executor_online=False)


@pytest.mark.asyncio
async def test_mcp_list_projects_filters_by_executor(db_session: AsyncSession):
    response = await handle_mcp_call(
        {"jsonrpc": "2.0", "id": "1", "method": "tools/call", "params": {"name": "list_projects", "arguments": {"executor_id": "T610"}}},
        db_session,
        DummyHub(),
        USER_P1,
    )
    projects = response["result"]["structuredContent"]["projects"]
    assert [project["project_id"] for project in projects] == ["p1"]


@pytest.mark.asyncio
async def test_mcp_submit_task_rejects_project_outside_user_scope(db_session: AsyncSession):
    with pytest.raises(Exception, match="project_access_denied"):
        await handle_mcp_call(
            {
                "jsonrpc": "2.0",
                "id": "1",
                "method": "tools/call",
                "params": {
                    "name": "submit_codex_task",
                    "arguments": _submit(run_when_available=True, project_id="p2").model_dump(mode="json"),
                },
            },
            db_session,
            DummyHub(),
            USER_P1,
        )


@pytest.mark.asyncio
async def test_task_logs_and_status_are_limited_to_task_owner(db_session: AsyncSession):
    hub = DummyHub()
    response = await handle_mcp_call(
        {
            "jsonrpc": "2.0",
            "id": "1",
            "method": "tools/call",
            "params": {
                "name": "submit_codex_task",
                "arguments": _submit(run_when_available=True).model_dump(mode="json"),
            },
        },
        db_session,
        hub,
        USER_P1,
    )
    task_id = response["result"]["structuredContent"]["task_id"]
    with pytest.raises(Exception, match="task_access_denied"):
        await handle_mcp_call(
            {
                "jsonrpc": "2.0",
                "id": "2",
                "method": "tools/call",
                "params": {"name": "get_task_status", "arguments": {"task_id": task_id}},
            },
            db_session,
            hub,
            USER_P2,
        )
    admin_view = await handle_mcp_call(
        {
            "jsonrpc": "2.0",
            "id": "3",
            "method": "tools/call",
            "params": {"name": "get_task_status", "arguments": {"task_id": task_id}},
        },
        db_session,
        hub,
        ADMIN,
    )
    assert admin_view["result"]["structuredContent"]["task_id"] == task_id


@pytest.mark.asyncio
async def test_approval_moves_task_back_to_queue(db_session: AsyncSession):
    task = await store.create_task(
        db_session,
        SubmitTaskRequest(
            executor_id="T610",
            project_id="p1",
            instruction="fazer deploy em production",
            mode=TaskMode.IMPLEMENT,
            timeout_seconds=300,
            priority=TaskPriority.NORMAL,
            run_when_available=True,
            expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
        ),
        executor_online=False,
    )
    assert task.state == TaskState.AWAITING_APPROVAL.value
    task = await store.decide_task_approval(db_session, task.id, ApprovalDecision.APPROVED, "manual approval")
    assert task.state == TaskState.WAITING_EXECUTOR.value


@pytest.mark.asyncio
async def test_mcp_cancel_of_a_disconnected_running_task_writes_cancelled(db_session: AsyncSession):
    """Issue #17's own context claims the HTTP `/stop` endpoint and the MCP
    `cancel_codex_task` tool "both send task.cancel only if the executor is
    currently connected" and otherwise still write the session cancelled so a
    later reconnect can replay it. That held for HTTP but not for MCP: a
    RUNNING task with its executor disconnected matched neither of
    cancel_codex_task's two branches — no state write, no cancel sent, and
    (state never becoming CANCELLED) nothing for
    store.list_tasks_requiring_cancel_replay to ever find. Found while
    verifying #17, fixed to mirror stop_session's unconditional write."""
    task = await store.create_task(db_session, _submit(run_when_available=True), executor_online=True)
    task = await store.update_task_state(db_session, task.id, TaskState.RUNNING)

    hub = DummyHub()  # T610 not in hub.connected — disconnected
    response = await handle_mcp_call(
        {
            "jsonrpc": "2.0",
            "id": "1",
            "method": "tools/call",
            "params": {"name": "cancel_codex_task", "arguments": {"task_id": task.id}},
        },
        db_session,
        hub,
        ADMIN,
    )

    reloaded = await store.get_task(db_session, task.id)
    assert reloaded.state == TaskState.CANCELLED.value
    assert response["result"]["structuredContent"]["state"] == TaskState.CANCELLED.value
    assert hub.sent == []  # nothing to send — the executor is not there to send it to
    assert hub.finished == [("T610", task.id)]  # concurrency slot released immediately, not left for an ack that will never come

    replay = await store.list_tasks_requiring_cancel_replay(db_session, "T610")
    assert [t.id for t in replay] == [task.id]


@pytest.mark.asyncio
async def test_mcp_cancel_of_a_connected_running_task_sends_and_writes_cancelled(db_session: AsyncSession):
    task = await store.create_task(db_session, _submit(run_when_available=True), executor_online=True)
    task = await store.update_task_state(db_session, task.id, TaskState.RUNNING)

    hub = DummyHub()
    hub.connected.add("T610")
    await handle_mcp_call(
        {
            "jsonrpc": "2.0",
            "id": "1",
            "method": "tools/call",
            "params": {"name": "cancel_codex_task", "arguments": {"task_id": task.id}},
        },
        db_session,
        hub,
        ADMIN,
    )

    reloaded = await store.get_task(db_session, task.id)
    assert reloaded.state == TaskState.CANCELLED.value
    assert len(hub.sent) == 1
    assert hub.sent[0][0] == "T610"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "pending_state",
    [TaskState.PAUSING, TaskState.PAUSED, TaskState.RESUMING, TaskState.RESTARTING],
)
async def test_mcp_cancel_of_a_pending_control_state_writes_cancelled(
    db_session: AsyncSession, pending_state: TaskState
):
    """Review of #17's own delivery: `cancel_codex_task` matched only RUNNING,
    so cancelling a PAUSED/PAUSING/RESUMING/RESTARTING session through MCP
    returned 200 with the session's *unchanged* state, sent no `task.cancel`,
    wrote nothing, and left nothing for
    store.list_tasks_requiring_cancel_replay to ever find on reconnect —
    exactly the failure #17 exists to close, reachable because #16 made these
    four states possible. The HTTP `/stop` endpoint already covered them
    (`STOPPABLE`, `gateway/app/api/routes/sessions.py`); the MCP tool now
    shares the same `shared.protocol.STOPPABLE_TASK_STATES` set."""
    task = await store.create_task(db_session, _submit(run_when_available=True), executor_online=True)
    task = await store.update_task_state(db_session, task.id, pending_state)

    hub = DummyHub()
    hub.connected.add("T610")
    response = await handle_mcp_call(
        {
            "jsonrpc": "2.0",
            "id": "1",
            "method": "tools/call",
            "params": {"name": "cancel_codex_task", "arguments": {"task_id": task.id}},
        },
        db_session,
        hub,
        ADMIN,
    )

    reloaded = await store.get_task(db_session, task.id)
    assert reloaded.state == TaskState.CANCELLED.value
    assert response["result"]["structuredContent"]["state"] == TaskState.CANCELLED.value
    assert len(hub.sent) == 1
    assert hub.sent[0][0] == "T610"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("initial_state", "connect_executor", "slot_was_held"),
    [
        (TaskState.RUNNING, True, True),
        # WAITING_EXECUTOR never held a concurrency slot (never dispatched),
        # so there is nothing for `mark_task_finished` to release.
        (TaskState.WAITING_EXECUTOR, False, False),
    ],
)
async def test_mcp_cancel_records_who_cancelled_it(
    db_session: AsyncSession, initial_state: TaskState, connect_executor: bool, slot_was_held: bool
):
    """issue #17 council round 1, "the second caller": HTTP `/stop` records
    `task.stopped_by_actor` (actor_id/actor_email/via) so "who cancelled this
    session" is answerable from the audit trail — half of #9's own
    acceptance criterion. `cancel_codex_task` wrote only the actor-less
    `task.state_changed`, so the audit answer to that question depended on
    which door was used to cancel a session."""
    task = await store.create_task(db_session, _submit(run_when_available=True), executor_online=True)
    if initial_state != TaskState.WAITING_EXECUTOR:
        task = await store.update_task_state(db_session, task.id, initial_state)

    hub = DummyHub()
    if connect_executor:
        hub.connected.add("T610")
    await handle_mcp_call(
        {
            "jsonrpc": "2.0",
            "id": "1",
            "method": "tools/call",
            "params": {"name": "cancel_codex_task", "arguments": {"task_id": task.id}},
        },
        db_session,
        hub,
        ADMIN,
    )

    events = (
        await db_session.execute(select(AuditEventModel).where(AuditEventModel.entity_id == task.id))
    ).scalars().all()
    actor_events = [e for e in events if e.event_type == "task.stopped_by_actor"]
    assert len(actor_events) == 1
    assert '"actor_id": "admin"' in actor_events[0].payload_json
    assert '"via": "mcp"' in actor_events[0].payload_json
    assert hub.finished == ([("T610", task.id)] if slot_was_held else [])


@pytest.mark.asyncio
async def test_startup_recovery_marks_running_as_lost(db_session: AsyncSession):
    task = await store.create_task(db_session, _submit(run_when_available=True), executor_online=True)
    task = await store.update_task_state(db_session, task.id, TaskState.RUNNING)
    recovered = await store.recover_tasks_after_startup(db_session)
    assert recovered["lost"] == 1
    reloaded = await store.get_task(db_session, task.id)
    assert reloaded.state == TaskState.LOST.value


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "pending_state",
    [TaskState.PAUSING, TaskState.PAUSED, TaskState.RESUMING, TaskState.RESTARTING],
)
async def test_startup_recovery_marks_pending_control_states_as_lost(
    db_session: AsyncSession, pending_state: TaskState
):
    """council 2026-08-18, round 2, "the second caller": issue #16 added these
    four states to the LOST-on-startup set alongside the pre-existing
    RUNNING, but nothing exercised it — reverting the branch back to
    `RUNNING`-only left the full 302-test suite green. `PAUSED` matters most
    of the four: `AgentHub.register`'s control replay only fires for
    PAUSING/RESUMING/RESTARTING (transitional states waiting on a `task.ack`),
    never for the stable PAUSED state, so a gateway restart is the only path
    that ever unsticks a task left PAUSED by a gateway that died."""
    task = await store.create_task(db_session, _submit(run_when_available=True), executor_online=True)
    task = await store.update_task_state(db_session, task.id, pending_state)
    recovered = await store.recover_tasks_after_startup(db_session)
    assert recovered["lost"] == 1
    reloaded = await store.get_task(db_session, task.id)
    assert reloaded.state == TaskState.LOST.value


# --------------------------------------------------------------------------
# approve_codex_task via MCP — issues #18/#19/#20
#
# `DummyHub` above is a stub (`dispatch_next` always returns `None`), which is
# exactly why it could not have caught #20's REST-side gap or proven this
# transport's own dispatch still works after `approve_codex_task` was
# refactored onto `AgentHub.dispatch_available`. These use a real `AgentHub`
# over its own database, same as `tests/integration/test_agent_ack_handling.py`.
# --------------------------------------------------------------------------


class _DummyWebSocket:
    def __init__(self) -> None:
        self.sent: list[dict] = []

    async def send_json(self, payload: dict) -> None:
        self.sent.append(payload)


@pytest.fixture
async def mcp_hub_factory():
    """A session factory over a fresh database, seeded like `db_session` but
    exposed as a factory rather than one open session — `AgentHub` needs to
    open sessions of its own."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with session_factory() as session:
        await store.upsert_registry(
            session,
            executors=[
                ExecutorRegistration(
                    executor_id="T610",
                    display_name="T610",
                    machine_token="token-1",
                    allowed_projects=["p1"],
                    max_concurrent_tasks=1,
                )
            ],
            projects=[
                ProjectRegistration(project_id="p1", name="Projeto 1", path="/srv/p1", max_timeout_seconds=600),
            ],
        )
    yield session_factory
    await engine.dispose()


async def _make_sensitive_task(factory):
    async with factory() as session:
        task = await store.create_task(
            session,
            SubmitTaskRequest(
                executor_id="T610",
                project_id="p1",
                instruction="fazer deploy em production",
                mode=TaskMode.IMPLEMENT,
                timeout_seconds=300,
                priority=TaskPriority.NORMAL,
                run_when_available=True,
                expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
            ),
            executor_online=False,
        )
    assert task.state == TaskState.AWAITING_APPROVAL.value
    return task


@pytest.mark.asyncio
async def test_mcp_approve_dispatches_to_a_connected_idle_executor(mcp_hub_factory):
    """Issue #20 asks this of the REST path specifically because the MCP
    transport already got it right; this pins that MCP's own behaviour
    survives the refactor onto the shared `AgentHub.dispatch_available`
    (`gateway/app/mcp/server.py`'s `approve_codex_task` no longer hand-rolls
    `is_connected` + `dispatch_next` + `send`)."""
    task = await _make_sensitive_task(mcp_hub_factory)

    hub = AgentHub(mcp_hub_factory)
    await hub.register("T610", _DummyWebSocket())

    async with mcp_hub_factory() as session:
        response = await handle_mcp_call(
            {
                "jsonrpc": "2.0",
                "id": "1",
                "method": "tools/call",
                "params": {
                    "name": "approve_codex_task",
                    "arguments": {"task_id": task.id, "decision": "approved"},
                },
            },
            session,
            hub,
            ADMIN,
        )
    assert response["result"]["structuredContent"]["approval_state"] == "approved"

    async with mcp_hub_factory() as session:
        reloaded = await store.get_task(session, task.id)
    # RUNNING, not just WAITING_EXECUTOR: `dispatch_next` moves a dispatched
    # task straight to RUNNING. Stuck at WAITING_EXECUTOR would mean the same
    # bug #18/#20 describe, just relocated to the transport this issue is not
    # about.
    assert reloaded.state == TaskState.RUNNING.value

    connection = hub.connections["T610"]
    sent_types = [msg["type"] for msg in connection.websocket.sent]
    assert "task.dispatch" in sent_types


@pytest.mark.asyncio
async def test_mcp_approve_records_the_deciding_actor(mcp_hub_factory):
    """Issue #19: only the generic `task.approval_decision` (written inside
    `store.decide_task_approval` itself, for every caller) used to land for
    an MCP approval — the actor-attributed `task.decision_resolved_by_actor`
    event the REST path's `_resolve()` records was missing here, so an audit
    reader could see *that* an MCP approval happened but never *who* did it.
    """
    task = await _make_sensitive_task(mcp_hub_factory)
    hub = AgentHub(mcp_hub_factory)  # T610 left offline; this test is about the audit trail, not dispatch

    async with mcp_hub_factory() as session:
        await handle_mcp_call(
            {
                "jsonrpc": "2.0",
                "id": "1",
                "method": "tools/call",
                "params": {
                    "name": "approve_codex_task",
                    "arguments": {"task_id": task.id, "decision": "approved", "reason": "looks safe"},
                },
            },
            session,
            hub,
            ADMIN,
        )

    async with mcp_hub_factory() as session:
        events = (
            await session.execute(select(AuditEventModel).where(AuditEventModel.entity_id == task.id))
        ).scalars().all()

    actor_events = [e for e in events if e.event_type == "task.decision_resolved_by_actor"]
    assert len(actor_events) == 1
    assert '"actor_id": "admin"' in actor_events[0].payload_json
    assert '"actor_email": "admin@example.com"' in actor_events[0].payload_json
    assert '"via": "mcp"' in actor_events[0].payload_json
    assert '"outcome": "approved"' in actor_events[0].payload_json

    # The generic event `decide_task_approval` itself records must still be
    # there too — this issue adds an event, it does not replace one.
    generic_events = [e for e in events if e.event_type == "task.approval_decision"]
    assert len(generic_events) == 1


@pytest.mark.asyncio
async def test_mcp_reject_and_request_revision_do_not_dispatch(mcp_hub_factory):
    task = await _make_sensitive_task(mcp_hub_factory)
    hub = AgentHub(mcp_hub_factory)
    await hub.register("T610", _DummyWebSocket())

    async with mcp_hub_factory() as session:
        await handle_mcp_call(
            {
                "jsonrpc": "2.0",
                "id": "1",
                "method": "tools/call",
                "params": {
                    "name": "approve_codex_task",
                    "arguments": {"task_id": task.id, "decision": "rejected", "reason": "not now"},
                },
            },
            session,
            hub,
            ADMIN,
        )

    async with mcp_hub_factory() as session:
        reloaded = await store.get_task(session, task.id)
    assert reloaded.state == TaskState.CANCELLED.value


# --------------------------------------------------------------------------
# continue_codex_session via MCP — issues #23/#24
#
# Zero coverage existed for this tool before (`pytest -k
# continue_codex_session` selected 0 tests). `_make_parent_task` creates its
# task in its own session and every test below reopens a *fresh* session from
# `mcp_hub_factory` for the actual `continue_codex_session` call — deliberately,
# so `store.get_task`'s `session.get()` cannot serve the parent row out of an
# identity-map cache and must round-trip it through SQLite, which is exactly
# what turns `expires_at` tzinfo-naive (issue #23) and is what a real second
# MCP call would do too.
# --------------------------------------------------------------------------


async def _make_parent_task(factory):
    """A finished task with a session to continue from.

    Left QUEUED (`executor_online=True`, its natural state on creation) it
    would still be the oldest QUEUED row for T610 by `created_at` —
    `next_dispatchable_task`'s own ordering — and `dispatch_next` would hand
    *it* back out instead of the continuation this fixture exists to set up
    for. Marking it COMPLETED, as a real finished session would be by the time
    anything continues it, takes it out of the QUEUED/WAITING_EXECUTOR pool
    `next_dispatchable_task` selects from.
    """
    async with factory() as session:
        task = await store.create_task(
            session,
            SubmitTaskRequest(
                executor_id="T610",
                project_id="p1",
                instruction="explore the repository",
                mode=TaskMode.ANALYZE,
                timeout_seconds=300,
                priority=TaskPriority.NORMAL,
                run_when_available=True,
                expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
            ),
            executor_online=True,
        )
        task = await store.update_task_state(session, task.id, TaskState.COMPLETED)
    return task


@pytest.mark.asyncio
async def test_mcp_continue_codex_session_succeeds_without_datetime_crash(mcp_hub_factory):
    """Issue #23: `continue_codex_session` forwards `parent.expires_at` —
    tzinfo-naive once it has round-tripped through SQLite, despite the column
    being `DateTime(timezone=True)` — into `store.create_task`'s
    `request.expires_at <= datetime.now(timezone.utc)` comparison, which used
    to raise `TypeError: can't compare offset-naive and offset-aware
    datetimes` before any dispatch logic ran. This is the plain success path:
    no executor connected, nothing to dispatch, just proving the call itself
    no longer raises.
    """
    parent = await _make_parent_task(mcp_hub_factory)
    hub = AgentHub(mcp_hub_factory)  # T610 left offline; this test is only about the crash

    async with mcp_hub_factory() as session:
        response = await handle_mcp_call(
            {
                "jsonrpc": "2.0",
                "id": "1",
                "method": "tools/call",
                "params": {
                    "name": "continue_codex_session",
                    "arguments": {
                        "task_id": parent.id,
                        "instruction": "now add tests",
                        "timeout_seconds": 300,
                    },
                },
            },
            session,
            hub,
            ADMIN,
        )

    structured = response["result"]["structuredContent"]
    assert structured["continued_from_task_id"] == parent.id
    assert structured["task_id"] != parent.id
    assert structured["state"] == TaskState.WAITING_EXECUTOR.value


@pytest.mark.asyncio
async def test_mcp_continue_codex_session_dispatches_to_a_connected_idle_executor(mcp_hub_factory):
    """Issue #24: unlike its sibling `submit_codex_task` (same file), this
    branch used to have no dispatch call at all — a continuation to a
    connected, idle executor landed QUEUED and waited for an unrelated event.
    Now routed through the shared `AgentHub.dispatch_available` (PR #21), same
    as the REST approve path and `approve_codex_task`.
    """
    parent = await _make_parent_task(mcp_hub_factory)
    hub = AgentHub(mcp_hub_factory)
    await hub.register("T610", _DummyWebSocket())

    async with mcp_hub_factory() as session:
        response = await handle_mcp_call(
            {
                "jsonrpc": "2.0",
                "id": "1",
                "method": "tools/call",
                "params": {
                    "name": "continue_codex_session",
                    "arguments": {
                        "task_id": parent.id,
                        "instruction": "now add tests",
                        "timeout_seconds": 300,
                    },
                },
            },
            session,
            hub,
            ADMIN,
        )

    structured = response["result"]["structuredContent"]
    # RUNNING, not just QUEUED: `dispatch_next` moves a dispatched task
    # straight to RUNNING, and the response reflects the post-dispatch row
    # (`session.refresh(task)` after `dispatch_available`), not the
    # pre-dispatch one.
    assert structured["state"] == TaskState.RUNNING.value

    async with mcp_hub_factory() as session:
        reloaded = await store.get_task(session, structured["task_id"])
    assert reloaded.state == TaskState.RUNNING.value

    connection = hub.connections["T610"]
    sent_types = [msg["type"] for msg in connection.websocket.sent]
    assert "task.dispatch" in sent_types


@pytest.mark.asyncio
async def test_mcp_continue_codex_session_leaves_task_queued_when_the_executor_is_offline(mcp_hub_factory):
    """No regression on the pre-existing (disconnected) case: an offline
    executor gets no dispatch attempt at all, matching #18/#20's own coverage
    of the REST approve path."""
    parent = await _make_parent_task(mcp_hub_factory)
    hub = AgentHub(mcp_hub_factory)  # nothing registered — T610 stays offline

    async with mcp_hub_factory() as session:
        response = await handle_mcp_call(
            {
                "jsonrpc": "2.0",
                "id": "1",
                "method": "tools/call",
                "params": {
                    "name": "continue_codex_session",
                    "arguments": {
                        "task_id": parent.id,
                        "instruction": "now add tests",
                        "timeout_seconds": 300,
                    },
                },
            },
            session,
            hub,
            ADMIN,
        )

    structured = response["result"]["structuredContent"]
    assert structured["state"] == TaskState.WAITING_EXECUTOR.value
    assert hub.connections == {}


@pytest.mark.asyncio
async def test_mcp_continue_codex_session_at_capacity_does_not_dispatch(mcp_hub_factory):
    """A connected executor already at its concurrency limit must not be sent
    a second `task.dispatch` — `dispatch_available`'s existing capacity gate
    (`AgentHub.dispatch_next`) must still apply through this call site,
    matching #18/#20's own at-capacity coverage of the REST approve path."""
    parent = await _make_parent_task(mcp_hub_factory)
    hub = AgentHub(mcp_hub_factory)
    await hub.register("T610", _DummyWebSocket())
    # T610's `max_concurrent_tasks` is 1 (mcp_hub_factory's registration) —
    # occupy that one slot with an unrelated task before continuing.
    hub.running_tasks["T610"] = {"some-other-task-already-running"}

    async with mcp_hub_factory() as session:
        response = await handle_mcp_call(
            {
                "jsonrpc": "2.0",
                "id": "1",
                "method": "tools/call",
                "params": {
                    "name": "continue_codex_session",
                    "arguments": {
                        "task_id": parent.id,
                        "instruction": "now add tests",
                        "timeout_seconds": 300,
                    },
                },
            },
            session,
            hub,
            ADMIN,
        )

    structured = response["result"]["structuredContent"]
    # The executor is connected, so `create_task` starts this continuation at
    # QUEUED (not WAITING_EXECUTOR — that state is only for an offline
    # executor). `dispatch_available`'s capacity gate must leave it there
    # rather than forcing a dispatch past the concurrency limit.
    assert structured["state"] == TaskState.QUEUED.value, "the fix must not bypass the concurrency gate"
    assert hub.connections["T610"].websocket.sent == []
    assert hub.connections["T610"].websocket.sent == []
