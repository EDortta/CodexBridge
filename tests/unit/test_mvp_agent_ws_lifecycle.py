"""MVP regression tests for the existing Agent WebSocket task lifecycle.

These tests intentionally target missing guarantees first (red phase).
They run with a simulated WebSocket and never execute a real coding CLI.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from pathlib import Path

import pytest

from agent.codex_bridge_agent.config import AgentSettings
from agent.codex_bridge_agent.service import AgentService
from shared.protocol import AgentEnvelope, AgentMessageType, ProjectRegistration


class Socket:
    def __init__(self):
        self.sent = []

    async def send(self, message: str):
        self.sent.append(AgentEnvelope.model_validate_json(message))


class Runner:
    def __init__(self):
        self.calls = 0
        self.entered = asyncio.Event()
        self.release = asyncio.Event()

    def mark_dispatched(self, task_id):
        pass

    def forget(self, task_id):
        pass

    async def run_task(self, **kwargs):
        self.calls += 1
        self.entered.set()
        await self.release.wait()
        return {
            "task_id": kwargs["task_id"],
            "final_state": "completed",
            "return_code": 0,
            "duration_seconds": 0,
        }


def dispatch(task_id: str):
    return AgentEnvelope(
        message_id=f"dispatch-{task_id}",
        executor_id="devel3",
        sent_at=datetime.now(timezone.utc),
        type=AgentMessageType.TASK_DISPATCH,
        payload={
            "task_id": task_id,
            "project_id": "sample",
            "instruction": "Analyze repository without changing files",
            "mode": "analyze",
            "timeout_seconds": 60,
        },
    )


def service_for(tmp_path: Path):
    service = AgentService(AgentSettings())
    service.projects = {
        "sample": ProjectRegistration(
            project_id="sample", name="Sample", path=str(tmp_path)
        )
    }
    runner = Runner()
    service.runners._runners["codex"] = runner
    return service, runner


@pytest.mark.asyncio
async def test_dispatch_ack_precedes_result(tmp_path):
    service, runner = service_for(tmp_path)
    socket = Socket()
    runner.release.set()
    await service._handle_dispatch(socket, dispatch("ack-1"))
    task_messages = [
        message for message in socket.sent
        if message.payload.get("task_id") == "ack-1"
    ]
    assert task_messages[0].type == AgentMessageType.TASK_ACK
    assert task_messages[0].payload["accepted"] is True
    assert task_messages[-1].type == AgentMessageType.TASK_RESULT
    assert runner.calls == 1


@pytest.mark.asyncio
async def test_concurrent_duplicate_dispatch_does_not_restart_task(tmp_path):
    service, runner = service_for(tmp_path)
    socket = Socket()
    first = asyncio.create_task(service._handle_dispatch(socket, dispatch("same-id")))
    try:
        await asyncio.wait_for(runner.entered.wait(), timeout=2)
        second = asyncio.create_task(service._handle_dispatch(socket, dispatch("same-id")))
        try:
            await asyncio.wait_for(second, timeout=2)
        finally:
            second.cancel()
        assert runner.calls == 1
    finally:
        runner.release.set()
        await asyncio.wait_for(first, timeout=2)
