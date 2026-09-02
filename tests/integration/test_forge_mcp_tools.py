"""The forge-routed MCP tools -- issue #79/#80, WK-20260902-forge-binding

(PR B4): `bind_project_forge`, `create_project_issue`, `list_project_issues`,
`comment_project_issue`, `close_project_issue`. The property every test here
is weighted toward: routing is a plain `if` over
`gateway.app.services.forge_routing.project_forge_binding` -- the operator
calls the SAME tool, with the SAME arguments, whether or not the project is
bound, and nothing in the call itself has to name which case it is in.
`test_list_project_issues_routes_identically_bound_vs_unbound` is the direct
test of that property, mirroring the required test named in the task
description.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from gateway.app.core.users import AuthenticatedPrincipal
from gateway.app.db.base import Base
from gateway.app.mcp.server import handle_mcp_call
from gateway.app.services import store
from shared.protocol import ExecutorRegistration, ProjectRegistration


class DummyHub:
    """Mirrors `tests/integration/test_start_development_task.py`'s own

    `DummyHub`, extended with `dispatch_forge_operation` -- the one extra
    method the forge-routed tools call that the task-only tools do not.
    Returns `False` (the same "no envelope actually left, executor
    disconnected" answer `AgentHub`'s real one gives) unless a test opts in
    via `self.forge_dispatch_result`.
    """

    def __init__(self) -> None:
        self.connected: set[str] = set()
        self.sent: list[tuple[str, object]] = []
        self.forge_dispatch_result = False
        self.forge_dispatched_ids: list[str] = []

    def is_connected(self, executor_id: str) -> bool:
        return executor_id in self.connected

    async def dispatch_next(self, executor_id: str):
        return None

    async def send(self, executor_id: str, envelope) -> None:
        self.sent.append((executor_id, envelope))

    async def dispatch_forge_operation(self, operation_id: str) -> bool:
        self.forge_dispatched_ids.append(operation_id)
        return self.forge_dispatch_result


ADMIN = AuthenticatedPrincipal(
    user_id="admin",
    email="admin@example.com",
    roles=["admin"],
    allowed_projects=["p1"],
    scopes=[
        "codexbridge.read",
        "codexbridge.task.submit",
        "codexbridge.task.approve",
        "codexbridge.admin",
        "codexbridge.issues.write",
    ],
    can_approve_sensitive=True,
)

# Can write issues, but not bind a project's forge repository -- proves
# `bind_project_forge` needs its own, stronger scope.
ISSUE_WRITER = AuthenticatedPrincipal(
    user_id="writer",
    email="writer@example.com",
    allowed_projects=["p1"],
    scopes=["codexbridge.read", "codexbridge.issues.write"],
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
                )
            ],
            projects=[
                ProjectRegistration(project_id="p1", name="Projeto Um", path="/srv/p1", max_timeout_seconds=3600),
            ],
        )
        yield session
    await engine.dispose()


async def _call(session, hub, principal, tool: str, arguments: dict) -> dict:
    return await handle_mcp_call(
        {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": tool, "arguments": arguments}},
        session, hub, principal,
    )


async def _bind(session, hub, repo_identity: str = "acme/widgets", confirm: bool = False) -> dict:
    response = await _call(
        session, hub, ADMIN, "bind_project_forge",
        {"project": "p1", "repo_identity": repo_identity, "confirm": confirm},
    )
    return response["result"]["structuredContent"]


# --------------------------------------------------------------------------
# bind_project_forge
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_bind_requires_admin_scope(db_session: AsyncSession):
    hub = DummyHub()
    with pytest.raises(Exception) as excinfo:
        await _call(db_session, hub, ISSUE_WRITER, "bind_project_forge", {"project": "p1", "repo_identity": "acme/widgets"})
    assert "missing_scope" in str(excinfo.value.detail if hasattr(excinfo.value, "detail") else excinfo.value)


@pytest.mark.asyncio
async def test_bind_declares_by_default_and_confirms_on_request(db_session: AsyncSession):
    hub = DummyHub()
    declared = await _bind(db_session, hub, confirm=False)
    assert declared["confidence"] == "declared"
    assert declared["repo_identity"] == "acme/widgets"

    confirmed = await _bind(db_session, hub, confirm=True)
    assert confirmed["confidence"] == "confirmed"

    from gateway.app.services.forge_routing import project_forge_binding

    binding = await project_forge_binding(db_session, "p1")
    assert binding is not None
    assert binding.repo_identity == "acme/widgets"
    assert binding.confidence == "confirmed"


@pytest.mark.asyncio
async def test_bind_rejects_a_malformed_repo_identity(db_session: AsyncSession):
    hub = DummyHub()
    with pytest.raises(Exception):
        await _call(db_session, hub, ADMIN, "bind_project_forge", {"project": "p1", "repo_identity": "--flag/x"})


# --------------------------------------------------------------------------
# create_project_issue
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_issue_unbound_creates_local_issue_immediately(db_session: AsyncSession):
    hub = DummyHub()
    response = await _call(
        db_session, hub, ADMIN, "create_project_issue", {"project": "p1", "title": "Fix the thing"}
    )
    payload = response["result"]["structuredContent"]
    assert payload["route"] == "local"

    issue = await store.get_issue(db_session, payload["issue_id"])
    assert issue is not None
    assert issue.title == "Fix the thing"
    assert issue.project_id == "p1"


@pytest.mark.asyncio
async def test_create_issue_bound_opens_a_forge_operation_awaiting_approval(db_session: AsyncSession):
    hub = DummyHub()
    hub.connected.add("T610")
    await _bind(db_session, hub)

    response = await _call(
        db_session, hub, ADMIN, "create_project_issue",
        {"project": "p1", "title": "Bug found", "body": "Steps to reproduce"},
    )
    payload = response["result"]["structuredContent"]
    assert payload["route"] == "forge"
    assert payload["state"] == "awaiting_approval"
    assert payload["repo_identity"] == "acme/widgets"

    operation = await store.get_forge_operation(db_session, payload["operation_id"])
    assert operation is not None
    assert operation.kind == "issue_open"
    assert operation.state == "awaiting_approval"
    # A forge write is never dispatched by this tool -- it waits at the
    # Decision Center like every other forge write.
    assert hub.forge_dispatched_ids == []

    # And no local issue was created for the same request.
    local_issues = await store.list_issues_page(db_session, project_id="p1")
    assert local_issues == []


# --------------------------------------------------------------------------
# list_project_issues -- the flagship "same call, no hint" test
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_project_issues_routes_identically_bound_vs_unbound(db_session: AsyncSession):
    """THE required test: the exact same MCP call (`list_project_issues`,

    `{"project": "p1"}`, nothing else) is answered by the forge route when
    bound and the local route when not -- the operator's call never names
    which case it is in.
    """
    hub = DummyHub()
    hub.connected.add("T610")

    # Unbound first: seed a local issue so the local route has something to
    # return.
    await store.create_issue(
        db_session, project_id="p1", epic_id=None, title="Local issue", description=None,
        status=None, priority=None, labels=None, assignee_user_id=None, assignee_email=None,
        dependencies=None, blocked_reason=None, actor_user_id="admin", actor_email=None,
    )
    unbound_response = await _call(db_session, hub, ADMIN, "list_project_issues", {"project": "p1"})
    unbound_payload = unbound_response["result"]["structuredContent"]
    assert unbound_payload["route"] == "local"
    assert [item["title"] for item in unbound_payload["issues"]] == ["Local issue"]

    # Now bind, and issue the EXACT SAME call.
    await _bind(db_session, hub)
    bound_response = await _call(db_session, hub, ADMIN, "list_project_issues", {"project": "p1"})
    bound_payload = bound_response["result"]["structuredContent"]
    assert bound_payload["route"] == "forge"
    assert bound_payload["repo_identity"] == "acme/widgets"
    # A read is dispatched immediately, unlike a write -- it never waits at
    # the Decision Center (shared.policy.forge_operation_policy_level: READ).
    operation = await store.get_forge_operation(db_session, bound_payload["operation_id"])
    assert operation.kind == "issue_list"
    assert operation.state == "approved"  # never awaiting_approval -- reads are never gated
    assert hub.forge_dispatched_ids == [bound_payload["operation_id"]]


@pytest.mark.asyncio
async def test_list_project_issues_needs_no_scope_beyond_read(db_session: AsyncSession):
    reader = AuthenticatedPrincipal(
        user_id="reader", email="reader@example.com", allowed_projects=["p1"], scopes=["codexbridge.read"],
    )
    hub = DummyHub()
    response = await _call(db_session, hub, reader, "list_project_issues", {"project": "p1"})
    assert response["result"]["structuredContent"]["route"] == "local"


# --------------------------------------------------------------------------
# comment_project_issue -- forge-only, no local equivalent
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_comment_unbound_is_a_typed_refusal(db_session: AsyncSession):
    hub = DummyHub()
    with pytest.raises(Exception) as excinfo:
        await _call(db_session, hub, ADMIN, "comment_project_issue", {"project": "p1", "issue": 7, "body": "hi"})
    detail = getattr(excinfo.value, "detail", str(excinfo.value))
    assert detail == "forge_binding_required"


@pytest.mark.asyncio
async def test_comment_bound_opens_a_forge_operation(db_session: AsyncSession):
    hub = DummyHub()
    hub.connected.add("T610")
    await _bind(db_session, hub)

    response = await _call(
        db_session, hub, ADMIN, "comment_project_issue", {"project": "p1", "issue": 7, "body": "Looking into it"}
    )
    payload = response["result"]["structuredContent"]
    assert payload["state"] == "awaiting_approval"
    operation = await store.get_forge_operation(db_session, payload["operation_id"])
    assert operation.kind == "issue_comment"
    assert operation.repo_identity == "acme/widgets"


# --------------------------------------------------------------------------
# close_project_issue
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_close_unbound_marks_the_local_issue_done(db_session: AsyncSession):
    hub = DummyHub()
    issue = await store.create_issue(
        db_session, project_id="p1", epic_id=None, title="To close", description=None,
        status=None, priority=None, labels=None, assignee_user_id=None, assignee_email=None,
        dependencies=None, blocked_reason=None, actor_user_id="admin", actor_email=None,
    )
    response = await _call(db_session, hub, ADMIN, "close_project_issue", {"project": "p1", "issue": issue.id})
    payload = response["result"]["structuredContent"]
    assert payload["route"] == "local"
    assert payload["state"] == "done"


@pytest.mark.asyncio
async def test_close_unbound_unknown_issue_is_not_found(db_session: AsyncSession):
    hub = DummyHub()
    with pytest.raises(Exception) as excinfo:
        await _call(db_session, hub, ADMIN, "close_project_issue", {"project": "p1", "issue": "nope"})
    detail = getattr(excinfo.value, "detail", str(excinfo.value))
    assert detail == "unknown_issue"


@pytest.mark.asyncio
async def test_close_bound_opens_a_forge_operation(db_session: AsyncSession):
    hub = DummyHub()
    hub.connected.add("T610")
    await _bind(db_session, hub)

    response = await _call(db_session, hub, ADMIN, "close_project_issue", {"project": "p1", "issue": "12"})
    payload = response["result"]["structuredContent"]
    assert payload["route"] == "forge"
    operation = await store.get_forge_operation(db_session, payload["operation_id"])
    assert operation.kind == "issue_close"
    assert operation.state == "awaiting_approval"
