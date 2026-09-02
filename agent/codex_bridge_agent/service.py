from __future__ import annotations

import asyncio
import logging
import platform
import random
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlencode
from uuid import uuid4

import websockets

from agent.codex_bridge_agent.config import AgentSettings, load_agent_projects, resolve_auto_project
from agent.codex_bridge_agent.git_delivery import deliver_changes
from agent.codex_bridge_agent.instructions import IssueResolutionError, build_task_instruction, resolve_issue_text
from agent.codex_bridge_agent.issue_materialize import MaterializeError, materialize_epic
from agent.codex_bridge_agent.runners.base import EngineNotImplementedError
from agent.codex_bridge_agent.runners.codex import SANDBOX_READ_ONLY, SANDBOX_WORKSPACE_WRITE
from agent.codex_bridge_agent.runners.pool import RunnerPool
from shared.policy import evaluate_task_policy
from shared.protocol import (
    EXECUTOR_TOKEN_HEADER,
    AgentEnvelope,
    AgentMessageType,
    Capability,
    DeliveryRequest,
    NodeAnnouncement,
    MaterializeRequest,
    PolicyLevel,
    SubmitTaskRequest,
    TaskMode,
    TaskPriority,
    TaskState,
)
from shared.security import ensure_within_root


logger = logging.getLogger(__name__)

# Sent as `NodeAnnouncement.agent_version` (the `hello` payload) -- the same
# literal `_run_once` always sent before issue #73 Stage 2, now single-sourced
# here rather than inlined at the send site. No dependency on the gateway
# package is introduced to get this value: it stays a plain constant local to
# the agent, exactly as it always was.
AGENT_VERSION = "0.1.0"


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
        # `additional_headers` -- confirmed live against the installed
        # `websockets` 16.1.1 (2026-08-30). The older `extra_headers` kwarg
        # this line used to pass is accepted by `connect()`'s own signature
        # (absorbed into `**kwargs`) but is no longer a real parameter
        # anywhere in the chain beneath it; it reaches asyncio's raw
        # `loop.create_connection(factory, **kwargs)` unconsumed and raises
        # `TypeError: got an unexpected keyword argument 'extra_headers'` on
        # every single connection attempt. `run_forever`'s own bare
        # `except Exception` (below) caught and silently retried that
        # TypeError forever, so the executor looked "active (running)"
        # under systemd for 16 days while never once successfully
        # connecting to the gateway (`executors.last_seen_at` stuck at
        # 2026-08-14 in the gateway's own database, discovered live while
        # verifying this session's delivery). No test in this suite ever
        # caught it because every existing test replaces
        # `websockets.connect` with a fake before this line runs.
        async with websockets.connect(url, max_size=2_000_000, additional_headers=headers) as websocket:
            announcement = await self._build_announcement()
            await websocket.send(
                self._envelope(AgentMessageType.HELLO, announcement.model_dump(mode="json")).model_dump_json()
            )
            heartbeat_task = asyncio.create_task(self._heartbeat_loop(websocket))
            try:
                async for raw in websocket:
                    envelope = AgentEnvelope.model_validate_json(raw)
                    if envelope.type == AgentMessageType.TASK_DISPATCH:
                        asyncio.create_task(self._handle_dispatch(websocket, envelope))
                    elif envelope.type == AgentMessageType.ISSUE_MATERIALIZE:
                        asyncio.create_task(self._handle_materialize(websocket, envelope))
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
            if project is None and self.settings.auto_project_root:
                # Opt-in fallback (see `AgentSettings.auto_project_root`'s own
                # docstring for the tradeoff): only reached once the static
                # allowlist has already said no.
                project = resolve_auto_project(project_id, self.settings.auto_project_root)
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
            # WK-20260830-chatgpt-entry-provider-and-delivery, issue #65: the
            # gateway never learns a project's real path
            # (`docs/architecture.md`), so `issue_ref` is resolved HERE, not
            # on the gateway. Failure is a typed error, never a traceback.
            issue_ref = envelope.payload.get("issue_ref")
            issue_text: str | None = None
            if issue_ref:
                try:
                    issue_text = resolve_issue_text(Path(root), issue_ref)
                except IssueResolutionError as exc:
                    await websocket.send(
                        self._envelope(
                            AgentMessageType.TASK_RESULT,
                            {"task_id": task_id, "final_state": TaskState.FAILED.value, "error": exc.code},
                        ).model_dump_json()
                    )
                    return
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
                    instruction=build_task_instruction(
                        base_prompt=BASE_PROMPT,
                        operator_request=envelope.payload["instruction"],
                        issue_text=issue_text,
                    ),
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

    async def _build_announcement(self) -> NodeAnnouncement:
        """Issue #73 Stage 2: the `hello` payload's real content.

        `capabilities` here is derived from this node's OWN configuration --
        what it is set up to *permit* -- never a grant. Per-project
        authorization still lives entirely server-side, in
        `project_authorizations` (see `shared/protocol.py:NodeAnnouncement`'s
        own docstring); a node claiming `MODIFY` here only means "if
        authorized, I am configured to attempt writes", not "I may write to
        anything".

        `discovery_root_count`: the agent has no local `DiscoveryRoot` list to
        count (`auto_project_root` is a single optional path, not a list --
        see `AgentSettings.auto_project_root`'s own docstring), so this
        reports 1 when that single opt-in root is set and 0 otherwise, rather
        than inventing a new setting to carry a count `AgentSettings` does not
        otherwise track.

        Never allowed to raise past this method: building the announcement
        must not cost the connection. Any exception here (a runner's `probe`
        somehow escaping `RunnerPool.probe_all`'s own `return_exceptions`
        guard, or anything else) is caught and logged, and a minimal
        announcement is returned instead -- `_run_once` always gets something
        it can send.
        """
        try:
            capabilities = [Capability.READ, Capability.TEST]
            if self.settings.allow_workspace_write:
                capabilities.append(Capability.MODIFY)
            if self.settings.allow_git_delivery:
                capabilities.append(Capability.DELIVER)
            return NodeAnnouncement(
                agent_version=AGENT_VERSION,
                os=platform.system(),
                arch=platform.machine(),
                engines=await self.runners.probe_all(),
                capabilities=capabilities,
                max_concurrent_tasks=self.settings.max_concurrent_tasks,
                # See this method's own docstring: no local list of discovery
                # roots exists to count, so the single opt-in
                # `auto_project_root` collapses to 0 or 1.
                discovery_root_count=1 if self.settings.auto_project_root else 0,
            )
        except Exception:
            logger.warning("Failed to build full node announcement; sending minimal fallback", exc_info=True)
            return NodeAnnouncement(agent_version=AGENT_VERSION)
    async def _handle_materialize(self, websocket, envelope: AgentEnvelope) -> None:
        """Writes one epic's rendered markdown to disk -- issue #78, Commit 2c.

        Mirrors `_handle_dispatch`'s own project-resolution shape (same
        `self.projects`/`auto_project_root` fallback, same
        `ensure_within_root` posture) but there is no `TaskModel` here: this
        is a fire-and-forget `ISSUE_MATERIALIZE`/`ISSUE_MATERIALIZE_RESULT`
        pair, not a queued task, so failures are reported the same way but
        nothing here ever touches `self.runners`.
        """
        payload = envelope.payload
        epic_id = payload.get("epic_id")

        async def fail(error: str) -> None:
            await websocket.send(
                self._envelope(
                    AgentMessageType.ISSUE_MATERIALIZE_RESULT,
                    {"epic_id": epic_id, "ok": False, "error": error},
                ).model_dump_json()
            )

        try:
            request = MaterializeRequest.model_validate(payload)
        except Exception:
            await fail("invalid_materialize_request")
            return

        project = self.projects.get(request.project_id)
        if project is None and self.settings.auto_project_root:
            project = resolve_auto_project(request.project_id, self.settings.auto_project_root)
        if project is None:
            await fail("unknown_project")
            return
        root = Path(ensure_within_root(project.path, project.path))

        try:
            outcome = materialize_epic(root, request)
        except MaterializeError as exc:
            await fail(exc.code)
            return

        result_payload: dict = {
            "epic_id": epic_id,
            "ok": True,
            "epic_path": outcome.epic_path,
            "epic_revision": request.epic_revision,
            "written_paths": outcome.written_paths,
            "issue_revisions": request.issue_revisions,
        }

        if request.delivery is not None:

            async def _noop_log(stream: str, line: str) -> None:
                return None

            delivery_outcome = await deliver_changes(
                project_root=root,
                delivery=request.delivery,
                settings=self.settings,
                task_id=f"materialize:{epic_id}",
                issue_ref=None,
                engine="materialize",
                send_log=_noop_log,
            )
            result_payload["delivery"] = delivery_outcome.to_dict()

        await websocket.send(
            self._envelope(AgentMessageType.ISSUE_MATERIALIZE_RESULT, result_payload).model_dump_json()
        )

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
