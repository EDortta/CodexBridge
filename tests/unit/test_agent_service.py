from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from agent.codex_bridge_agent.config import AgentSettings
from agent.codex_bridge_agent.service import AgentService, _sandbox_for
from shared.protocol import AgentEnvelope, AgentMessageType, PolicyLevel, ProjectRegistration


class DummyWebSocket:
    def __init__(self) -> None:
        self.messages: list[str] = []

    async def send(self, payload: str) -> None:
        self.messages.append(payload)


class FailingRunner:
    def mark_dispatched(self, _: str) -> None:
        pass

    def forget(self, _: str) -> None:
        pass

    async def run_task(self, **_: object) -> dict:
        raise FileNotFoundError("codex-not-found")


class ControlRunner:
    def __init__(self, *, pause: bool = True, resume: bool = True, restart: bool = True, known: bool = True) -> None:
        self.pause_result = pause
        self.resume_result = resume
        self.restart_result = restart
        self.known_result = known

    def is_known(self, _: str) -> bool:
        return self.known_result

    async def pause(self, _: str) -> bool:
        return self.pause_result

    async def resume(self, _: str) -> bool:
        return self.resume_result

    async def restart(self, _: str) -> bool:
        return self.restart_result


@pytest.mark.asyncio
async def test_dispatch_failure_returns_task_result(tmp_path: Path) -> None:
    service = AgentService(AgentSettings())
    service.projects = {
        "codexbridge": ProjectRegistration(
            project_id="codexbridge",
            name="CodexBridge",
            path=str(tmp_path),
        )
    }
    service.runner = FailingRunner()
    websocket = DummyWebSocket()
    envelope = AgentEnvelope(
        message_id="dispatch-1",
        executor_id="devel3",
        sent_at=datetime.now(timezone.utc),
        type=AgentMessageType.TASK_DISPATCH,
        payload={
            "task_id": "task-1",
            "project_id": "codexbridge",
            "instruction": "Analyze repository",
            "mode": "analyze",
            "timeout_seconds": 60,
        },
    )

    await service._handle_dispatch(websocket, envelope)

    assert len(websocket.messages) >= 2
    result = AgentEnvelope.model_validate_json(websocket.messages[-1])
    assert result.type == AgentMessageType.TASK_RESULT
    assert result.payload["task_id"] == "task-1"
    assert result.payload["final_state"] == "failed"
    assert result.payload["error"] == "codex-not-found"


class _RecordingConnect:
    """Captures how the agent opens the socket, then ends the loop.

    `_run_once` is where the credential is chosen. Asserting on the URL alone
    would pass even if the token were sent twice; the point of #15 is that it
    leaves the URL entirely, so both halves are checked.
    """

    def __init__(self) -> None:
        self.url: str | None = None
        self.kwargs: dict = {}

    def __call__(self, url: str, **kwargs):
        self.url = url
        self.kwargs = kwargs
        return self

    async def __aenter__(self):
        raise _StopRun()

    async def __aexit__(self, *_: object) -> bool:
        return False


class _StopRun(Exception):
    pass


class _FakeAgentSocket:
    """An async-iterable stand-in for the real websocket, so a control test can
    drive `_run_once`'s real TASK_PAUSE/RESUME/RESTART branches end to end
    instead of calling `service.runner.pause(...)` and hand-building the ack
    the production code is supposed to send."""

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


@pytest.mark.asyncio
async def test_machine_token_travels_in_a_header_not_the_url(monkeypatch) -> None:
    """The token in the query string was logged verbatim 107 times (#15)."""
    from shared.protocol import EXECUTOR_TOKEN_HEADER
    from agent.codex_bridge_agent import service as service_module

    recorder = _RecordingConnect()
    monkeypatch.setattr(service_module.websockets, "connect", recorder)

    service = AgentService(AgentSettings(executor_id="devel3", machine_token="s3cr3t"))
    with pytest.raises(_StopRun):
        await service._run_once()

    assert "s3cr3t" not in recorder.url
    assert "token=" not in recorder.url
    assert "executor_id=devel3" in recorder.url
    assert recorder.kwargs["extra_headers"][EXECUTOR_TOKEN_HEADER] == "s3cr3t"


@pytest.mark.asyncio
async def test_pause_resume_and_restart_controls_acknowledge_over_the_socket(monkeypatch) -> None:
    """Drives the real `_run_once` dispatch loop, not a copy of it.

    A version of this test that called `service.runner.pause(...)` directly
    and hand-built the ack envelope stayed green when the real
    TASK_PAUSE/RESUME/RESTART branches in `_run_once` were gutted to send no
    ack at all — the whole suite (292 tests) stayed green with the real wiring
    completely broken (council 2026-08-18, "the claim auditor"). Routing
    through `_run_once` with a fake socket, the same mutation now fails this
    test directly.
    """
    from agent.codex_bridge_agent import service as service_module

    service = AgentService(AgentSettings())
    service.runner = ControlRunner()

    incoming = [
        service._envelope(message_type, {"task_id": "task-1"}).model_dump_json()
        for message_type in (
            AgentMessageType.TASK_PAUSE,
            AgentMessageType.TASK_RESUME,
            AgentMessageType.TASK_RESTART,
        )
    ]
    socket = _FakeAgentSocket(incoming)
    monkeypatch.setattr(service_module.websockets, "connect", _FakeConnect(socket))

    await service._run_once()

    acks = [
        AgentEnvelope.model_validate_json(payload)
        for payload in socket.sent
        if AgentEnvelope.model_validate_json(payload).type == AgentMessageType.TASK_ACK
    ]
    assert [ack.payload["control"] for ack in acks] == ["pause", "resume", "restart"]
    assert [ack.payload["accepted"] for ack in acks] == [True, True, True]
    assert [ack.payload["state"] for ack in acks] == ["paused", "running", "running"]
    assert [ack.payload["known"] for ack in acks] == [True, True, True]


@pytest.mark.asyncio
async def test_cancel_of_an_unknown_task_still_acks_over_the_socket(monkeypatch) -> None:
    """issue #17 council round 1, "the claim auditor" / "the second caller":
    a fresh `CodexRunner` (e.g. an executor host that just restarted, or a
    reconnect replay for a task that was never dispatched at all) returns
    `False` from `cancel()`. The old `if cancelled:` guard sent nothing back
    in that case, so the gateway waited forever for a `task.cancelled` that
    could never arrive — pinning the executor's concurrency slot for the
    life of the gateway process. A cancel's postcondition ("not running
    here") holds either way, so the ack must be unconditional."""
    from agent.codex_bridge_agent import service as service_module
    from agent.codex_bridge_agent.codex_runner import CodexRunner

    service = AgentService(AgentSettings())
    service.runner = CodexRunner(AgentSettings())  # empty: knows no tasks

    incoming = [service._envelope(AgentMessageType.TASK_CANCEL, {"task_id": "ghost-task"}).model_dump_json()]
    socket = _FakeAgentSocket(incoming)
    monkeypatch.setattr(service_module.websockets, "connect", _FakeConnect(socket))

    await service._run_once()

    acks = [
        AgentEnvelope.model_validate_json(payload)
        for payload in socket.sent
        if AgentEnvelope.model_validate_json(payload).type == AgentMessageType.TASK_CANCELLED
    ]
    assert len(acks) == 1
    assert acks[0].payload["task_id"] == "ghost-task"


@pytest.mark.asyncio
async def test_pause_of_an_unknown_task_reports_known_false(monkeypatch) -> None:
    """The control-message sibling of the cancel case above (issue #17
    council round 1, "the sweep skeptic"): before `known` existed, a fresh
    runner rejecting a `task.pause` for a task it never heard of looked
    identical, over the wire, to a live runner rejecting one for a real
    reason (already paused). The gateway could not tell "revert to RUNNING,
    the process is still alive" from "there is no process at all"."""
    from agent.codex_bridge_agent import service as service_module
    from agent.codex_bridge_agent.codex_runner import CodexRunner

    service = AgentService(AgentSettings())
    service.runner = CodexRunner(AgentSettings())  # empty: knows no tasks

    incoming = [service._envelope(AgentMessageType.TASK_PAUSE, {"task_id": "ghost-task"}).model_dump_json()]
    socket = _FakeAgentSocket(incoming)
    monkeypatch.setattr(service_module.websockets, "connect", _FakeConnect(socket))

    await service._run_once()

    acks = [
        AgentEnvelope.model_validate_json(payload)
        for payload in socket.sent
        if AgentEnvelope.model_validate_json(payload).type == AgentMessageType.TASK_ACK
    ]
    assert len(acks) == 1
    assert acks[0].payload["accepted"] is False
    assert acks[0].payload["known"] is False


class _RecordingRunner:
    """Records call order to prove `_handle_dispatch` brackets a task's whole
    observable lifetime with `mark_dispatched`/`forget`, not just the span
    `run_task` itself is on the stack for."""

    def __init__(self, calls: list[str]) -> None:
        self.calls = calls

    def mark_dispatched(self, task_id: str) -> None:
        self.calls.append(f"mark_dispatched:{task_id}")

    def forget(self, task_id: str) -> None:
        self.calls.append(f"forget:{task_id}")

    async def run_task(self, *, task_id: str, **_: object) -> dict:
        self.calls.append(f"run_task:start:{task_id}")
        self.calls.append(f"run_task:end:{task_id}")
        return {
            "task_id": task_id,
            "final_state": "completed",
            "return_code": 0,
            "duration_seconds": 0,
            "command": [],
            "command_redacted": [],
            "codex_session_id": None,
            "codex_version": "",
            "started_at": datetime.now(timezone.utc).isoformat(),
            "last_message": "",
            "pre_git": {},
            "post_git": {},
            "tests_ran": [],
            "no_changes": True,
            "raw_events": [],
        }


class _OrderedWebSocket:
    """Same recording list as `_RecordingRunner`, so send order interleaves
    with runner calls in one timeline."""

    def __init__(self, calls: list[str]) -> None:
        self.calls = calls
        self.messages: list[str] = []

    async def send(self, payload: str) -> None:
        self.messages.append(payload)
        envelope_type = AgentEnvelope.model_validate_json(payload).type.value
        self.calls.append(f"send:{envelope_type}")


@pytest.mark.asyncio
async def test_handle_dispatch_forgets_the_task_only_after_the_result_is_sent(tmp_path: Path) -> None:
    """finding 14 (council round 2, "the second caller"): before this fix,
    nothing called `mark_dispatched`/`forget` at all — `is_known` read
    `CodexRunner.running` directly, empty during dispatch setup and popped by
    `run_task`'s own `finally` before `_handle_dispatch` ever built the
    `task.result` to send. A control message landing in either gap saw a live
    (or just-finished) task as unknown to the runner. `mark_dispatched` must
    run before anything that could reach `run_task`, and `forget` only after
    the result has actually been sent.
    """
    calls: list[str] = []
    service = AgentService(AgentSettings())
    service.runner = _RecordingRunner(calls)
    service.projects = {
        "codexbridge": ProjectRegistration(
            project_id="codexbridge",
            name="CodexBridge",
            path=str(tmp_path),
        )
    }
    websocket = _OrderedWebSocket(calls)
    envelope = AgentEnvelope(
        message_id="dispatch-1",
        executor_id="devel3",
        sent_at=datetime.now(timezone.utc),
        type=AgentMessageType.TASK_DISPATCH,
        payload={
            "task_id": "task-1",
            "project_id": "codexbridge",
            "instruction": "Analyze repository",
            "mode": "analyze",
            "timeout_seconds": 60,
        },
    )

    await service._handle_dispatch(websocket, envelope)

    assert calls == [
        "mark_dispatched:task-1",
        "run_task:start:task-1",
        "run_task:end:task-1",
        "send:task.result",
        "forget:task-1",
    ]


# --------------------------------------------------------------------------
# Issue #34: sandbox derived from policy level, and the machine-level override
# --------------------------------------------------------------------------


def test_sandbox_for_is_read_only_for_the_read_policy_level() -> None:
    assert _sandbox_for(PolicyLevel.READ, allow_workspace_write=True) == "read-only"
    # The machine override cannot make a read-level task write either way —
    # there is nothing for it to override here.
    assert _sandbox_for(PolicyLevel.READ, allow_workspace_write=False) == "read-only"


def test_sandbox_for_is_workspace_write_for_controlled_write_and_sensitive() -> None:
    assert _sandbox_for(PolicyLevel.CONTROLLED_WRITE, allow_workspace_write=True) == "workspace-write"
    assert _sandbox_for(PolicyLevel.SENSITIVE, allow_workspace_write=True) == "workspace-write"


def test_sandbox_for_machine_override_forces_read_only_even_for_write_levels() -> None:
    """`AgentSettings.allow_workspace_write=False` is the executor's own kill
    switch — it must win over what the task's mode asked for, not merely
    default the same way."""
    assert _sandbox_for(PolicyLevel.CONTROLLED_WRITE, allow_workspace_write=False) == "read-only"
    assert _sandbox_for(PolicyLevel.SENSITIVE, allow_workspace_write=False) == "read-only"


class _SandboxRecordingRunner:
    """Only cares about the `sandbox=` kwarg `_handle_dispatch` passes to
    `run_task` — everything else is `_RecordingRunner`'s minimal success stub."""

    def __init__(self) -> None:
        self.sandboxes: list[str] = []

    def mark_dispatched(self, _: str) -> None:
        pass

    def forget(self, _: str) -> None:
        pass

    async def run_task(self, *, task_id: str, sandbox: str, **_: object) -> dict:
        self.sandboxes.append(sandbox)
        return {
            "task_id": task_id,
            "final_state": "completed",
            "return_code": 0,
            "duration_seconds": 0,
            "command": [],
            "command_redacted": [],
            "codex_session_id": None,
            "codex_version": "",
            "started_at": datetime.now(timezone.utc).isoformat(),
            "last_message": "",
            "pre_git": {},
            "post_git": {},
            "tests_ran": [],
            "no_changes": True,
            "raw_events": [],
        }


def _dispatch_envelope(*, task_id: str, mode: str, instruction: str = "do the thing") -> AgentEnvelope:
    return AgentEnvelope(
        message_id=f"dispatch-{task_id}",
        executor_id="devel3",
        sent_at=datetime.now(timezone.utc),
        type=AgentMessageType.TASK_DISPATCH,
        payload={
            "task_id": task_id,
            "project_id": "codexbridge",
            "instruction": instruction,
            "mode": mode,
            "timeout_seconds": 60,
        },
    )


@pytest.mark.asyncio
async def test_handle_dispatch_sends_read_only_for_a_read_mode_task(tmp_path: Path) -> None:
    service = AgentService(AgentSettings())
    runner = _SandboxRecordingRunner()
    service.runner = runner
    service.projects = {
        "codexbridge": ProjectRegistration(project_id="codexbridge", name="CodexBridge", path=str(tmp_path))
    }

    await service._handle_dispatch(DummyWebSocket(), _dispatch_envelope(task_id="t-read", mode="analyze"))

    assert runner.sandboxes == ["read-only"]


@pytest.mark.asyncio
async def test_handle_dispatch_sends_workspace_write_for_a_write_mode_task(tmp_path: Path) -> None:
    service = AgentService(AgentSettings())
    runner = _SandboxRecordingRunner()
    service.runner = runner
    service.projects = {
        "codexbridge": ProjectRegistration(project_id="codexbridge", name="CodexBridge", path=str(tmp_path))
    }

    await service._handle_dispatch(DummyWebSocket(), _dispatch_envelope(task_id="t-write", mode="edit"))

    assert runner.sandboxes == ["workspace-write"]


@pytest.mark.asyncio
async def test_handle_dispatch_honours_the_machine_level_read_only_override(tmp_path: Path) -> None:
    """A write-mode task still only gets `read-only` when this executor's own
    `allow_workspace_write` is off — the override must reach `run_task`, not
    just exist on `AgentSettings`."""
    service = AgentService(AgentSettings(allow_workspace_write=False))
    runner = _SandboxRecordingRunner()
    service.runner = runner
    service.projects = {
        "codexbridge": ProjectRegistration(project_id="codexbridge", name="CodexBridge", path=str(tmp_path))
    }

    await service._handle_dispatch(DummyWebSocket(), _dispatch_envelope(task_id="t-locked", mode="implement"))

    assert runner.sandboxes == ["read-only"]
