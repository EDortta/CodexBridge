"""End-to-end wiring for a forge operation -- issue #80/#79,

WK-20260902-forge-wiring-and-gate (PR B3). Everything B1
(`shared/protocol.py`, `shared/policy.py`) and B2
(`agent/codex_bridge_agent/forge/`) shipped sat unconnected until this PR: no
module called `run_forge_operation`, nothing built a `FORGE_OPERATION`
envelope, and no table recorded a forge request at all. This suite proves the
full internal path works, end to end, without any of it going through a real
websocket or a real `gh`:

    store.create_forge_operation   -- born awaiting_approval (a write) or
                                       approved (a read, issue_list)
    hub.dispatch_forge_operation   -- THE gate: refuses, structurally, unless
                                       state == "approved"
    store.decide_forge_operation   -- the human decision a write waits for
    AgentService._handle_forge_operation -- the real executor handler (not
                                       just forge.github.run_forge_operation
                                       in isolation), run against a fake `gh`
    main.handle_forge_operation_result -- resolves the row from what the
                                       executor actually reported

Every test that calls `hub.dispatch_forge_operation` calls the REAL function,
never `shared.policy.forge_operation_policy_level` in isolation (that has its
own exhaustive suite, `tests/unit/test_forge_policy.py`) -- the risk this
suite defends against is a bypass added to the real dispatch/decide/handler
code later, not a regression in the pure policy function, which has no
bypass field to begin with (docs/napkin-lessons.md, 2026-09-01: "a narrow
test on a pure function stays green while the real path grows a bypass").
Every refusal is paired with a positive control in this same file.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from agent.codex_bridge_agent.config import AgentSettings
from agent.codex_bridge_agent.forge import github as forge_github
from agent.codex_bridge_agent.forge.gh_tool import GhResult
from agent.codex_bridge_agent.service import AgentService
from gateway.app.db.base import Base
from gateway.app.main import handle_forge_operation_result
from gateway.app.models.entities import ForgeOperationModel
from gateway.app.services import store
from gateway.app.services.agent_hub import AgentHub
from shared.protocol import (
    AgentEnvelope,
    AgentMessageType,
    ApprovalDecision,
    ExecutorRegistration,
    ForgeOperationKind,
    ForgeOperationRequest,
    ProjectRegistration,
)


class _DummyGatewayWebSocket:
    """Stands in for the executor's websocket on the gateway side of

    `AgentHub` -- same shape `tests/integration/test_decisions.py` already
    uses for the same purpose."""

    def __init__(self) -> None:
        self.sent: list[dict] = []

    async def send_json(self, payload: dict) -> None:
        self.sent.append(payload)


class _DummyExecutorWebSocket:
    """Stands in for the gateway's websocket on the executor side --

    `tests/unit/test_agent_service.py`'s own `DummyWebSocket` shape
    (`AgentService` calls `.send(str)`, not `.send_json(dict)`: the executor
    serializes its own envelope)."""

    def __init__(self) -> None:
        self.messages: list[str] = []

    async def send(self, payload: str) -> None:
        self.messages.append(payload)


@pytest.fixture
async def db():
    """A real database and session factory, seeded with one executor/project

    pair -- same pattern `tests/integration/test_push_preauthorization.py`
    uses. Yields `(session_factory, session)`: most calls use the shared
    `session`, and `AgentHub`/`decide`/`dispatch` open their own via the
    factory, exactly as they do in production.
    """
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
                )
            ],
            projects=[
                ProjectRegistration(project_id="p1", name="Projeto 1", path="/srv/p1"),
            ],
        )
        yield session_factory, session
    await engine.dispose()


def _write_request(**overrides) -> ForgeOperationRequest:
    fields = {
        "kind": ForgeOperationKind.ISSUE_OPEN,
        "repo_identity": "acme/widgets",
        "title": "Bug found",
        "body": "Steps to reproduce...",
    }
    fields.update(overrides)
    return ForgeOperationRequest(**fields)


def _read_request(**overrides) -> ForgeOperationRequest:
    fields = {"kind": ForgeOperationKind.ISSUE_LIST, "repo_identity": "acme/widgets"}
    fields.update(overrides)
    return ForgeOperationRequest(**fields)


# --------------------------------------------------------------------------
# The gate itself: a write is born awaiting_approval, and dispatch refuses
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_forge_write_is_born_awaiting_approval(db) -> None:
    _, session = db
    row = await store.create_forge_operation(
        session, executor_id="T610", project_id="p1", operation=_write_request()
    )
    assert row.state == "awaiting_approval"
    assert row.resolved_at is None


@pytest.mark.asyncio
async def test_dispatch_refuses_a_write_still_awaiting_approval(db) -> None:
    """THE required test: a forge write cannot be dispatched without passing

    the gate. Calls the real `AgentHub.dispatch_forge_operation`, not the
    pure policy function -- see this module's own docstring."""
    session_factory, session = db
    row = await store.create_forge_operation(
        session, executor_id="T610", project_id="p1", operation=_write_request()
    )
    hub = AgentHub(session_factory)
    websocket = _DummyGatewayWebSocket()
    await hub.register("T610", websocket)
    websocket.sent.clear()  # drop hello/replay bookkeeping noise from register()

    with pytest.raises(ValueError, match="forge_operation_not_approved"):
        await hub.dispatch_forge_operation(row.id)

    assert websocket.sent == []  # no envelope reached the executor


@pytest.mark.asyncio
async def test_rejected_forge_operation_never_dispatches(db) -> None:
    """A human `REJECTED` decision is just as terminal as never deciding at

    all -- the gate does not reopen for a second dispatch attempt."""
    session_factory, session = db
    row = await store.create_forge_operation(
        session, executor_id="T610", project_id="p1", operation=_write_request()
    )
    row = await store.decide_forge_operation(session, row.id, ApprovalDecision.REJECTED, reason="not now")
    assert row.state == "rejected"
    assert row.resolved_at is not None

    hub = AgentHub(session_factory)
    websocket = _DummyGatewayWebSocket()
    await hub.register("T610", websocket)
    websocket.sent.clear()

    with pytest.raises(ValueError, match="forge_operation_not_approved"):
        await hub.dispatch_forge_operation(row.id)
    assert websocket.sent == []


@pytest.mark.asyncio
async def test_issue_list_read_does_not_stop_at_the_gate(db) -> None:
    """Positive control for the two refusals above, and for issue #80/#79's

    own requirement: `issue_list` is READ and is never gated -- it is born
    `approved`, ready to dispatch on the same turn it is created."""
    session_factory, session = db
    row = await store.create_forge_operation(
        session, executor_id="T610", project_id="p1", operation=_read_request()
    )
    assert row.state == "approved"

    hub = AgentHub(session_factory)
    websocket = _DummyGatewayWebSocket()
    await hub.register("T610", websocket)
    websocket.sent.clear()

    dispatched = await hub.dispatch_forge_operation(row.id)
    assert dispatched is True
    assert len(websocket.sent) == 1
    assert websocket.sent[0]["type"] == AgentMessageType.FORGE_OPERATION.value
    assert websocket.sent[0]["payload"]["operation_id"] == row.id


@pytest.mark.asyncio
async def test_create_forge_operation_refuses_a_project_not_allowed_for_the_executor(db) -> None:
    """The gateway's OWN allowlist check (`executors.metadata_json`), separate

    from the executor's local one exercised in
    `tests/unit/test_agent_service.py`. Positive control is
    `test_forge_write_is_born_awaiting_approval` above, which uses the
    allowed pair."""
    _, session = db
    await store.upsert_registry(
        session,
        executors=[],
        projects=[ProjectRegistration(project_id="p2", name="Projeto 2", path="/srv/p2")],
    )
    with pytest.raises(ValueError, match="project_not_allowed_for_executor"):
        await store.create_forge_operation(
            session, executor_id="T610", project_id="p2", operation=_write_request()
        )


# --------------------------------------------------------------------------
# Full pipeline: request -> awaiting_approval -> approval -> dispatch ->
# FORGE_OPERATION_RESULT -> resolved row
# --------------------------------------------------------------------------


async def _dispatch_and_capture_envelope(hub: AgentHub, websocket: _DummyGatewayWebSocket, operation_id: str) -> AgentEnvelope:
    dispatched = await hub.dispatch_forge_operation(operation_id)
    assert dispatched is True
    return AgentEnvelope.model_validate(websocket.sent[-1])


async def _run_on_executor(service: AgentService, envelope: AgentEnvelope) -> AgentEnvelope:
    executor_ws = _DummyExecutorWebSocket()
    await service._handle_forge_operation(executor_ws, envelope)
    return AgentEnvelope.model_validate_json(executor_ws.messages[-1])


@pytest.mark.asyncio
async def test_full_pipeline_write_completes_after_a_human_approves(db, tmp_path: Path, monkeypatch) -> None:
    session_factory, session = db
    await store.upsert_registry(
        session,
        executors=[],
        projects=[ProjectRegistration(project_id="p1", name="Projeto 1", path=str(tmp_path))],
    )
    row = await store.create_forge_operation(
        session, executor_id="T610", project_id="p1", operation=_write_request()
    )
    assert row.state == "awaiting_approval"

    row = await store.decide_forge_operation(session, row.id, ApprovalDecision.APPROVED, reason="looks fine")
    assert row.state == "approved"

    hub = AgentHub(session_factory)
    gateway_ws = _DummyGatewayWebSocket()
    await hub.register("T610", gateway_ws)
    gateway_ws.sent.clear()
    dispatch_envelope = await _dispatch_and_capture_envelope(hub, gateway_ws, row.id)
    assert dispatch_envelope.type == AgentMessageType.FORGE_OPERATION
    assert dispatch_envelope.payload["operation_id"] == row.id

    async def fake_run_gh(*a, **k):
        return GhResult(returncode=0, stdout="https://github.com/acme/widgets/issues/7\n", stderr="")

    async def fake_run_git(*a, **k):
        # `_confirm_repo_identity_live`'s live remote check, WK-20260902-
        # forge-binding (PR B4): `tmp_path` has no real git remote, so the
        # workspace's "real" remote is faked to match `_write_request`'s
        # `repo_identity` -- the exact positive control this pipeline test
        # needs to still exercise the real `run_forge_operation` body rather
        # than stopping one gate earlier at `repo_identity_mismatch`.
        return 0, "https://github.com/acme/widgets.git\n", ""

    monkeypatch.setattr(forge_github, "run_gh", fake_run_gh)
    monkeypatch.setattr(forge_github, "run_git", fake_run_git)
    service = AgentService(AgentSettings(allow_forge_operations=True))
    service.projects = {
        "p1": ProjectRegistration(project_id="p1", name="Projeto 1", path=str(tmp_path))
    }
    result_envelope = await _run_on_executor(service, dispatch_envelope)
    assert result_envelope.type == AgentMessageType.FORGE_OPERATION_RESULT
    assert result_envelope.payload["outcome"] == "succeeded"
    assert result_envelope.payload["issue_number"] == 7

    async with session_factory() as resolve_session:
        await handle_forge_operation_result(resolve_session, result_envelope)

    async with session_factory() as check_session:
        resolved = await check_session.get(ForgeOperationModel, row.id)
        assert resolved.state == "completed"
        assert resolved.resolved_at is not None
        assert '"issue_number": 7' in resolved.result_json


@pytest.mark.asyncio
async def test_executor_kill_switch_refuses_even_after_gateway_approval(db, tmp_path: Path, monkeypatch) -> None:
    """The two locks are independent: a gateway approval is not, by itself,

    enough to make `gh` run. `allow_forge_operations=False` on the executor
    refuses regardless -- and the gateway still resolves the row (as
    `failed`), because a `FORGE_OPERATION_RESULT` came back either way."""
    session_factory, session = db
    await store.upsert_registry(
        session,
        executors=[],
        projects=[ProjectRegistration(project_id="p1", name="Projeto 1", path=str(tmp_path))],
    )
    row = await store.create_forge_operation(
        session, executor_id="T610", project_id="p1", operation=_write_request()
    )
    row = await store.decide_forge_operation(session, row.id, ApprovalDecision.APPROVED)

    hub = AgentHub(session_factory)
    gateway_ws = _DummyGatewayWebSocket()
    await hub.register("T610", gateway_ws)
    gateway_ws.sent.clear()
    dispatch_envelope = await _dispatch_and_capture_envelope(hub, gateway_ws, row.id)

    calls: list[object] = []

    async def fake_run_gh(*a, **k):
        calls.append((a, k))
        return GhResult(returncode=0, stdout="https://github.com/acme/widgets/issues/7\n", stderr="")

    monkeypatch.setattr(forge_github, "run_gh", fake_run_gh)
    service = AgentService(AgentSettings(allow_forge_operations=False))  # the trava, OFF
    service.projects = {
        "p1": ProjectRegistration(project_id="p1", name="Projeto 1", path=str(tmp_path))
    }
    result_envelope = await _run_on_executor(service, dispatch_envelope)
    assert result_envelope.payload["outcome"] == "refused"
    assert result_envelope.payload["reason"] == "executor_forge_disabled"
    assert calls == []  # gh was never invoked despite the gateway's approval

    async with session_factory() as resolve_session:
        await handle_forge_operation_result(resolve_session, result_envelope)
    async with session_factory() as check_session:
        resolved = await check_session.get(ForgeOperationModel, row.id)
        assert resolved.state == "failed"


@pytest.mark.asyncio
async def test_project_outside_executor_local_allowlist_refuses_even_after_gateway_approval(
    db, tmp_path: Path, monkeypatch
) -> None:
    """The executor's own project allowlist is the second independent gate:

    a gateway-approved operation for a project this executor was never
    configured to touch still never reaches `gh`. Positive control is
    `test_full_pipeline_write_completes_after_a_human_approves` above, which
    registers `p1` on the executor."""
    session_factory, session = db
    await store.upsert_registry(
        session,
        executors=[],
        projects=[ProjectRegistration(project_id="p1", name="Projeto 1", path=str(tmp_path))],
    )
    row = await store.create_forge_operation(
        session, executor_id="T610", project_id="p1", operation=_write_request()
    )
    row = await store.decide_forge_operation(session, row.id, ApprovalDecision.APPROVED)

    hub = AgentHub(session_factory)
    gateway_ws = _DummyGatewayWebSocket()
    await hub.register("T610", gateway_ws)
    gateway_ws.sent.clear()
    dispatch_envelope = await _dispatch_and_capture_envelope(hub, gateway_ws, row.id)

    calls: list[object] = []

    async def fake_run_gh(*a, **k):
        calls.append((a, k))
        return GhResult(returncode=0, stdout="https://github.com/acme/widgets/issues/7\n", stderr="")

    monkeypatch.setattr(forge_github, "run_gh", fake_run_gh)
    service = AgentService(AgentSettings(allow_forge_operations=True))
    service.projects = {}  # p1 not registered locally, and no auto_project_root
    result_envelope = await _run_on_executor(service, dispatch_envelope)
    assert result_envelope.payload["outcome"] == "refused"
    assert result_envelope.payload["reason"] == "unknown_project"
    assert calls == []

    async with session_factory() as resolve_session:
        await handle_forge_operation_result(resolve_session, result_envelope)
    async with session_factory() as check_session:
        resolved = await check_session.get(ForgeOperationModel, row.id)
        assert resolved.state == "failed"
