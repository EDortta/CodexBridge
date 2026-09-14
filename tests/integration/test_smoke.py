"""High-level smoke tests for CodexBridge's ChatGPT/MCP entry path.

These tests intentionally cover the operator-facing contract rather than every
unit-level branch: explicit Bridge Node routing, no silent spillover,
Node/Project authorization, safe result projection, and registered engines.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from gateway.app.core.users import AuthenticatedPrincipal
from gateway.app.db.base import Base
from gateway.app.mcp.server import handle_mcp_call
from gateway.app.models.entities import (
    ExecutorModel,
    NodeModel,
    ProjectAuthorizationModel,
    WorkspaceBindingModel,
)
from gateway.app.services import store
from shared.protocol import ExecutorRegistration, ProjectRegistration, TaskState


class DummyHub:
    def __init__(self) -> None:
        self.connected: set[str] = set()
        self.sent: list[tuple[str, object]] = []

    def is_connected(self, executor_id: str) -> bool:
        return executor_id in self.connected

    async def dispatch_next(self, executor_id: str):
        return None

    async def send(self, executor_id: str, envelope) -> None:
        self.sent.append((executor_id, envelope))


ADMIN = AuthenticatedPrincipal(
    user_id="admin",
    email="admin@example.com",
    roles=["admin"],
    allowed_projects=["p1", "wa-hub"],
    scopes=[
        "codexbridge.read",
        "codexbridge.task.submit",
        "codexbridge.task.cancel",
        "codexbridge.task.approve",
        "codexbridge.admin",
    ],
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
                    executor_id="T610",
                    display_name="T610 worker",
                    machine_token="t",
                    allowed_projects=["p1"],
                    max_concurrent_tasks=5,
                )
            ],
            projects=[
                ProjectRegistration(
                    project_id="p1",
                    name="Projeto Um",
                    path="/srv/p1",
                    max_timeout_seconds=3600,
                ),
                ProjectRegistration(
                    project_id="wa-hub",
                    name="WA-HUB",
                    path="/srv/wa-hub",
                    max_timeout_seconds=3600,
                ),
            ],
        )
        node = await session.get(NodeModel, "T610")
        assert node is not None
        node.display_name = "devel3"
        now = datetime.now(timezone.utc)
        session.add(
            WorkspaceBindingModel(
                id="binding-T610-p1",
                node_id="T610",
                project_id="p1",
                local_path="/srv/p1",
                state="active",
                created_at=now,
                updated_at=now,
            )
        )
        session.add(
            ProjectAuthorizationModel(
                id="authorization-T610-p1",
                node_id="T610",
                project_id="p1",
                capabilities_json='["read", "test", "modify"]',
                granted_by="operator:admin",
                granted_at=now,
            )
        )
        await session.commit()
        yield session
    await engine.dispose()


async def _mcp_tool_call(session: AsyncSession, hub: DummyHub, name: str, arguments: dict) -> dict:
    return await handle_mcp_call(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": name, "arguments": arguments},
        },
        session,
        hub,
        ADMIN,
    )


async def _start_task(session: AsyncSession, hub: DummyHub, arguments: dict) -> dict:
    response = await _mcp_tool_call(session, hub, "start_development_task", arguments)
    return response["result"]["structuredContent"]


@pytest.mark.asyncio
async def test_happy_path_targets_devel3_node_for_project_without_exposing_paths(db_session: AsyncSession):
    """The operator can name a Bridge Node and logical Project from MCP."""
    hub = DummyHub()
    hub.connected.add("T610")

    payload = await _start_task(
        db_session,
        hub,
        {
            "project": "p1",
            "node": "devel3",
            "request": "Verifique as issues locais que ainda não resolvemos no wa-hub",
            "mode": "analyze",
        },
    )

    assert payload["node_id"] == "T610"
    assert payload["executor_id"] == "T610"
    assert payload["project_id"] == "p1"
    assert payload["engine"] == "claude"
    assert payload["state"] == "queued"
    assert "mode" not in payload
    assert "/srv" not in str(payload)
    assert "/home" not in str(payload)
    for forbidden_field in ("command", "raw_events", "provider_run_ref", "pre_git", "post_git"):
        assert forbidden_field not in payload

    task = await store.get_task(db_session, payload["task_id"])
    assert task is not None
    assert task.executor_id == "T610"
    assert task.project_id == "p1"
    assert task.mode == "analyze"
    assert task.instruction == "Verifique as issues locais que ainda não resolvemos no wa-hub"


@pytest.mark.asyncio
async def test_explicit_node_project_request_requires_binding_and_authorization(db_session: AsyncSession):
    """A logical Project registered in the Gateway is not enough for a named Node."""
    executor = await db_session.get(ExecutorModel, "T610")
    assert executor is not None
    executor.metadata_json = '{"allowed_projects": ["p1", "wa-hub"]}'
    await db_session.execute(
        delete(WorkspaceBindingModel).where(WorkspaceBindingModel.id == "binding-T610-p1")
    )
    await db_session.commit()

    with pytest.raises(ValueError, match="workspace_binding_required:p1:T610"):
        await _start_task(
            db_session,
            DummyHub(),
            {
                "project": "p1",
                "node": "devel3",
                "request": "This should fail closed before task creation",
                "mode": "analyze",
            },
        )

    assert await store.list_recent_tasks(db_session, 10) == []


@pytest.mark.asyncio
async def test_explicit_node_routing_never_spills_to_another_online_node(db_session: AsyncSession):
    """If devel3 is named, another connected executor must not receive the task."""
    await store.upsert_registry(
        db_session,
        executors=[
            ExecutorRegistration(
                executor_id="E2",
                display_name="devel4 worker",
                machine_token="t2",
                allowed_projects=["p1"],
                max_concurrent_tasks=5,
            )
        ],
        projects=[],
    )
    other_node = await db_session.get(NodeModel, "E2")
    assert other_node is not None
    other_node.display_name = "devel4"
    await db_session.commit()

    hub = DummyHub()
    hub.connected.add("E2")

    payload = await _start_task(
        db_session,
        hub,
        {
            "project": "p1",
            "node": "devel3",
            "request": "Target only the explicitly named Node",
            "mode": "analyze",
        },
    )

    assert payload["node_id"] == "T610"
    assert payload["executor_id"] == "T610"
    assert payload["state"] == "waiting_executor"
    assert hub.sent == []


@pytest.mark.asyncio
async def test_mcp_task_result_projects_only_sanitized_public_fields(db_session: AsyncSession):
    """Persisted provider details can be rich; MCP receives only a safe projection."""
    payload = await _start_task(
        db_session,
        DummyHub(),
        {
            "project": "p1",
            "node": "devel3",
            "request": "Analyze safely",
            "mode": "analyze",
        },
    )
    await store.store_result(
        db_session,
        payload["task_id"],
        {
            "final_state": "completed",
            "return_code": 0,
            "last_message": "done password=secret123 at /home/user/private",
            "tests_ran": ["pytest /home/user/private/test.py"],
            "evidence": ["token=abc12345", "src/ok.py"],
            "command": ["agent", "--token", "secret123"],
            "raw_events": [{"secret": "secret123"}],
            "provider_run_ref": "session-secret",
            "pre_git": {"path": "/home/user/private"},
            "post_git": {"path": "/home/user/private"},
        },
        TaskState.COMPLETED,
    )

    result_response = await _mcp_tool_call(
        db_session,
        DummyHub(),
        "get_task_result",
        {"task_id": payload["task_id"]},
    )
    result_payload = result_response["result"]["structuredContent"]

    assert result_payload["task_id"] == payload["task_id"]
    assert result_payload["state"] == "completed"
    assert result_payload["final_state"] == "completed"
    assert result_payload["return_code"] == 0
    assert "last_message" in result_payload
    for forbidden_field in ("command", "raw_events", "provider_run_ref", "pre_git", "post_git"):
        assert forbidden_field not in result_payload
    serialized = str(result_payload)
    assert "secret123" not in serialized
    assert "/home/user/private" not in serialized
    assert "password=secret123" not in serialized
    assert "[REDACTED]" in serialized
    assert "[PATH]" in serialized


@pytest.mark.asyncio
async def test_engine_registry_accepts_implemented_engines_and_rejects_unknown(db_session: AsyncSession):
    """The MCP entrypoint validates engines through the extensible registry."""
    hub = DummyHub()
    hub.connected.add("T610")

    for engine in ("codex", "claude"):
        payload = await _start_task(
            db_session,
            hub,
            {
                "project": "p1",
                "node": "devel3",
                "request": f"Test with {engine} engine",
                "mode": "analyze",
                "engine": engine,
            },
        )
        assert payload["engine"] == engine

    with pytest.raises(Exception) as raised:
        await _start_task(
            db_session,
            hub,
            {
                "project": "p1",
                "node": "devel3",
                "request": "Test unsupported engine",
                "mode": "analyze",
                "engine": "unsupported-engine",
            },
        )
    assert "engine_not_implemented:unsupported-engine" in str(raised.value)
