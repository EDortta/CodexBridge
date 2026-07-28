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
