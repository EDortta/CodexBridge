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
from pydantic import ValidationError

from agent.codex_bridge_agent.config import (
    AgentSettings,
    load_agent_projects,
    resolve_auto_project,
    resolve_machine_token,
)
from agent.codex_bridge_agent.config import AgentSettings, load_agent_projects, resolve_auto_project
from agent.codex_bridge_agent.forge.base import ForgeOutcome
from agent.codex_bridge_agent.forge.github import run_forge_operation
from agent.codex_bridge_agent.git_delivery import deliver_changes
from agent.codex_bridge_agent.git_tools import run_git
from agent.codex_bridge_agent.instructions import IssueResolutionError, build_task_instruction, resolve_issue_text
from agent.codex_bridge_agent.issue_materialize import MaterializeError, materialize_epic
from agent.codex_bridge_agent.runners.base import EngineNotImplementedError
from agent.codex_bridge_agent.runners.codex import SANDBOX_READ_ONLY, SANDBOX_WORKSPACE_WRITE
from agent.codex_bridge_agent.runners.pool import RunnerPool
from shared.policy import evaluate_task_policy
from shared.project_discovery import build_project_id_index
from shared.protocol import (
    EXECUTOR_TOKEN_HEADER,
    AgentEnvelope,
    AgentMessageType,
    Capability,
    DeliveryRequest,
    DiscoveredCandidate,
    DiscoveryReport,
    NodeAnnouncement,
    MaterializeRequest,
    ForgeOperationKind,
    ForgeOperationRequest,
    PolicyLevel,
    SubmitTaskRequest,
    TaskMode,
    TaskPriority,
    TaskState,
    capabilities_to_modes,
)
from shared.security import ensure_within_root


logger = logging.getLogger(__name__)

# Sent as `NodeAnnouncement.agent_version` (the `hello` payload) -- the same
# literal `_run_once` always sent before issue #73 Stage 2, now single-sourced
# here rather than inlined at the send site. No dependency on the gateway
# package is introduced to get this value: it stays a plain constant local to
# the agent, exactly as it always was.
AGENT_VERSION = "0.1.0"

# Issue #73 Stage 3 (`_scan_root` below). Depth cap for the discovery walk,
# same value `resolve_auto_project` already defaults to -- one number, so a
# monorepo's submodules are still found (CLAUDE.md's own "monorepo e
# submodulos" rule) without an unbounded walk on a root that turns out to be
# far larger or far deeper than an operator expected.
_DISCOVERY_MAX_DEPTH = 6

# How many repositories `_scan_root` probes with `git` at once. The walk
# itself runs in a thread executor because it is blocking filesystem I/O; the
# per-repository `git` calls below are already async subprocesses that do not
# block the event loop, but launching all of them for a root with hundreds of
# candidates (247, in the root that motivated this work) at the same instant
# would still be a burst of process spawns competing with the heartbeat and
# dispatch loops for scheduling. A modest bound smooths that out without
# meaningfully slowing an interval measured in the thousands of seconds.
_DISCOVERY_GIT_CONCURRENCY = 8

# Per-`git` invocation ceiling during a scan. Not the whole-scan budget --
# `_discovery_loop`'s own interval is that -- just a guard against one
# corrupted repository (a `.git` that exists but hangs `git` indefinitely)
# stalling the rest of a root's candidates behind it.
_DISCOVERY_GIT_TIMEOUT_SECONDS = 10.0


BASE_PROMPT = (
    "You are running inside CodexBridge on an approved workspace only. "
    "Do not access parent directories, secrets, deployment targets, or other hosts. "
    "Do not push, deploy, migrate production, or modify infrastructure unless explicitly approved."
)


def _configured_capabilities(settings: AgentSettings) -> list[Capability]:
    """The `Capability` values THIS machine's own configuration permits.

    Issue #73 Stage 4. Factored out of `_build_announcement` so its `hello`
    payload and `_handle_dispatch`'s own gate (below) compute the exact same
    thing -- the docstring of `Capability` in `shared/protocol.py` names this
    as one of the two places Stage 4 would touch. `READ`/`TEST` are always
    offered (a node that connects at all can at least be inspected and
    tested); `MODIFY` only when `allow_workspace_write` is on; `DELIVER` only
    when `allow_git_delivery` is on -- the same two machine-level kill
    switches `_sandbox_for` and `git_delivery.py` already gate on.
    """
    capabilities = [Capability.READ, Capability.TEST]
    if settings.allow_workspace_write:
        capabilities.append(Capability.MODIFY)
    if settings.allow_git_delivery:
        capabilities.append(Capability.DELIVER)
    return capabilities


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
        # Issue #76: prefers `machine_token_file` over the static field when
        # set -- see `resolve_machine_token`'s docstring.
        headers = {EXECUTOR_TOKEN_HEADER: resolve_machine_token(self.settings)}
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
            discovery_task = asyncio.create_task(self._discovery_loop(websocket))
            try:
                async for raw in websocket:
                    envelope = AgentEnvelope.model_validate_json(raw)
                    if envelope.type == AgentMessageType.TASK_DISPATCH:
                        asyncio.create_task(self._handle_dispatch(websocket, envelope))
                    elif envelope.type == AgentMessageType.ISSUE_MATERIALIZE:
                        asyncio.create_task(self._handle_materialize(websocket, envelope))
                    elif envelope.type == AgentMessageType.FORGE_OPERATION:
                        asyncio.create_task(self._handle_forge_operation(websocket, envelope))
                    elif envelope.type == AgentMessageType.TASK_CANCEL:
                        task_id = envelope.payload["task_id"]
                        # Issue #66 ARO finding F34, recorded BEFORE
                        # `self.runners.cancel(task_id)` below and
                        # unconditionally -- not gated on that call's own
                        # return value. `cancel()` only finds a live
                        # process to terminate; by the time this task's git
                        # delivery step is running (`deliver_changes`,
                        # dispatched from `_handle_dispatch` after the
                        # runner already exited) there is no process left
                        # for `cancel()` to find, and it would report
                        # `False` -- exactly as it should, since there is
                        # nothing to terminate -- while a cancel was still
                        # genuinely requested for this task. This flag is
                        # the only record of that request that survives
                        # past the process exiting; see
                        # `RunnerPool.mark_cancel_requested`'s own
                        # docstring and `deliver_changes`'s for what reads
                        # it.
                        self.runners.mark_cancel_requested(task_id)
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
                discovery_task.cancel()

    async def _heartbeat_loop(self, websocket) -> None:
        while True:
            await websocket.send(self._envelope(AgentMessageType.HEARTBEAT, {}).model_dump_json())
            await asyncio.sleep(self.settings.heartbeat_interval_seconds)

    async def _discovery_loop(self, websocket) -> None:
        """Issue #73 Stage 3: this node's own periodic filesystem scan.

        Started the same way `_heartbeat_loop` is -- its own task, alongside
        it -- and deliberately independent of it: `AgentSettings.
        discovery_scan_interval_seconds` defaults to an hour, not 15 seconds,
        because a real scan (`build_project_id_index`, walking a real
        operator root of 247 repositories) is not something to repeat on a
        heartbeat's cadence, and running it on this loop's own task means a
        slow scan can never delay a heartbeat or a dispatch either.

        A no-op when `discovery_roots` is empty (the default): no task work,
        no scan, no message -- exactly today's behaviour for every operator
        who has not opted in, the same posture `AgentSettings.
        auto_project_root` already takes.

        One `DISCOVERY_REPORT` envelope PER ROOT, sent as soon as that root's
        scan finishes rather than batched into one message for every root:
        see `DiscoveryReport`'s own docstring for why. A scan runs once
        immediately (this method's own first loop iteration, before the
        first `sleep`) so a freshly connected node does not wait a full
        interval to report what it already knows the moment it reconnects.
        """
        if not self.settings.discovery_roots:
            return
        while True:
            for root in self.settings.discovery_roots:
                report = await self._scan_root(root)
                if report is None:
                    continue
                await websocket.send(
                    self._envelope(AgentMessageType.DISCOVERY_REPORT, report.model_dump(mode="json")).model_dump_json()
                )
            await asyncio.sleep(self.settings.discovery_scan_interval_seconds)

    async def _scan_root(self, root: str) -> DiscoveryReport | None:
        """One root's worth of `DiscoveryReport`, or `None` if the scan itself failed.

        Reuses `shared.project_discovery.build_project_id_index` -- itself
        built from `walk_for_git_repos` and `suggest_project_id` -- rather
        than walking the filesystem a second, independent way: the same
        reasoning that module's own docstring gives for
        `resolve_auto_project` sharing it applies here, and it is what makes
        `resource_key` (the absolute path) and `suggested_project_id` agree
        with what `scripts/discover_projects.py` would show an operator for
        the same directory.

        The walk itself is blocking filesystem I/O, run in the default
        executor so it cannot stall the heartbeat or dispatch loops running
        on the same event loop -- the whole reason this method, and not
        `_discovery_loop` itself, is the unit that gets awaited per root.

        `root_path` on the returned report is the STRING `root` was passed
        in as, never the resolved path `build_project_id_index` computes
        internally -- see `DiscoveryReport.root_path`'s own docstring for why
        that distinction matters to the operator-side match this feeds.
        """
        loop = asyncio.get_running_loop()
        try:
            index = await loop.run_in_executor(None, build_project_id_index, Path(root), _DISCOVERY_MAX_DEPTH)
        except Exception:
            logger.warning("discovery scan failed for root %r", root, exc_info=True)
            return None

        semaphore = asyncio.Semaphore(_DISCOVERY_GIT_CONCURRENCY)

        async def _probe(project_id: str, repo_dir: Path) -> DiscoveredCandidate:
            async with semaphore:
                remote_url = await self._git_value(repo_dir, "remote", "get-url", "origin")
                head = await self._git_value(repo_dir, "rev-parse", "HEAD")
                dirty = await self._git_dirty(repo_dir)
            return DiscoveredCandidate(
                resource_key=str(repo_dir),
                suggested_project_id=project_id,
                suggested_name=repo_dir.name,
                remote_url=remote_url,
                head=head,
                dirty=dirty,
            )

        candidates = await asyncio.gather(*(_probe(project_id, path) for project_id, path in index.items()))
        return DiscoveryReport(root_path=root, candidates=list(candidates), scanned_at=datetime.now(timezone.utc))

    @staticmethod
    async def _git_value(repo_dir: Path, *args: str) -> str | None:
        """One `git` field, or `None` on any non-zero exit -- including "no such remote".

        `git remote get-url origin` exits non-zero when a repository simply
        has no `origin` configured, which is the ordinary case for plenty of
        legitimate local repositories, not a fault
        (`DiscoveredCandidate.remote_url`'s own docstring). Reusing the same
        helper for `rev-parse HEAD` treats a HEAD that cannot be read (an
        empty repository with no commits yet) the same forgiving way.
        """
        code, out, _ = await run_git(repo_dir, *args, timeout_seconds=_DISCOVERY_GIT_TIMEOUT_SECONDS)
        if code != 0:
            return None
        value = out.strip()
        return value or None

    @staticmethod
    async def _git_dirty(repo_dir: Path) -> bool | None:
        code, out, _ = await run_git(repo_dir, "status", "--porcelain", timeout_seconds=_DISCOVERY_GIT_TIMEOUT_SECONDS)
        if code != 0:
            return None
        return bool(out.strip())

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

            # WK-20260830-chatgpt-entry-provider-and-delivery, issue #65: the
            # gateway never learns a project's real path
            # (`docs/architecture.md`), so `issue_ref` is resolved HERE, not
            # on the gateway. Failure is a typed error, never a traceback.
            #
            # WK-20260902-forge-binding, issue #79/#80 (PR B4): `gh:N` is the
            # one shape `resolve_issue_text` still refuses unconditionally
            # (it is file resolution only -- see its own docstring). A bound
            # project resolves it here instead, through the same READ forge
            # path (`ForgeOperationKind.ISSUE_VIEW`) every other forge
            # operation uses, including the live `repo_identity` confirmation
            # against this workspace's real remote
            # (`forge.github._confirm_repo_identity_live`) -- never cached,
            # never skipped for a read. `forge_repo_identity` is present on
            # the envelope only when the gateway found this project bound at
            # dispatch time (`AgentHub.dispatch_next`); its absence here
            # means "not bound" and gets the exact same typed refusal `gh:N`
            # has always gotten, byte for byte.
            #
            # INVARIANT: the issue text resolved below -- from a file OR from
            # the forge -- reaches ONLY `build_task_instruction`'s
            # `issue_text` parameter, inside `--- BEGIN UNTRUSTED ISSUE
            # CONTENT ---`, a few lines down. It never reaches `request`
            # (built right after this block) or `evaluate_task_policy`, which
            # only ever sees `envelope.payload["instruction"]` -- the
            # operator's own words, assembled by the gateway BEFORE this
            # method runs. A public repository's issue is writable by anyone
            # with a GitHub account; letting its text influence policy
            # classification would let a stranger force (or dodge) a
            # sensitive-approval gate on this operator's task by choosing
            # what to write in an issue they do not control access to.
            # `tests/unit/test_agent_service.py` proves this directly for the
            # forge path, the same way it already did for `docs:NNN`.
            issue_ref = envelope.payload.get("issue_ref")
            issue_text: str | None = None
            if issue_ref and issue_ref.startswith("gh:"):
                forge_repo_identity = envelope.payload.get("forge_repo_identity")
                if forge_repo_identity is None:
                    await websocket.send(
                        self._envelope(
                            AgentMessageType.TASK_RESULT,
                            {
                                "task_id": task_id,
                                "final_state": TaskState.FAILED.value,
                                "error": "issue_source_unsupported",
                            },
                        ).model_dump_json()
                    )
                    return
                try:
                    issue_number = int(issue_ref.split(":", 1)[1])
                except ValueError:
                    await websocket.send(
                        self._envelope(
                            AgentMessageType.TASK_RESULT,
                            {"task_id": task_id, "final_state": TaskState.FAILED.value, "error": "issue_ref_invalid"},
                        ).model_dump_json()
                    )
                    return
                view_operation = ForgeOperationRequest(
                    kind=ForgeOperationKind.ISSUE_VIEW,
                    repo_identity=forge_repo_identity,
                    issue_number=issue_number,
                )
                outcome = await run_forge_operation(
                    project_root=Path(root),
                    operation=view_operation,
                    settings=self.settings,
                    task_id=task_id,
                    send_log=send_log,
                )
                if outcome.outcome != "succeeded":
                    await websocket.send(
                        self._envelope(
                            AgentMessageType.TASK_RESULT,
                            {
                                "task_id": task_id,
                                "final_state": TaskState.FAILED.value,
                                "error": outcome.reason or "forge_issue_view_failed",
                            },
                        ).model_dump_json()
                    )
                    return
                issue_text = f"Title: {outcome.issue_title or ''}\n\n{outcome.issue_body or ''}"
            elif issue_ref:
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
            # Issue #73 Stage 4: this node's OWN mirror of the gateway's
            # `effective_task_modes` gate (`gateway/app/services/store.py`),
            # not a duplicate of it. The gateway already decided the dispatch
            # was allowed against `project_authorizations`; this re-derives
            # what THIS machine's own configuration (`_configured_capabilities`
            # above -- the exact same computation `_build_announcement`
            # reported in `hello`) would permit and refuses independently when
            # the two disagree. The point is defense in depth against a
            # compromised or buggy gateway dispatching a mode this node never
            # offered to run -- the same reasoning `git_delivery.py` already
            # applies when it reconfirms the branch pattern the gateway
            # already checked, per `Capability`'s own docstring anticipating
            # Stage 4 touching two places.
            configured_modes = capabilities_to_modes(_configured_capabilities(self.settings))
            if request.mode not in configured_modes:
                await websocket.send(
                    self._envelope(
                        AgentMessageType.TASK_RESULT,
                        {
                            "task_id": task_id,
                            "final_state": TaskState.FAILED.value,
                            "error": f"capability_not_configured:{request.mode.value}",
                        },
                    ).model_dump_json()
                )
                return
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
            # `send_log` (and its `offset` counter) was defined earlier in
            # this method, before `issue_ref` resolution -- WK-20260902-
            # forge-binding, PR B4 -- so a `gh:N` resolution's own forge-argv
            # diagnostic line and this task's real log stream share ONE
            # counter, never two independently-numbered ones colliding on
            # the same `offset` values.
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
            # block. Issue #65/#66 wired the gateway side of that: the MCP
            # tool `start_development_task` (and `publish_epic_to_repo`) sets
            # `DeliveryRequest.allow_push`/`branch` from an operator's own
            # request (`gateway/app/mcp/server.py`), `store.create_task`
            # persists it as `delivery_json`, and `AgentHub.dispatch_next`
            # forwards it into this exact `payload["delivery"]` key
            # (`gateway/app/services/agent_hub.py`). So this branch IS
            # reachable in practice today, gated by this executor's own
            # `AgentSettings.allow_git_delivery` (off by default) and by
            # `PUSHABLE_BRANCH_PATTERN` re-checked inside `deliver_changes`
            # itself. Exercised through `_handle_dispatch` with a fake
            # WebSocket in `tests/unit/test_agent_service.py::
            # test_handle_dispatch_runs_delivery_when_the_payload_carries_one`
            # (and its sibling negative cases), and through `deliver_changes`
            # directly in `tests/unit/test_git_delivery.py`; there is no test
            # yet with a real socket on both ends (see `docs/security.md`,
            # "Lacunas assumidas para endurecimento").
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
                    # Issue #66 ARO finding F34: a `task.cancel` can arrive
                    # after the runner above already finished but while
                    # this step is still working (`self.runners` still
                    # considers `task_id` known -- `forget` below has not
                    # run yet). `RunnerPool.is_cancel_requested` is the
                    # durable flag `mark_cancel_requested` sets from the
                    # TASK_CANCEL branch of `_run_once`, above; passed as a
                    # callable rather than a bool so `deliver_changes` reads
                    # the live value at the moment it actually checks, not
                    # a snapshot taken before this call started.
                    is_cancelled=lambda: self.runners.is_cancel_requested(task_id),
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

        `discovery_root_count`: as of issue #73 Stage 3, `len(self.settings.
        discovery_roots)` -- the node's own scan-root list
        (`AgentSettings.discovery_roots`, this method's caller,
        `_discovery_loop`). Deliberately NOT `auto_project_root`: that path
        never produces a `DiscoveryReport` or any other message to the
        gateway -- it only widens which `project_id` values a dispatch may
        resolve to locally (`AgentSettings.auto_project_root`'s own
        docstring) -- so counting it here would answer "is this node
        configured to discover anything at all" with a number the gateway
        can never observe evidence for. Stage 2 counted it anyway, as a
        stand-in, because no real list existed yet to count; its own
        docstring said as much and predicted this replacement.

        Never allowed to raise past this method: building the announcement
        must not cost the connection. Any exception here (a runner's `probe`
        somehow escaping `RunnerPool.probe_all`'s own `return_exceptions`
        guard, or anything else) is caught and logged, and a minimal
        announcement is returned instead -- `_run_once` always gets something
        it can send.
        """
        try:
            return NodeAnnouncement(
                agent_version=AGENT_VERSION,
                os=platform.system(),
                arch=platform.machine(),
                engines=await self.runners.probe_all(),
                capabilities=_configured_capabilities(self.settings),
                max_concurrent_tasks=self.settings.max_concurrent_tasks,
                # See this method's own docstring: the node's own scan-root
                # count, not `auto_project_root` (a different valve entirely).
                discovery_root_count=len(self.settings.discovery_roots),
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
