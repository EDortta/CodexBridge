from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from agent.codex_bridge_agent.config import AgentSettings
from agent.codex_bridge_agent.service import AgentService
from shared.protocol import AgentEnvelope, AgentMessageType, ProjectRegistration


class DummyWebSocket:
    def __init__(self) -> None:
        self.messages: list[str] = []

    async def send(self, payload: str) -> None:
        self.messages.append(payload)


class FailingRunner:
    async def run_task(self, **_: object) -> dict:
        raise FileNotFoundError("codex-not-found")


class ControlRunner:
    def __init__(self, *, pause: bool = True, resume: bool = True, restart: bool = True) -> None:
        self.pause_result = pause
        self.resume_result = resume
        self.restart_result = restart

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
