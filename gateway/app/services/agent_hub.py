from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from fastapi import WebSocket
from sqlalchemy.ext.asyncio import async_sessionmaker

from gateway.app.models.entities import ExecutorModel
from gateway.app.services import store
from shared.protocol import AgentEnvelope, AgentMessageType, TaskState


@dataclass
class AgentConnection:
    executor_id: str
    websocket: WebSocket
    connected_at: datetime


class AgentHub:
    def __init__(self, session_factory: async_sessionmaker):
        self.session_factory = session_factory
        self.connections: dict[str, AgentConnection] = {}
        self.running_tasks: dict[str, set[str]] = {}
        self._lock = asyncio.Lock()

    def is_connected(self, executor_id: str) -> bool:
        return executor_id in self.connections

    async def register(self, executor_id: str, websocket: WebSocket) -> None:
        async with self._lock:
            self.connections[executor_id] = AgentConnection(
                executor_id=executor_id,
                websocket=websocket,
                connected_at=datetime.now(timezone.utc),
            )
            self.running_tasks.setdefault(executor_id, set())
        async with self.session_factory() as session:
            await store.mark_executor_connected(session, executor_id, True)

    async def unregister(self, executor_id: str) -> None:
        async with self._lock:
            self.connections.pop(executor_id, None)
        async with self.session_factory() as session:
            try:
                await store.mark_executor_connected(session, executor_id, False)
            except ValueError:
                return

    async def send(self, executor_id: str, envelope: AgentEnvelope) -> None:
        connection = self.connections[executor_id]
        await connection.websocket.send_json(envelope.model_dump(mode="json"))

    async def dispatch_next(self, executor_id: str) -> dict[str, Any] | None:
        if executor_id not in self.connections:
            return None
        async with self.session_factory() as session:
            executor = await session.get(ExecutorModel, executor_id)
            if executor is None:
                return None
            metadata = json.loads(executor.metadata_json)
            if len(self.running_tasks.setdefault(executor_id, set())) >= int(metadata.get("max_concurrent_tasks", 1)):
                return None
            task = await store.next_dispatchable_task(session, executor_id)
            if task is None:
                return None
            await store.update_task_state(session, task.id, TaskState.RUNNING)
            self.running_tasks.setdefault(executor_id, set()).add(task.id)
            return {
                "task_id": task.id,
                "project_id": task.project_id,
                "instruction": task.instruction,
                "mode": task.mode,
                "timeout_seconds": task.timeout_seconds,
                "continue_session_id": task.session_id,
            }

    async def mark_task_finished(self, executor_id: str, task_id: str) -> None:
        self.running_tasks.setdefault(executor_id, set()).discard(task_id)


def hub_envelope(executor_id: str, message_type: str, payload: dict) -> AgentEnvelope:
    """Build a message for an executor.

    Lives here rather than in the MCP server because the envelope is a property
    of the agent channel, not of the transport that happens to ask for it. The
    HTTP sessions API sends `task.cancel` too, and a second hand-rolled
    constructor there was already one field short — `AgentEnvelope` requires
    `message_id`, `executor_id` and `sent_at`, and omitting them fails at
    validation time rather than at review time.
    """
    return AgentEnvelope(
        message_id=str(uuid4()),
        executor_id=executor_id,
        sent_at=datetime.now(timezone.utc),
        type=AgentMessageType(message_type),
        payload=payload,
    )
