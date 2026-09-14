"""The `start_development_task` MCP tool -- the conversational entry point.

WK-20260830-chatgpt-entry-provider-and-delivery, issue #65. "resolve issue X
of project Y" resolved to a real `SubmitTaskRequest` without the caller
inventing an `executor_id` or an RFC-3339 `expires_at`.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from gateway.app.core.users import AuthenticatedPrincipal
from gateway.app.db.base import Base
from gateway.app.mcp.server import handle_mcp_call
from gateway.app.mcp.tools import tool_definitions
from gateway.app.models.entities import (
    NodeModel,
    ProjectAuthorizationModel,
    WorkspaceBindingModel,
)
from gateway.app.services import store
from shared.protocol import ExecutorRegistration, ProjectRegistration


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
    allowed_projects=["p1", "p2", "unclaimed"],
    scopes=["codexbridge.read", "codexbridge.task.submit", "codexbridge.task.approve", "codexbridge.admin"],
    can_approve_sensitive=True,
)

SUBMIT_ONLY = AuthenticatedPrincipal(
    user_id="alice",
    email="alice@example.com",
    allowed_projects=["p1", "p2", "unclaimed"],
    scopes=["codexbridge.read", "codexbridge.task.submit"],
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
                    executor_id="T610", display_name="T610 worker", machine_token="t",
                    allowed_projects=["p1"], max_concurrent_tasks=5,
                )
            ],
            projects=[
                ProjectRegistration(project_id="p1", name="Projeto Um", path="/srv/p1", max_timeout_seconds=3600),
                ProjectRegistration(project_id="p2", name="Projeto Um Bis", path="/srv/p2", max_timeout_seconds=3600),
                # Registered in the gateway but no executor allows it -- the
                # exact "project_not_onboarded" shape (docs/project-onboarding.md).
                ProjectRegistration(project_id="unclaimed", name="Unclaimed Project", path="/srv/unclaimed", max_timeout_seconds=3600),
            ],
        )
        # The operator names the machine (Bridge Node), not the protocol
        # connection (executor). They are 1:1 in this fixture but deliberately
        # carry different human names so the test cannot pass by resolving the
        # executor display name accidentally.
        node = await session.get(NodeModel, "T610")
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


async def _call(session, hub, principal, arguments: dict) -> dict:
    return await handle_mcp_call(
        {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": "start_development_task", "arguments": arguments}},
        session, hub, principal,
    )


def test_tool_schema_exposes_the_operator_facing_node_selector() -> None:
    tool = next(item for item in tool_definitions() if item["name"] == "start_development_task")

    node = tool["inputSchema"]["properties"]["node"]
    assert node["type"] == "string"
    assert "devel3" in node["description"]
    assert "node" in tool["description"].lower()
    assert "mode='analyze'" in tool["description"]

    list_issues = next(item for item in tool_definitions() if item["name"] == "list_issues")
    assert "banco deste gateway" in list_issues["description"]
    assert "Nao inspeciona arquivos" in list_issues["description"]


@pytest.mark.asyncio
async def test_happy_path_resolves_project_and_returns_eta_fields(db_session: AsyncSession):
    hub = DummyHub()
    hub.connected.add("T610")
    response = await _call(db_session, hub, ADMIN, {"project": "p1", "request": "implementar X"})
    payload = response["result"]["structuredContent"]

    assert payload["engine"] == "claude"
    assert payload["project_id"] == "p1"
    assert payload["executor_id"] == "T610"
    assert payload["state"] == "queued"
    assert payload["eta_seconds"] is None
    assert payload["eta_basis"] == "none"
    assert payload["eta_sample_size"] == 0
    task = await store.get_task(db_session, payload["task_id"])
    assert task.state == "queued"


@pytest.mark.asyncio
async def test_operator_can_target_a_bridge_node_by_its_human_name(db_session: AsyncSession):
    hub = DummyHub()
    hub.connected.add("T610")

    response = await _call(
        db_session,
        hub,
        ADMIN,
        {
            "project": "p1",
            "node": "DEVEL3",
            "request": "Liste as issues locais que ainda nao resolvemos.",
            "mode": "analyze",
        },
    )
    payload = response["result"]["structuredContent"]

    assert payload["node_id"] == "T610"
    assert payload["executor_id"] == "T610"
    task = await store.get_task(db_session, payload["task_id"])
    assert task.mode == "analyze"
    assert task.instruction == "Liste as issues locais que ainda nao resolvemos."


@pytest.mark.asyncio
async def test_named_node_requires_an_active_workspace_binding(db_session: AsyncSession):
    await db_session.execute(
        delete(WorkspaceBindingModel).where(
            WorkspaceBindingModel.node_id == "T610",
            WorkspaceBindingModel.project_id == "p1",
        )
    )
    await db_session.commit()

    with pytest.raises(ValueError, match="workspace_binding_required:p1:T610"):
        await _call(
            db_session,
            DummyHub(),
            ADMIN,
            {"project": "p1", "node": "devel3", "request": "read", "mode": "analyze"},
        )
    assert await store.list_recent_tasks(db_session, 10) == []


@pytest.mark.asyncio
async def test_named_node_rejects_an_inactive_workspace_binding(db_session: AsyncSession):
    binding = await db_session.get(WorkspaceBindingModel, "binding-T610-p1")
    binding.state = "stale"
    await db_session.commit()

    with pytest.raises(ValueError, match="workspace_binding_inactive:p1:T610:stale"):
        await _call(
            db_session,
            DummyHub(),
            ADMIN,
            {"project": "p1", "node": "devel3", "request": "read", "mode": "analyze"},
        )
    assert await store.list_recent_tasks(db_session, 10) == []


@pytest.mark.asyncio
async def test_named_node_requires_an_active_project_authorization(db_session: AsyncSession):
    await db_session.execute(
        delete(ProjectAuthorizationModel).where(
            ProjectAuthorizationModel.node_id == "T610",
            ProjectAuthorizationModel.project_id == "p1",
        )
    )
    await db_session.commit()

    with pytest.raises(ValueError, match="project_authorization_required:p1:T610"):
        await _call(
            db_session,
            DummyHub(),
            ADMIN,
            {"project": "p1", "node": "devel3", "request": "read", "mode": "analyze"},
        )
    assert await store.list_recent_tasks(db_session, 10) == []


@pytest.mark.asyncio
async def test_named_node_rejects_a_revoked_project_authorization(db_session: AsyncSession):
    authorization = await db_session.get(ProjectAuthorizationModel, "authorization-T610-p1")
    authorization.revoked_at = datetime.now(timezone.utc)
    await db_session.commit()

    with pytest.raises(ValueError, match="project_authorization_revoked:p1:T610"):
        await _call(
            db_session,
            DummyHub(),
            ADMIN,
            {"project": "p1", "node": "devel3", "request": "read", "mode": "analyze"},
        )
    assert await store.list_recent_tasks(db_session, 10) == []


@pytest.mark.asyncio
async def test_named_node_requires_the_capability_for_the_requested_mode(db_session: AsyncSession):
    authorization = await db_session.get(ProjectAuthorizationModel, "authorization-T610-p1")
    authorization.capabilities_json = '["read"]'
    await db_session.commit()

    with pytest.raises(ValueError, match="capability_not_authorized_for_mode:p1:T610:implement"):
        await _call(
            db_session,
            DummyHub(),
            ADMIN,
            {"project": "p1", "node": "devel3", "request": "write", "mode": "implement"},
        )
    assert await store.list_recent_tasks(db_session, 10) == []


@pytest.mark.asyncio
async def test_legacy_submission_without_node_keeps_pre_binding_behavior(db_session: AsyncSession):
    await db_session.execute(
        delete(ProjectAuthorizationModel).where(
            ProjectAuthorizationModel.node_id == "T610",
            ProjectAuthorizationModel.project_id == "p1",
        )
    )
    await db_session.execute(
        delete(WorkspaceBindingModel).where(
            WorkspaceBindingModel.node_id == "T610",
            WorkspaceBindingModel.project_id == "p1",
        )
    )
    await db_session.commit()

    response = await _call(
        db_session,
        DummyHub(),
        ADMIN,
        {"project": "p1", "request": "legacy write", "mode": "implement"},
    )
    assert response["result"]["structuredContent"]["state"] == "waiting_executor"


@pytest.mark.asyncio
async def test_named_node_never_spills_to_another_online_node(db_session: AsyncSession):
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
    other_node.display_name = "devel4"
    await db_session.commit()
    hub = DummyHub()
    hub.connected.add("E2")

    response = await _call(
        db_session,
        hub,
        ADMIN,
        {"project": "p1", "node": "devel3", "request": "read only", "mode": "analyze"},
    )
    payload = response["result"]["structuredContent"]

    assert payload["node_id"] == "T610"
    assert payload["executor_id"] == "T610"
    assert payload["state"] == "waiting_executor"


@pytest.mark.asyncio
async def test_node_and_legacy_executor_selectors_cannot_be_combined(db_session: AsyncSession):
    hub = DummyHub()

    with pytest.raises(Exception) as raised:
        await _call(
            db_session,
            hub,
            ADMIN,
            {"project": "p1", "node": "devel3", "executor_id": "T610", "request": "x"},
        )

    assert "executor_selector_conflict" in str(raised.value)


@pytest.mark.asyncio
async def test_unknown_node_reference_is_404(db_session: AsyncSession):
    hub = DummyHub()

    with pytest.raises(Exception) as raised:
        await _call(
            db_session,
            hub,
            ADMIN,
            {"project": "p1", "node": "no-such-node", "request": "x"},
        )

    assert "unknown_node" in str(raised.value)


@pytest.mark.asyncio
async def test_named_node_must_have_an_executor_onboarded_for_the_project(db_session: AsyncSession):
    hub = DummyHub()

    with pytest.raises(Exception) as raised:
        await _call(
            db_session,
            hub,
            ADMIN,
            {"project": "p2", "node": "devel3", "request": "x"},
        )

    assert "project_not_onboarded_on_node:p2:T610" in str(raised.value)
    assert await store.list_recent_tasks(db_session, 10) == []


@pytest.mark.asyncio
async def test_ambiguous_node_prefix_is_409_and_names_candidates(db_session: AsyncSession):
    await store.upsert_registry(
        db_session,
        executors=[
            ExecutorRegistration(
                executor_id="E2",
                display_name="second worker",
                machine_token="t2",
                allowed_projects=["p1"],
                max_concurrent_tasks=5,
            )
        ],
        projects=[],
    )
    second_node = await db_session.get(NodeModel, "E2")
    second_node.display_name = "devel30"
    await db_session.commit()
    hub = DummyHub()

    with pytest.raises(Exception) as raised:
        await _call(
            db_session,
            hub,
            ADMIN,
            {"project": "p1", "node": "devel", "request": "x"},
        )

    message = str(raised.value)
    assert "ambiguous_node" in message
    assert "T610 (devel3)" in message
    assert "E2 (devel30)" in message


@pytest.mark.asyncio
async def test_resolves_project_by_unique_prefix(db_session: AsyncSession):
    """"unclai" resolves uniquely to "unclaimed" -- proven by getting past

    project resolution to the NEXT gate (project_not_onboarded, since
    "unclaimed" has no executor allowing it), rather than "unknown_project".
    """
    hub = DummyHub()
    with pytest.raises(Exception) as raised:
        await _call(db_session, hub, ADMIN, {"project": "unclai", "request": "x"})
    assert "project_not_onboarded" in str(raised.value)


@pytest.mark.asyncio
async def test_ambiguous_project_reference_is_409_naming_every_candidate(db_session: AsyncSession):
    hub = DummyHub()
    with pytest.raises(Exception) as raised:
        await _call(db_session, hub, ADMIN, {"project": "p", "request": "x"})
    message = str(raised.value)
    assert "ambiguous_project" in message
    assert "p1" in message and "p2" in message


@pytest.mark.asyncio
async def test_unknown_project_reference_is_404(db_session: AsyncSession):
    hub = DummyHub()
    with pytest.raises(Exception) as raised:
        await _call(db_session, hub, ADMIN, {"project": "does-not-exist", "request": "x"})
    assert "unknown_project" in str(raised.value)


@pytest.mark.asyncio
async def test_project_not_onboarded_names_both_allowlist_files(db_session: AsyncSession):
    hub = DummyHub()
    with pytest.raises(Exception) as raised:
        await _call(db_session, hub, ADMIN, {"project": "unclaimed", "request": "x"})
    message = str(raised.value)
    assert "project_not_onboarded" in message
    assert "registry.json" in message
    assert "allowed-projects.json" in message


@pytest.mark.asyncio
async def test_allow_push_without_approval_authority_is_refused(db_session: AsyncSession):
    hub = DummyHub()
    with pytest.raises(Exception) as raised:
        await _call(db_session, hub, SUBMIT_ONLY, {
            "project": "p1", "request": "x", "allow_push": True, "branch": "feature/uc-1",
        })
    assert "missing_scope" in str(raised.value) or "approval_not_allowed" in str(raised.value)


@pytest.mark.asyncio
async def test_allow_push_without_a_branch_is_refused(db_session: AsyncSession):
    hub = DummyHub()
    with pytest.raises(Exception) as raised:
        await _call(db_session, hub, ADMIN, {"project": "p1", "request": "x", "allow_push": True})
    assert "branch_required_for_push" in str(raised.value)


@pytest.mark.asyncio
async def test_allow_push_to_an_unpushable_branch_is_refused(db_session: AsyncSession):
    hub = DummyHub()
    with pytest.raises(Exception) as raised:
        await _call(db_session, hub, ADMIN, {
            "project": "p1", "request": "x", "allow_push": True, "branch": "main",
        })
    assert "branch_not_pushable" in str(raised.value)


@pytest.mark.asyncio
async def test_allow_push_on_a_valid_branch_creates_a_preauthorized_task(db_session: AsyncSession):
    hub = DummyHub()
    hub.connected.add("T610")
    response = await _call(db_session, hub, ADMIN, {
        "project": "p1", "request": "implement and push", "allow_push": True, "branch": "feature/uc-1",
    })
    payload = response["result"]["structuredContent"]
    assert payload["branch"] == "feature/uc-1"
    assert payload["allow_push"] is True
    # ADMIN holds approval authority, so this resolves straight through --
    # never left pending for a human (shared.policy + store.create_task,
    # PR1's push-preauthorization-as-approval path). WAITING_EXECUTOR, not
    # QUEUED: decide_task_approval always lands an APPROVED task there,
    # whether or not the executor happens to be connected right now --
    # mirroring approve_codex_task's own handler.
    assert payload["state"] == "waiting_executor"

    task = await store.get_task(db_session, payload["task_id"])
    assert task.approval_state == "approved"


@pytest.mark.asyncio
async def test_issue_ref_invalid_shape_is_refused(db_session: AsyncSession):
    hub = DummyHub()
    with pytest.raises(Exception) as raised:
        await _call(db_session, hub, ADMIN, {"project": "p1", "issue": "../../etc/passwd"})
    assert "issue_ref_invalid" in str(raised.value)


@pytest.mark.asyncio
async def test_github_issue_reference_is_explicitly_unsupported(db_session: AsyncSession):
    hub = DummyHub()
    with pytest.raises(Exception) as raised:
        await _call(db_session, hub, ADMIN, {"project": "p1", "issue": "gh:57"})
    assert "issue_source_unsupported" in str(raised.value)


@pytest.mark.asyncio
async def test_an_unimplemented_engine_is_refused_before_dispatch(db_session: AsyncSession):
    """Council round 1, "the second caller": the tool's own JSON Schema

    accepts six candidate engines (shared.protocol.AgentEngine), but only
    "codex" and "claude" have a real Runner (shared.protocol.
    IMPLEMENTED_ENGINES). Without this check, the gateway would create and
    dispatch the task anyway, burning a dispatch cycle and the executor's
    one concurrency slot before the executor's own RunnerPool.for_engine
    rejects it asynchronously.
    """
    hub = DummyHub()
    with pytest.raises(Exception) as raised:
        await _call(db_session, hub, ADMIN, {"project": "p1", "request": "x", "engine": "gemini"})
    assert "engine_not_implemented:gemini" in str(raised.value)

    # And the task must never have been created at all.
    tasks = await store.list_recent_tasks(db_session, 10)
    assert tasks == []


@pytest.mark.asyncio
async def test_neither_request_nor_issue_is_refused(db_session: AsyncSession):
    hub = DummyHub()
    with pytest.raises(Exception) as raised:
        await _call(db_session, hub, ADMIN, {"project": "p1"})
    assert "request_or_issue_required" in str(raised.value)


@pytest.mark.asyncio
async def test_local_issue_reference_builds_a_default_request_from_its_title(db_session: AsyncSession):
    issue = await store.create_issue(
        db_session, project_id="p1", epic_id=None, title="Fix the login bug",
        description=None, status=None, priority=None, labels=None,
        assignee_user_id=None, assignee_email=None, dependencies=None,
        blocked_reason=None, actor_user_id="admin", actor_email="admin@example.com",
    )
    hub = DummyHub()
    response = await _call(db_session, hub, ADMIN, {"project": "p1", "issue": f"local:{issue.id}"})
    payload = response["result"]["structuredContent"]
    task = await store.get_task(db_session, payload["task_id"])
    assert "Fix the login bug" in task.instruction
    assert task.issue_ref == f"local:{issue.id}"


@pytest.mark.asyncio
async def test_local_issue_reference_in_another_project_is_unknown(db_session: AsyncSession):
    issue = await store.create_issue(
        db_session, project_id="p2", epic_id=None, title="Belongs to p2",
        description=None, status=None, priority=None, labels=None,
        assignee_user_id=None, assignee_email=None, dependencies=None,
        blocked_reason=None, actor_user_id="admin", actor_email="admin@example.com",
    )
    hub = DummyHub()
    with pytest.raises(Exception) as raised:
        await _call(db_session, hub, ADMIN, {"project": "p1", "issue": f"local:{issue.id}"})
    assert "unknown_issue" in str(raised.value)


@pytest.mark.asyncio
async def test_bare_issue_number_with_no_request_builds_a_generic_objective(db_session: AsyncSession):
    """"docs:NNN"/bare NNN forms are resolved on the EXECUTOR, not the

    gateway (docs/architecture.md) -- the gateway can still build a sensible
    default instruction from the reference alone.
    """
    hub = DummyHub()
    response = await _call(db_session, hub, ADMIN, {"project": "p1", "issue": "57"})
    payload = response["result"]["structuredContent"]
    task = await store.get_task(db_session, payload["task_id"])
    assert "57" in task.instruction
    assert task.issue_ref == "57"


@pytest.mark.asyncio
async def test_eta_reflects_real_task_history(db_session: AsyncSession):
    from shared.protocol import SubmitTaskRequest, TaskMode, TaskPriority, TaskState

    for seconds in (100, 200, 300, 400, 500):
        task = await store.create_task(
            db_session,
            SubmitTaskRequest(
                executor_id="T610", project_id="p1", instruction="past run", mode=TaskMode.IMPLEMENT,
                priority=TaskPriority.NORMAL, timeout_seconds=3600, run_when_available=True,
                expires_at=datetime.now(timezone.utc) + timedelta(hours=1), engine="claude",
            ),
            executor_online=True,
        )
        await store.update_task_state(db_session, task.id, TaskState.RUNNING)
        task = await db_session.get(type(task), task.id)
        anchor = datetime.now(timezone.utc)
        task.started_at = anchor - timedelta(seconds=seconds)
        task.completed_at = anchor
        task.state = TaskState.COMPLETED.value
        await db_session.commit()

    hub = DummyHub()
    response = await _call(db_session, hub, ADMIN, {"project": "p1", "request": "new one", "engine": "claude"})
    payload = response["result"]["structuredContent"]
    assert payload["eta_basis"] == "project+mode+engine"
    assert payload["eta_seconds"] == 300
    assert payload["eta_sample_size"] == 5
