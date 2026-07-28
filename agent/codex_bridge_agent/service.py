from __future__ import annotations

import asyncio
import random
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlencode
from uuid import uuid4

import websockets

from agent.codex_bridge_agent.codex_runner import CodexRunner
from agent.codex_bridge_agent.config import AgentSettings, load_agent_projects
from shared.policy import evaluate_task_policy
from shared.protocol import AgentEnvelope, AgentMessageType, SubmitTaskRequest, TaskMode, TaskPriority, TaskState
from shared.security import ensure_within_root


BASE_PROMPT = (
    "You are running inside CodexBridge on an approved workspace only. "
    "Do not access parent directories, secrets, deployment targets, or other hosts. "
    "Do not push, deploy, migrate production, or modify infrastructure unless explicitly approved."
)


class AgentService:
    def __init__(self, settings: AgentSettings):
        self.settings = settings
        self.projects = load_agent_projects(settings.allowed_projects_file)
        self.runner = CodexRunner(settings)

    async def run_forever(self) -> None:
        delay = self.settings.reconnect_min_seconds
        while True:
            try:
                await self._run_once()
                delay = self.settings.reconnect_min_seconds
            except Exception:
                await asyncio.sleep(delay + random.uniform(0, 1))
                delay = min(delay * 2, self.settings.reconnect_max_seconds)

    async def _run_once(self) -> None:
        query = urlencode({"executor_id": self.settings.executor_id, "token": self.settings.machine_token})
        url = f"{self.settings.gateway_ws_url}?{query}"
        async with websockets.connect(url, max_size=2_000_000) as websocket:
            await websocket.send(self._envelope(AgentMessageType.HELLO, {"version": "0.1.0"}).model_dump_json())
            heartbeat_task = asyncio.create_task(self._heartbeat_loop(websocket))
            try:
                async for raw in websocket:
                    envelope = AgentEnvelope.model_validate_json(raw)
                    if envelope.type == AgentMessageType.TASK_DISPATCH:
                        asyncio.create_task(self._handle_dispatch(websocket, envelope))
                    elif envelope.type == AgentMessageType.TASK_CANCEL:
                        cancelled = await self.runner.cancel(envelope.payload["task_id"])
                        if cancelled:
                            await websocket.send(
                                self._envelope(
                                    AgentMessageType.TASK_CANCELLED,
                                    {"task_id": envelope.payload["task_id"]},
                                ).model_dump_json()
                            )
            finally:
                heartbeat_task.cancel()

    async def _heartbeat_loop(self, websocket) -> None:
        while True:
            await websocket.send(self._envelope(AgentMessageType.HEARTBEAT, {}).model_dump_json())
            await asyncio.sleep(self.settings.heartbeat_interval_seconds)

    async def _handle_dispatch(self, websocket, envelope: AgentEnvelope) -> None:
        task_id = envelope.payload["task_id"]
        project_id = envelope.payload["project_id"]
        project = self.projects.get(project_id)
        if project is None:
            await websocket.send(
                self._envelope(
                    AgentMessageType.TASK_RESULT,
                    {
                        "task_id": task_id,
                        "final_state": TaskState.FAILED.value,
                        "error": "unknown_project",
                    },
                ).model_dump_json()
            )
            return
        root = ensure_within_root(project.path, project.path)
        request = SubmitTaskRequest(
            executor_id=self.settings.executor_id,
            project_id=project_id,
            instruction=envelope.payload["instruction"],
            mode=TaskMode(envelope.payload["mode"]),
            timeout_seconds=int(envelope.payload["timeout_seconds"]),
            priority=TaskPriority.NORMAL,
            run_when_available=True,
            expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
        )
        decision = evaluate_task_policy(request)
        if not decision.approved and decision.level.value == "sensitive":
            await websocket.send(
                self._envelope(
                    AgentMessageType.TASK_RESULT,
                    {
                        "task_id": task_id,
                        "final_state": TaskState.FAILED.value,
                        "error": "sensitive_policy_blocked",
                    },
                ).model_dump_json()
            )
            return
        offset = 0

        async def send_log(stream: str, line: str) -> None:
            nonlocal offset
            offset += 1
            await websocket.send(
                self._envelope(
                    AgentMessageType.TASK_LOG,
                    {"task_id": task_id, "offset": offset, "stream": stream, "line": line},
                ).model_dump_json()
            )

        result = await self.runner.run_task(
            task_id=task_id,
            project_root=Path(root),
            instruction=f"{BASE_PROMPT}\n\nUser task:\n{envelope.payload['instruction']}",
            timeout_seconds=int(envelope.payload["timeout_seconds"]),
            continue_session_id=envelope.payload.get("continue_session_id"),
            send_log=send_log,
        )
        await websocket.send(self._envelope(AgentMessageType.TASK_RESULT, result).model_dump_json())

    def _envelope(self, message_type: AgentMessageType, payload: dict) -> AgentEnvelope:
        return AgentEnvelope(
            message_id=str(uuid4()),
            executor_id=self.settings.executor_id,
            sent_at=datetime.now(timezone.utc),
            type=message_type,
            payload=payload,
        )


async def main() -> None:
    service = AgentService(AgentSettings())
    await service.run_forever()


if __name__ == "__main__":
    asyncio.run(main())
