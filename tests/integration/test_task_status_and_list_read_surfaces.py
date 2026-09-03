"""`get_task_status` / `list_recent_tasks` additive read-surface fields.

WK-20260903-gh67-70-read-gaps. Closes the two DoD gaps a delivery audit found
in already-merged issues #67 and #70:

- #67 Scope: `eta_seconds` / `eta_basis` / `eta_sample_size` were only ever
  returned by `start_development_task`'s response, never by the two other
  read surfaces named in the same Scope bullet.
- #70 Scope: `engine`, `issue_ref`, `delivery{branch, commit, pushed,
  outcome, reason}` and the `states` filter were code-complete but had zero
  test coverage anywhere in the repo.

Both tools are MCP tools (`gateway/app/mcp/tools.py`), not `/api/v1` HTTP
routes -- these tests go through `handle_mcp_call` the same way
`test_start_development_task.py` and `test_store_and_mcp.py` already do for
this transport, not through `TestClient` against a REST route (there is no
REST route for either tool, and none is being added here).
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from gateway.app.core.users import AuthenticatedPrincipal
from gateway.app.db.base import Base
from gateway.app.mcp.server import handle_mcp_call
from gateway.app.services import store
from shared.protocol import ExecutorRegistration, ProjectRegistration, SubmitTaskRequest, TaskMode, TaskPriority, TaskState


class DummyHub:
    def __init__(self):
        self.connected: set[str] = set()
        self.sent: list[tuple[str, object]] = []

    def is_connected(self, executor_id: str) -> bool:
        return executor_id in self.connected

    async def dispatch_next(self, executor_id: str):
        return None

    async def send(self, executor_id: str, envelope):
        self.sent.append((executor_id, envelope))


ADMIN = AuthenticatedPrincipal(
    user_id="admin",
    email="admin@example.com",
    roles=["admin"],
    allowed_projects=["p1"],
    scopes=["codexbridge.read", "codexbridge.task.submit", "codexbridge.task.approve", "codexbridge.admin"],
    can_approve_sensitive=True,
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
                    executor_id="T610", display_name="T610", machine_token="t",
                    allowed_projects=["p1"], max_concurrent_tasks=5,
                ),
                # A second, separately-capacity-limited executor -- only used
                # by the submit_codex_task queue_wait_seconds test below, so
                # saturating it (max_concurrent_tasks=1) never affects T610's
                # own tests.
                ExecutorRegistration(
                    executor_id="T900", display_name="T900", machine_token="t2",
                    allowed_projects=["p1"], max_concurrent_tasks=1,
                ),
            ],
            projects=[
                ProjectRegistration(project_id="p1", name="Projeto Um", path="/srv/p1", max_timeout_seconds=3600),
            ],
        )
        yield session
    await engine.dispose()


async def _create_task(
    session: AsyncSession, *, mode: TaskMode = TaskMode.IMPLEMENT, engine: str = "claude", issue_ref: str | None = None,
    executor_id: str = "T610",
):
    request = SubmitTaskRequest(
        executor_id=executor_id,
        project_id="p1",
        instruction="do the thing",
        mode=mode,
        timeout_seconds=3600,
        priority=TaskPriority.NORMAL,
        run_when_available=True,
        expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
        engine=engine,
        issue_ref=issue_ref,
    )
    return await store.create_task(session, request, executor_online=True)


async def _submit_codex_task(session, hub, arguments: dict) -> dict:
    response = await handle_mcp_call(
        {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": "submit_codex_task", "arguments": arguments}},
        session, hub, ADMIN,
    )
    return response["result"]["structuredContent"]


def _submit_arguments(
    *, executor_id: str = "T610", mode: str = "implement", engine: str = "claude", timeout_seconds: int = 3600
) -> dict:
    return {
        "executor_id": executor_id,
        "project_id": "p1",
        "instruction": "do the thing",
        "mode": mode,
        "timeout_seconds": timeout_seconds,
        "priority": "normal",
        "run_when_available": True,
        "expires_at": (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat(),
        "engine": engine,
    }


async def _seed_completed_history(
    session: AsyncSession, *, mode: TaskMode, engine: str, seconds_list, executor_id: str = "T610"
) -> None:
    for seconds in seconds_list:
        task = await _create_task(session, mode=mode, engine=engine, executor_id=executor_id)
        await store.update_task_state(session, task.id, TaskState.RUNNING)
        task = await session.get(type(task), task.id)
        anchor = datetime.now(timezone.utc)
        task.started_at = anchor - timedelta(seconds=seconds)
        task.completed_at = anchor
        task.state = TaskState.COMPLETED.value
        await session.commit()


async def _seed_running_task(
    session: AsyncSession, *, mode: TaskMode, engine: str, started_seconds_ago: float, executor_id: str = "T610"
):
    task = await _create_task(session, mode=mode, engine=engine, executor_id=executor_id)
    await store.update_task_state(session, task.id, TaskState.RUNNING)
    task = await session.get(type(task), task.id)
    task.started_at = datetime.now(timezone.utc) - timedelta(seconds=started_seconds_ago)
    await session.commit()
    return task


async def _get_task_status(session, hub, task_id: str) -> dict:
    response = await handle_mcp_call(
        {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": "get_task_status", "arguments": {"task_id": task_id}}},
        session, hub, ADMIN,
    )
    return response["result"]["structuredContent"]


async def _list_recent_tasks(session, hub, arguments: dict | None = None) -> dict:
    response = await handle_mcp_call(
        {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": "list_recent_tasks", "arguments": arguments or {}}},
        session, hub, ADMIN,
    )
    return response["result"]["structuredContent"]


# --------------------------------------------------------------------------
# Gap #2: eta_seconds / eta_basis / eta_sample_size on get_task_status
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_task_status_carries_eta_fields_with_no_history(db_session: AsyncSession):
    task = await _create_task(db_session)
    hub = DummyHub()
    payload = await _get_task_status(db_session, hub, task.id)
    assert payload["eta_seconds"] is None
    assert payload["eta_basis"] == "none"
    assert payload["eta_sample_size"] == 0


@pytest.mark.asyncio
async def test_get_task_status_eta_reflects_real_history(db_session: AsyncSession):
    await _seed_completed_history(db_session, mode=TaskMode.IMPLEMENT, engine="claude", seconds_list=(100, 200, 300, 400, 500))
    task = await _create_task(db_session)
    hub = DummyHub()
    payload = await _get_task_status(db_session, hub, task.id)
    assert payload["eta_basis"] == "project+mode+engine"
    assert payload["eta_seconds"] == 300
    assert payload["eta_sample_size"] == 5


@pytest.mark.asyncio
async def test_get_task_status_never_carries_queue_wait_seconds(db_session: AsyncSession):
    """`queue_wait_seconds` is about the wait BEFORE a task starts

    (`start_development_task`'s own concern); a task `get_task_status`
    already has a status for has already cleared that gate, so this surface
    intentionally never adds it -- see the comment at the call site in
    `gateway/app/mcp/server.py`.
    """
    task = await _create_task(db_session)
    hub = DummyHub()
    payload = await _get_task_status(db_session, hub, task.id)
    assert "queue_wait_seconds" not in payload


# --------------------------------------------------------------------------
# Gap #2: eta_seconds / eta_basis / eta_sample_size on list_recent_tasks
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_recent_tasks_carries_eta_fields_per_item(db_session: AsyncSession):
    await _seed_completed_history(db_session, mode=TaskMode.IMPLEMENT, engine="claude", seconds_list=(100, 200, 300, 400, 500))
    task = await _create_task(db_session)
    hub = DummyHub()
    payload = await _list_recent_tasks(db_session, hub)
    item = next(t for t in payload["tasks"] if t["task_id"] == task.id)
    assert item["eta_basis"] == "project+mode+engine"
    assert item["eta_seconds"] == 300
    assert item["eta_sample_size"] == 5


# --------------------------------------------------------------------------
# Gap #3: the `states` filter on list_recent_tasks (#70's own test plan,
# zero coverage before this change)
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_states_filter_narrows_to_the_requested_states(db_session: AsyncSession):
    queued = await _create_task(db_session)
    running = await _create_task(db_session)
    await store.update_task_state(db_session, running.id, TaskState.RUNNING)

    hub = DummyHub()
    payload = await _list_recent_tasks(db_session, hub, {"states": ["running"]})
    ids = {t["task_id"] for t in payload["tasks"]}
    assert ids == {running.id}
    assert queued.id not in ids


@pytest.mark.asyncio
async def test_states_filter_accepts_multiple_values(db_session: AsyncSession):
    """The exact motivating case named in #70's Objective: "what finished

    since I last asked" -- `states: ["completed", "failed"]`.
    """
    completed = await _create_task(db_session)
    await store.update_task_state(db_session, completed.id, TaskState.RUNNING)
    task_row = await db_session.get(type(completed), completed.id)
    task_row.state = TaskState.COMPLETED.value
    task_row.completed_at = datetime.now(timezone.utc)
    await db_session.commit()

    failed = await _create_task(db_session)
    await store.update_task_state(db_session, failed.id, TaskState.RUNNING)
    await store.update_task_state(db_session, failed.id, TaskState.FAILED, error="boom")

    still_queued = await _create_task(db_session)

    hub = DummyHub()
    payload = await _list_recent_tasks(db_session, hub, {"states": ["completed", "failed"]})
    ids = {t["task_id"] for t in payload["tasks"]}
    assert ids == {completed.id, failed.id}
    assert still_queued.id not in ids


@pytest.mark.asyncio
async def test_states_filter_absent_returns_every_state(db_session: AsyncSession):
    queued = await _create_task(db_session)
    running = await _create_task(db_session)
    await store.update_task_state(db_session, running.id, TaskState.RUNNING)

    hub = DummyHub()
    payload = await _list_recent_tasks(db_session, hub)
    ids = {t["task_id"] for t in payload["tasks"]}
    assert {queued.id, running.id} <= ids


@pytest.mark.asyncio
async def test_states_filter_matching_nothing_returns_an_empty_list(db_session: AsyncSession):
    await _create_task(db_session)
    hub = DummyHub()
    payload = await _list_recent_tasks(db_session, hub, {"states": ["cancelled"]})
    assert payload["tasks"] == []


# --------------------------------------------------------------------------
# Gap #4: engine / issue_ref / delivery{branch, commit, pushed, outcome,
# reason} -- including the null/absent case
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_task_status_delivery_result_is_none_when_no_delivery_happened(db_session: AsyncSession):
    """A task with no delivery must not fabricate a delivery object --

    Hard Rule from the delivery audit this issue closes.
    """
    task = await _create_task(db_session)
    hub = DummyHub()
    payload = await _get_task_status(db_session, hub, task.id)
    assert payload["delivery_result"] is None
    assert payload["issue_ref"] is None
    assert payload["engine"] == "claude"


@pytest.mark.asyncio
async def test_get_task_status_delivery_result_carries_the_full_outcome_shape(db_session: AsyncSession):
    task = await _create_task(db_session, issue_ref="local:abc123")
    task_row = await db_session.get(type(task), task.id)
    task_row.delivery_result_json = json.dumps(
        {"outcome": "pushed", "reason": None, "branch": "feature/x", "commit": "deadbeef", "pushed": True}
    )
    await db_session.commit()

    hub = DummyHub()
    payload = await _get_task_status(db_session, hub, task.id)
    assert payload["issue_ref"] == "local:abc123"
    assert payload["delivery_result"] == {
        "outcome": "pushed", "reason": None, "branch": "feature/x", "commit": "deadbeef", "pushed": True,
    }


@pytest.mark.asyncio
async def test_list_recent_tasks_delivery_is_none_when_no_delivery_happened(db_session: AsyncSession):
    task = await _create_task(db_session)
    hub = DummyHub()
    payload = await _list_recent_tasks(db_session, hub)
    item = next(t for t in payload["tasks"] if t["task_id"] == task.id)
    assert item["delivery"] is None
    assert item["issue_ref"] is None
    # The two pre-existing flattened fields must also read as None, exactly
    # as they did before this change -- not omitted, not a different shape.
    assert item["branch"] is None
    assert item["pushed"] is None


@pytest.mark.asyncio
async def test_list_recent_tasks_delivery_carries_the_full_outcome_shape(db_session: AsyncSession):
    task = await _create_task(db_session, issue_ref="local:xyz789")
    task_row = await db_session.get(type(task), task.id)
    task_row.delivery_result_json = json.dumps(
        {"outcome": "refused", "reason": "branch_not_pushable", "branch": "main", "commit": None, "pushed": False}
    )
    await db_session.commit()

    hub = DummyHub()
    payload = await _list_recent_tasks(db_session, hub)
    item = next(t for t in payload["tasks"] if t["task_id"] == task.id)
    assert item["issue_ref"] == "local:xyz789"
    assert item["delivery"] == {
        "outcome": "refused", "reason": "branch_not_pushable", "branch": "main", "commit": None, "pushed": False,
    }
    # Backward compatible: the pre-existing flattened fields still agree
    # with the richer `delivery` object, unchanged in shape or meaning.
    assert item["branch"] == "main"
    assert item["pushed"] is False


# --------------------------------------------------------------------------
# Hard Rule 1: additive only -- a client reading today's response keeps
# working unchanged.
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_task_status_keeps_every_pre_existing_field_unchanged(db_session: AsyncSession):
    task = await _create_task(db_session, issue_ref="local:keep-me")
    hub = DummyHub()
    payload = await _get_task_status(db_session, hub, task.id)
    pre_existing = {
        "task_id": task.id,
        "state": "queued",
        "executor_id": "T610",
        "project_id": "p1",
        "started_at": None,
        "completed_at": None,
        "last_error": None,
        "session_id": None,
        "engine": "claude",
        "issue_ref": "local:keep-me",
        "delivery": None,
        "delivery_result": None,
    }
    for key, value in pre_existing.items():
        assert payload[key] == value, key


@pytest.mark.asyncio
async def test_list_recent_tasks_keeps_every_pre_existing_field_unchanged(db_session: AsyncSession):
    task = await _create_task(db_session)
    hub = DummyHub()
    payload = await _list_recent_tasks(db_session, hub)
    item = next(t for t in payload["tasks"] if t["task_id"] == task.id)
    pre_existing = {
        "task_id": task.id,
        "executor_id": "T610",
        "project_id": "p1",
        "state": "queued",
        "approval_state": None,
        "engine": "claude",
        "branch": None,
        "pushed": None,
    }
    for key, value in pre_existing.items():
        assert item[key] == value, key


# --------------------------------------------------------------------------
# #67 Objective ("additively, submit_codex_task"): the same eta_seconds /
# eta_basis / eta_sample_size spread submit_codex_task's sibling submission
# tool (start_development_task) already carries.
#
# Reading taken: unlike get_task_status/list_recent_tasks -- poll surfaces
# for a task that has already cleared the dispatch gate, where executor_id
# is deliberately withheld -- submit_codex_task is a SUBMISSION surface,
# exactly like start_development_task. The Objective groups the two
# together ("Give start_development_task (and, additively,
# submit_codex_task) a duration estimate at submission time"), and
# submit_codex_task's own schema already requires the caller to name
# executor_id directly (no auto-resolution to second-guess), so there is no
# ambiguity about which executor's queue is in question. queue_wait_seconds
# is therefore wired through here, the same way it is for
# start_development_task.
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_submit_codex_task_carries_eta_fields_with_no_history(db_session: AsyncSession):
    hub = DummyHub()
    payload = await _submit_codex_task(db_session, hub, _submit_arguments())
    assert payload["eta_seconds"] is None
    assert payload["eta_basis"] == "none"
    assert payload["eta_sample_size"] == 0
    assert "queue_wait_seconds" not in payload


@pytest.mark.asyncio
async def test_submit_codex_task_eta_reflects_real_history(db_session: AsyncSession):
    await _seed_completed_history(db_session, mode=TaskMode.IMPLEMENT, engine="claude", seconds_list=(100, 200, 300, 400, 500))
    hub = DummyHub()
    payload = await _submit_codex_task(db_session, hub, _submit_arguments())
    assert payload["eta_basis"] == "project+mode+engine"
    assert payload["eta_seconds"] == 300
    assert payload["eta_sample_size"] == 5


@pytest.mark.asyncio
async def test_submit_codex_task_queue_wait_seconds_present_when_target_executor_saturated(db_session: AsyncSession):
    """T900's `max_concurrent_tasks` is 1 (fixture) -- unlike T610, so this

    test cannot be mistaken for exercising `get_task_status`/`list_recent_tasks`'s
    deliberately-different, executor_id-less behaviour.
    """
    await _seed_completed_history(
        db_session, mode=TaskMode.IMPLEMENT, engine="claude", seconds_list=(100, 200, 300, 400, 500), executor_id="T900"
    )
    # Median historical duration is 300s; this RUNNING task started 80s ago.
    await _seed_running_task(db_session, mode=TaskMode.IMPLEMENT, engine="claude", started_seconds_ago=80, executor_id="T900")

    hub = DummyHub()
    payload = await _submit_codex_task(db_session, hub, _submit_arguments(executor_id="T900"))
    assert "queue_wait_seconds" in payload
    assert 215 <= payload["queue_wait_seconds"] <= 225


@pytest.mark.asyncio
async def test_submit_codex_task_keeps_every_pre_existing_field_unchanged(db_session: AsyncSession):
    hub = DummyHub()
    payload = await _submit_codex_task(db_session, hub, _submit_arguments())
    task = await store.get_task(db_session, payload["task_id"])
    # DummyHub reports no connections, so this lands `waiting_executor` (the
    # pre-existing state a disconnected `run_when_available` task always got)
    # -- unrelated to the additive fields under test here.
    pre_existing = {
        "task_id": task.id,
        "state": "waiting_executor",
        "expires_at": task.expires_at.isoformat(),
    }
    for key, value in pre_existing.items():
        assert payload[key] == value, key
