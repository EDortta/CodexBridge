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
