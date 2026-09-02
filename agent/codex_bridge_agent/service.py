from __future__ import annotations

import asyncio
import logging
import random
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlencode
from uuid import uuid4

import websockets
from pydantic import ValidationError

from agent.codex_bridge_agent.config import AgentSettings, load_agent_projects, resolve_auto_project
from agent.codex_bridge_agent.forge.base import ForgeOutcome
from agent.codex_bridge_agent.forge.github import run_forge_operation
from agent.codex_bridge_agent.git_delivery import deliver_changes
from agent.codex_bridge_agent.instructions import IssueResolutionError, build_task_instruction, resolve_issue_text
from agent.codex_bridge_agent.runners.base import EngineNotImplementedError
from agent.codex_bridge_agent.runners.codex import SANDBOX_READ_ONLY, SANDBOX_WORKSPACE_WRITE
from agent.codex_bridge_agent.runners.pool import RunnerPool
from shared.policy import evaluate_task_policy
from shared.protocol import (
    EXECUTOR_TOKEN_HEADER,
    AgentEnvelope,
    AgentMessageType,
    DeliveryRequest,
    ForgeOperationRequest,
    PolicyLevel,
    SubmitTaskRequest,
    TaskMode,
    TaskPriority,
    TaskState,
)
from shared.security import ensure_within_root


logger = logging.getLogger(__name__)


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
            await websocket.send(self._envelope(AgentMessageType.HELLO, {"version": "0.1.0"}).model_dump_json())
            heartbeat_task = asyncio.create_task(self._heartbeat_loop(websocket))
            try:
                async for raw in websocket:
                    envelope = AgentEnvelope.model_validate_json(raw)
                    if envelope.type == AgentMessageType.TASK_DISPATCH:
                        asyncio.create_task(self._handle_dispatch(websocket, envelope))
                    elif envelope.type == AgentMessageType.FORGE_OPERATION:
                        asyncio.create_task(self._handle_forge_operation(websocket, envelope))
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

    async def _handle_forge_operation(self, websocket, envelope: AgentEnvelope) -> None:
        """Runs one `FORGE_OPERATION` envelope and reports a

        `FORGE_OPERATION_RESULT`. Parallel to `_handle_dispatch` above --
        same envelope-in/envelope-out shape, same local-allowlist project
        resolution, same typed-error-never-traceback posture -- and
        deliberately UNLIKE it in the one place that matters most:
        `_handle_dispatch` re-derives `evaluate_task_policy` from the
        envelope and refuses a SENSITIVE task that reads unapproved, as a
        second opinion against a compromised or buggy gateway. This handler
        does NOT re-derive `shared.policy.forge_operation_policy_level` the
        same way, because that function has no bypass field for any write
        kind, by design (see its own docstring in `shared/policy.py`) --
        re-deriving it here would refuse every forge write unconditionally
        regardless of any human decision the gateway already recorded, which
        would not defend the gate, it would delete the feature. The gate for
        a forge write lives entirely on the gateway side
        (`gateway/app/services/store.py`'s `create_forge_operation`/
        `decide_forge_operation`, and `AgentHub.dispatch_forge_operation`,
        which never sends this envelope for a row that is not `approved`);
        this executor trusts that decision, the same way
        `agent.codex_bridge_agent.forge.github.run_forge_operation`'s own
        module docstring says it does. What this handler still defends,
        independently of anything the gateway claims: which project this
        executor is willing to touch at all (the exact same local allowlist
        `_handle_dispatch` resolves against -- reused, not reinvented), and
        the machine-level `allow_forge_operations` kill switch plus the
        field-level revalidation `run_forge_operation` itself performs
        (`_revalidate_locally` in `forge/github.py`) -- both independent of
        whatever the gateway believes it approved.
        """
        operation_id = envelope.payload.get("operation_id")
        project_id = envelope.payload.get("project_id")

        async def send_result(outcome: ForgeOutcome) -> None:
            await websocket.send(
                self._envelope(
                    AgentMessageType.FORGE_OPERATION_RESULT,
                    {"operation_id": operation_id, **outcome.to_dict()},
                ).model_dump_json()
            )

        raw_kind = envelope.payload.get("kind")
        raw_repo_identity = envelope.payload.get("repo_identity")
        try:
            operation = ForgeOperationRequest(
                kind=raw_kind,
                repo_identity=raw_repo_identity,
                title=envelope.payload.get("title"),
                body=envelope.payload.get("body"),
                issue_number=envelope.payload.get("issue_number"),
                state=envelope.payload.get("state"),
            )
        except ValidationError as exc:
            # Never reached `forge.github.run_forge_operation` at all -- a
            # malformed envelope from a buggy or compromised gateway, not a
            # forge operation this executor ever tried. `attempted=False`
            # marks that distinction; every refusal `run_forge_operation`
            # itself can produce sets `attempted=True` (it was invoked, even
            # when it refuses immediately -- see `forge/github.py::_refused`).
            await send_result(
                ForgeOutcome(
                    attempted=False,
                    outcome="refused",
                    reason="invalid_forge_operation_payload",
                    kind=raw_kind if isinstance(raw_kind, str) else None,
                    repo_identity=raw_repo_identity if isinstance(raw_repo_identity, str) else None,
                )
            )
            return

        # Same allowlist resolution `_handle_dispatch` uses above: a forge
        # operation only ever runs against a project THIS executor is
        # configured to operate, static allowlist first and the opt-in
        # `auto_project_root` fallback second. Reused rather than
        # reimplemented so the two paths cannot drift on what "this
        # executor's project" means.
        project = self.projects.get(project_id)
        if project is None and self.settings.auto_project_root:
            project = resolve_auto_project(project_id, self.settings.auto_project_root)
        if project is None:
            await send_result(
                ForgeOutcome(
                    attempted=False,
                    outcome="refused",
                    reason="unknown_project",
                    kind=operation.kind.value,
                    repo_identity=operation.repo_identity,
                )
            )
            return
        root = ensure_within_root(project.path, project.path)

        async def send_log(stream: str, line: str) -> None:
            # No `TASK_LOG` stream for a forge operation: `task_logs.task_id`
            # is a real foreign key against `tasks` on Postgres, and
            # `operation_id` names a `forge_operations` row, never a `tasks`
            # one -- sending it as a `task_id` would either violate that
            # constraint or silently attach a forge operation's diagnostic
            # line to an unrelated task. `run_forge_operation`'s gh-argv
            # diagnostic already reaches the operator through
            # `ForgeOutcome.stdout`/`stderr` on the final result; this is
            # local-only, for an operator tailing the executor's own log.
            logger.debug("forge.log[%s] %s: %s", operation_id, stream, line)

        try:
            outcome = await run_forge_operation(
                project_root=Path(root),
                operation=operation,
                settings=self.settings,
                task_id=None,
                send_log=send_log,
            )
        except Exception as exc:
            # Typed result, never a bare traceback across the wire -- same
            # posture `_handle_dispatch` takes toward `runner.run_task`
            # above.
            outcome = ForgeOutcome(
                attempted=True,
                outcome="refused",
                reason=f"forge_operation_failed:{exc}",
                kind=operation.kind.value,
                repo_identity=operation.repo_identity,
            )
        await send_result(outcome)

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
