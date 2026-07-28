from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from gateway.app.core.users import AuthenticatedPrincipal
from gateway.app.db.base import Base
from gateway.app.mcp.server import handle_mcp_call
from gateway.app.services import store
from shared.protocol import ApprovalDecision, ExecutorRegistration, ProjectRegistration, SubmitTaskRequest, TaskMode, TaskPriority, TaskState


class DummyHub:
    def __init__(self):
        self.connected: set[str] = set()

    def is_connected(self, executor_id: str) -> bool:
        return executor_id in self.connected

    async def dispatch_next(self, executor_id: str):
        return None

    async def send(self, executor_id: str, envelope):
        return None


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
async def test_startup_recovery_marks_running_as_lost(db_session: AsyncSession):
    task = await store.create_task(db_session, _submit(run_when_available=True), executor_online=True)
    task = await store.update_task_state(db_session, task.id, TaskState.RUNNING)
    recovered = await store.recover_tasks_after_startup(db_session)
    assert recovered["lost"] == 1
    reloaded = await store.get_task(db_session, task.id)
    assert reloaded.state == TaskState.LOST.value
