from __future__ import annotations

import asyncio
import random
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlencode
from uuid import uuid4

import websockets

from agent.codex_bridge_agent.config import AgentSettings, load_agent_projects
from agent.codex_bridge_agent.git_delivery import deliver_changes
from agent.codex_bridge_agent.runners.base import EngineNotImplementedError
from agent.codex_bridge_agent.runners.codex import SANDBOX_READ_ONLY, SANDBOX_WORKSPACE_WRITE
from agent.codex_bridge_agent.runners.pool import RunnerPool
from shared.policy import evaluate_task_policy
from shared.protocol import (
    EXECUTOR_TOKEN_HEADER,
    AgentEnvelope,
    AgentMessageType,
    DeliveryRequest,
    PolicyLevel,
    SubmitTaskRequest,
    TaskMode,
    TaskPriority,
    TaskState,
)
from shared.security import ensure_within_root


BASE_PROMPT = (
    "You are running inside CodexBridge on an approved workspace only. "
    "Do not access parent directories, secrets, deployment targets, or other hosts. "
    "Do not push, deploy, migrate production, or modify infrastructure unless explicitly approved."
)


def _sandbox_for(policy_level: PolicyLevel, *, allow_workspace_write: bool) -> str:
    """Issue #34: the sandbox `codex exec` runs a dispatched task under.

    Read-only unless the task's own mode already opted into writing
    (`PolicyLevel.CONTROLLED_WRITE`/`SENSITIVE` — see
    `shared/policy.py:policy_level_for_mode`; a `SENSITIVE` task only reaches
    here at all once `_handle_dispatch`'s approval gate above has let it
    through, so by the time this runs it is exactly as write-intending as a
    `CONTROLLED_WRITE` one). `allow_workspace_write=False` is the executor's
    own machine-level override (`AgentSettings.allow_workspace_write`) and
    wins regardless of what the task asked for — the same "last barrier on
    this machine" shape `allowed_projects_file` already has for project
    scope.
    """
    if policy_level == PolicyLevel.READ:
        return SANDBOX_READ_ONLY
    return SANDBOX_WORKSPACE_WRITE if allow_workspace_write else SANDBOX_READ_ONLY


class AgentService:
    def __init__(self, settings: AgentSettings):
        self.settings = settings
        self.projects = load_agent_projects(settings.allowed_projects_file)
        # WK-20260830-chatgpt-entry-provider-and-delivery: was a single
        # `CodexRunner`; `RunnerPool` routes to the engine a dispatch names,
        # defaulting to "codex" for a payload that predates the `engine`
        # field so an unmodified gateway keeps dispatching correctly.
        self.runners = RunnerPool(settings)

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
        # `executor_id` stays in the query — it names the executor, it is not a
        # secret. The machine token moves to a header so it stops being written
        # to every access log between here and the gateway (#15).
        query = urlencode({"executor_id": self.settings.executor_id})
        url = f"{self.settings.gateway_ws_url}?{query}"
        headers = {EXECUTOR_TOKEN_HEADER: self.settings.machine_token}
        async with websockets.connect(url, max_size=2_000_000, extra_headers=headers) as websocket:
            await websocket.send(self._envelope(AgentMessageType.HELLO, {"version": "0.1.0"}).model_dump_json())
            heartbeat_task = asyncio.create_task(self._heartbeat_loop(websocket))
            try:
                async for raw in websocket:
                    envelope = AgentEnvelope.model_validate_json(raw)
                    if envelope.type == AgentMessageType.TASK_DISPATCH:
                        asyncio.create_task(self._handle_dispatch(websocket, envelope))
                    elif envelope.type == AgentMessageType.TASK_CANCEL:
                        task_id = envelope.payload["task_id"]
                        await self.runners.cancel(task_id)
                        # Unconditional ack. A cancel's postcondition — "not
                        # running here" — holds whether a live process was
                        # actually terminated or the runner never heard of
                        # the task at all (a fresh runner after a restart,
                        # replaying a durable CANCELLED write on reconnect —
                        # issue #17). The old `if cancelled:` guard left the
                        # gateway waiting for an ack a restarted runner could
                        # never send, pinning the executor's one concurrency
                        # slot for the life of the gateway process.
                        await websocket.send(
                            self._envelope(
                                AgentMessageType.TASK_CANCELLED,
                                {"task_id": task_id},
                            ).model_dump_json()
                        )
                    elif envelope.type == AgentMessageType.TASK_PAUSE:
                        task_id = envelope.payload["task_id"]
                        known = self.runners.is_known(task_id)
                        paused = await self.runners.pause(task_id)
                        await websocket.send(
                            self._envelope(
                                AgentMessageType.TASK_ACK,
                                {
                                    "task_id": task_id,
                                    "control": "pause",
                                    "accepted": paused,
                                    "state": TaskState.PAUSED.value if paused else None,
                                    "known": known,
                                },
                            ).model_dump_json()
                        )
                    elif envelope.type == AgentMessageType.TASK_RESUME:
                        task_id = envelope.payload["task_id"]
                        known = self.runners.is_known(task_id)
                        resumed = await self.runners.resume(task_id)
                        await websocket.send(
                            self._envelope(
                                AgentMessageType.TASK_ACK,
                                {
                                    "task_id": task_id,
                                    "control": "resume",
                                    "accepted": resumed,
                                    "state": TaskState.RUNNING.value if resumed else None,
                                    "known": known,
                                },
                            ).model_dump_json()
                        )
                    elif envelope.type == AgentMessageType.TASK_RESTART:
                        task_id = envelope.payload["task_id"]
                        known = self.runners.is_known(task_id)
                        restarted = await self.runners.restart(task_id)
                        await websocket.send(
                            self._envelope(
                                AgentMessageType.TASK_ACK,
                                {
                                    "task_id": task_id,
                                    "control": "restart",
                                    "accepted": restarted,
                                    "state": TaskState.RUNNING.value if restarted else None,
                                    "known": known,
                                },
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
        # WK-20260830-chatgpt-entry-provider-and-delivery: `engine` is a new,
        # optional dispatch field (`shared.protocol.AgentEngine`). Its
        # absence -- any gateway that predates this migration -- defaults to
        # "codex", which is exactly the one engine that existed before this
        # runner abstraction, so an unmodified gateway keeps dispatching
        # correctly against an upgraded executor.
        engine = envelope.payload.get("engine", "codex")
        try:
            runner = self.runners.for_engine(engine)
        except EngineNotImplementedError as exc:
            await websocket.send(
                self._envelope(
                    AgentMessageType.TASK_RESULT,
                    {
                        "task_id": task_id,
                        "final_state": TaskState.FAILED.value,
                        "error": str(exc),
                    },
                ).model_dump_json()
            )
            return
        # Known to the pool for the task's whole observable lifetime here —
        # from the moment this dispatch is accepted until its result has been
        # sent — not just while the runner's own `running` dict holds a live
        # process. `is_known` backs the gateway's `known=False` ghost-task
        # branch: a `task.pause`/`task.restart` landing before `run_task`
        # ever spawns a process, or after it exits but before this method
        # reports the result, used to read as "runner never heard of this
        # task" and got a live (or just-finished) task marked CANCELLED out
        # from under it (issue #17 council round 2, "the second caller").
        self.runners.mark_dispatched(task_id, engine)
        try:
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

            sandbox = _sandbox_for(decision.level, allow_workspace_write=self.settings.allow_workspace_write)
            try:
                result = await runner.run_task(
                    task_id=task_id,
                    project_root=Path(root),
                    instruction=f"{BASE_PROMPT}\n\nUser task:\n{envelope.payload['instruction']}",
                    timeout_seconds=int(envelope.payload["timeout_seconds"]),
                    continue_session_id=envelope.payload.get("continue_session_id"),
                    send_log=send_log,
                    sandbox=sandbox,
                )
            except Exception as exc:
                await send_log("stderr", f"Codex execution failed before completion: {exc}")
                result = {
                    "task_id": task_id,
                    "final_state": TaskState.FAILED.value,
                    "error": str(exc),
                    "return_code": -1,
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
            # WK-20260830-chatgpt-entry-provider-and-delivery, slice of #51.
            # Runs OUTSIDE the provider's own sandbox, only after a successful
            # run, and only when the dispatch itself carried a `delivery`
            # block. Today no gateway ever sets that key (issue #65 wires the
            # MCP tool that will), so this branch is currently unreachable in
            # practice -- exercised directly in
            # tests/unit/test_git_delivery.py, not yet through a real dispatch.
            delivery_payload = envelope.payload.get("delivery")
            if delivery_payload and result.get("final_state") == TaskState.COMPLETED.value:
                delivery_outcome = await deliver_changes(
                    project_root=Path(root),
                    delivery=DeliveryRequest.model_validate(delivery_payload),
                    settings=self.settings,
                    task_id=task_id,
                    issue_ref=envelope.payload.get("issue_ref"),
                    engine=engine,
                    send_log=send_log,
                )
                result["delivery"] = delivery_outcome.to_dict()
            await websocket.send(self._envelope(AgentMessageType.TASK_RESULT, result).model_dump_json())
        finally:
            self.runners.forget(task_id)

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
