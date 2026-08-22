from __future__ import annotations

import asyncio
import json
import signal
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Awaitable, Callable

from agent.codex_bridge_agent.config import AgentSettings
from agent.codex_bridge_agent.git_tools import collect_git_snapshot
from shared.protocol import TaskState
from shared.security import filtered_environment, sanitize_log_line


LogSender = Callable[[str, str], Awaitable[None]]

# codex-cli 0.147.0's `codex exec -s/--sandbox <MODE>` (confirmed via
# `codex exec --help`, issue #34): `read-only`, `workspace-write`,
# `danger-full-access`. This runner only ever emits the first two — the third
# is a real, accepted value that this codebase must never pass regardless of
# caller input, so it is deliberately left out of the allowed set rather than
# merely undocumented.
SANDBOX_READ_ONLY = "read-only"
SANDBOX_WORKSPACE_WRITE = "workspace-write"
_ALLOWED_SANDBOX_MODES = frozenset({SANDBOX_READ_ONLY, SANDBOX_WORKSPACE_WRITE})


@dataclass
class RunningTask:
    process: asyncio.subprocess.Process
    paused: bool = False
    cancel_requested: bool = False
    restart_requested: bool = False
    continue_session_id: str | None = None
    raw_events: list[dict] = field(default_factory=list)


class CodexRunner:
    def __init__(self, settings: AgentSettings):
        self.settings = settings
        self.running: dict[str, RunningTask] = {}
        self.known_tasks: set[str] = set()

    def is_known(self, task_id: str) -> bool:
        """Whether this runner has any record of the task at all.

        The signal the gateway needs to tell "already resolved on a live
        process" apart from "this runner never heard of it" — e.g. a fresh
        runner after a restart replaying a control message for a task it
        lost all memory of (issue #17). `pause`/`resume`/`restart` returning
        `False` collapses both "unknown" and "known but wrong sub-state"
        into one boolean, which is not enough for the gateway to tell a
        ghost task (no process anywhere, revert the state is a lie) from a
        transient rejection (process is alive, revert the state is exact).

        Backed by `known_tasks`, not `self.running`. `self.running` only
        holds a task while its process is alive — empty during dispatch
        setup (before `run_task` spawns it) and during result teardown
        (after it exits, before the caller reports the result) even on a
        live executor that never restarted. A control message landing in
        either window used to read as "runner never heard of this task",
        and the gateway's ghost-task branch marked a task that was still
        running, or had just finished successfully, CANCELLED out from
        under it (issue #17 council round 2, "the second caller").
        `known_tasks` is keyed to the task's whole observable lifetime in
        the agent — see `AgentService._handle_dispatch`'s
        `mark_dispatched`/`forget` pair, which brackets it.
        """
        return task_id in self.known_tasks

    def mark_dispatched(self, task_id: str) -> None:
        self.known_tasks.add(task_id)

    def forget(self, task_id: str) -> None:
        self.known_tasks.discard(task_id)

    async def cancel(self, task_id: str) -> bool:
        item = self.running.get(task_id)
        if item is None:
            return False
        item.cancel_requested = True
        # A cancel arriving after an in-flight restart() must win: restart()
        # sets restart_requested and run_task's loop checks it before
        # cancel_requested, so a pending restart_requested left True here would
        # relaunch the process the operator just told the gateway was
        # cancelled — reported CANCELLED and slot-freed on the gateway side
        # while the executor keeps running it, unmanaged (council 2026-08-18,
        # "the second caller", reproduced live).
        item.restart_requested = False
        if item.paused:
            item.process.send_signal(signal.SIGCONT)
            item.paused = False
        item.process.terminate()
        return True

    async def pause(self, task_id: str) -> bool:
        item = self.running.get(task_id)
        if item is None or item.paused:
            return False
        item.process.send_signal(signal.SIGSTOP)
        item.paused = True
        return True

    async def resume(self, task_id: str) -> bool:
        item = self.running.get(task_id)
        if item is None or not item.paused:
            return False
        item.process.send_signal(signal.SIGCONT)
        item.paused = False
        return True

    async def restart(self, task_id: str) -> bool:
        item = self.running.get(task_id)
        if item is None:
            return False
        item.restart_requested = True
        item.cancel_requested = False
        if item.paused:
            item.process.send_signal(signal.SIGCONT)
            item.paused = False
        item.process.terminate()
        return True

    async def run_task(
        self,
        task_id: str,
        project_root: Path,
        instruction: str,
        timeout_seconds: int,
        continue_session_id: str | None,
        send_log: LogSender,
        sandbox: str = SANDBOX_READ_ONLY,
    ) -> dict:
        """Issue #34: `sandbox` is now always explicit, never implicit.

        Before this, `_build_command` passed no `-s`/`--sandbox` at all, so
        whether a task could actually write depended on whether the executor
        host's `~/.codex/config.toml` already marked `project_root`
        `trust_level = "trusted"` — invisible here, and untouched by anything
        `codex_runner.py` itself does. A freshly-registered project ran fully
        read-only: exit 0, `TaskState.COMPLETED`, `no_changes: true`, no error
        anywhere (confirmed live against codex-cli 0.147.0,
        `docs/napkin-lessons.md` 2026-08-21).

        The default here (`read-only`) is deliberately the *safe* one — a
        caller that does not think about sandboxing at all gets the
        restrictive behavior, not the permissive one. `AgentService._handle_dispatch`
        is the only caller in this codebase and always passes an explicit
        value derived from the task's policy level
        (`shared.policy.policy_level_for_mode`), so this default is what a
        test or a future caller gets for saying nothing — never what a real
        dispatched task gets by omission.
        """
        if sandbox not in _ALLOWED_SANDBOX_MODES:
            raise ValueError(
                f"sandbox must be one of {sorted(_ALLOWED_SANDBOX_MODES)}, got {sandbox!r} "
                "(danger-full-access is a real codex-cli value this runner refuses to pass)"
            )
        pre = await collect_git_snapshot(project_root, self.settings.max_diff_chars)
        start = time.monotonic()
        deadline = start + timeout_seconds
        started_at = datetime.now(timezone.utc).isoformat()
        allowed_env = filtered_environment({"HOME", "PATH", "LANG", "LC_ALL", "CODEX_HOME", "OPENAI_API_KEY"})
        offset = 0
        item: RunningTask | None = None
        cmd: list[str] = []
        output_path = Path("")

        async def pump(stream: asyncio.StreamReader | None, name: str) -> None:
            nonlocal offset, item
            if stream is None or item is None:
                return
            while True:
                line = await stream.readline()
                if not line:
                    break
                raw_text = line.decode("utf-8", errors="replace").rstrip()
                if name == "stdout":
                    try:
                        item.raw_events.append(json.loads(raw_text))
                    except json.JSONDecodeError:
                        pass
                text = sanitize_log_line(raw_text)
                await send_log(name, text)
                offset += 1

        try:
            while True:
                remaining = max(1, int(deadline - time.monotonic()))
                with NamedTemporaryFile(prefix="codex-last-message-", suffix=".txt", delete=False) as handle:
                    output_path = Path(handle.name)
                cmd = self._build_command(project_root, instruction, output_path, continue_session_id, sandbox)
                process = await asyncio.create_subprocess_exec(
                    *cmd,
                    cwd=str(project_root),
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    env=allowed_env,
                )
                if item is None:
                    item = RunningTask(process=process, continue_session_id=continue_session_id)
                else:
                    item.process = process
                    item.paused = False
                self.running[task_id] = item
                try:
                    await asyncio.wait_for(
                        asyncio.gather(pump(process.stdout, "stdout"), pump(process.stderr, "stderr")),
                        timeout=remaining,
                    )
                    returncode = await asyncio.wait_for(process.wait(), timeout=5)
                except asyncio.TimeoutError:
                    await self._terminate_gracefully(item, process)
                    item.cancel_requested = True
                    returncode = 124
                    await send_log("stderr", "Task exceeded timeout and was terminated.")
                session_id = self._find_session_id(item.raw_events) or item.continue_session_id
                item.continue_session_id = session_id
                if item.restart_requested:
                    item.restart_requested = False
                    await send_log("stderr", "Task restart requested; relaunching the Codex process.")
                    continue_session_id = item.continue_session_id
                    continue
                final_state = TaskState.CANCELLED if item.cancel_requested else (TaskState.COMPLETED if returncode == 0 else TaskState.FAILED)
                break
        finally:
            self.running.pop(task_id, None)
        duration = round(time.monotonic() - start, 3)
        post = await collect_git_snapshot(project_root, self.settings.max_diff_chars)
        session_id = item.continue_session_id if item is not None else continue_session_id
        if output_path.exists():
            last_message = output_path.read_text(encoding="utf-8", errors="replace")[: self.settings.max_result_chars]
        else:
            last_message = ""
        return {
            "task_id": task_id,
            "final_state": final_state.value,
            "return_code": returncode,
            "duration_seconds": duration,
            "command": cmd,
            "command_redacted": cmd,
            "codex_session_id": session_id,
            "codex_version": await self._codex_version(),
            "started_at": started_at,
            "last_message": last_message,
            "pre_git": pre,
            "post_git": post,
            "tests_ran": self._guess_tests(last_message),
            "no_changes": pre["diff"] == post["diff"] and pre["modified_files"] == post["modified_files"],
            "raw_events": item.raw_events if item is not None else [],
        }

    async def _terminate_gracefully(
        self, item: RunningTask, process: asyncio.subprocess.Process
    ) -> None:
        """Ends `process`, resuming it first if it is paused.

        A SIGSTOP'd process never processes a pending SIGTERM while it stays
        stopped. `cancel()` and `restart()` both resume before terminating;
        `run_task`'s timeout branch used to be the third caller of
        `terminate()` on a possibly-paused process and was missing the same
        guard, which left the child leaked in the stopped state forever —
        reported to the gateway as cancelled while still alive on the
        executor host (council 2026-08-18, "the second caller" / "the
        adversarial user"). A `kill()` fallback covers a `terminate()` that
        does not take effect for some other reason.
        """
        if item.paused:
            process.send_signal(signal.SIGCONT)
            item.paused = False
        process.terminate()
        try:
            await asyncio.wait_for(process.wait(), timeout=5)
        except asyncio.TimeoutError:
            process.kill()
            await process.wait()

    def _build_command(
        self,
        project_root: Path,
        instruction: str,
        output_path: Path,
        continue_session_id: str | None,
        sandbox: str,
    ) -> list[str]:
        if continue_session_id:
            # `codex exec resume` (unlike `codex exec`) has no `-C`/`--cd` flag at
            # all — confirmed via `codex exec resume --help` against the real CLI
            # (issue #33); passing it makes clap reject the whole command with exit
            # code 2 before anything runs. `resume` instead scopes/finds sessions by
            # the process's actual cwd (see its `--all` flag: "Show all sessions
            # (disables cwd filtering)"), which `run_task` already sets via
            # `create_subprocess_exec(..., cwd=str(project_root))` below — so the
            # project directory still reaches it, just not as a flag.
            #
            # Same check for `-s`/`--sandbox` (issue #34): `codex exec resume
            # --help` lists no such option either — confirmed against codex-cli
            # 0.147.0, the same version issue #33 was confirmed against. `sandbox`
            # is accepted here (not ignored) so a caller does not have to special-
            # case resume, but it deliberately does not reach the command; a
            # resumed session's sandbox is whatever the original `codex exec`
            # call that created it established, which this codebase does not
            # currently have a verified way to override after the fact.
            return [
                self.settings.codex_bin,
                "exec",
                "resume",
                continue_session_id,
                "--json",
                "-o",
                str(output_path),
                instruction,
            ]
        return [
            self.settings.codex_bin,
            "exec",
            "--json",
            "-s",
            sandbox,
            "-C",
            str(project_root),
            "-o",
            str(output_path),
            instruction,
        ]

    async def _codex_version(self) -> str:
        process = await asyncio.create_subprocess_exec(
            self.settings.codex_bin,
            "--version",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await process.communicate()
        return stdout.decode("utf-8", errors="replace").strip()

    def _guess_tests(self, text: str) -> list[str]:
        tests = []
        for line in text.splitlines():
            lowered = line.lower()
            if "pytest" in lowered or "test" in lowered:
                tests.append(line[:300])
        return tests[:50]

    def _find_session_id(self, raw_events: list[dict]) -> str | None:
        """Looks for the resumable session id across every JSON event shape we know of.

        `thread_id` is the real one: codex-cli 0.147.0's `codex exec --json` opens
        every stream with `{"type": "thread.started", "thread_id": "<uuid>"}`
        (issue #32, confirmed by driving the real CLI in
        `tests/integration/test_codex_runner_real_process.py`). The other four keys
        (`session_id`/`sessionId`/`conversation_id`/`conversationId`) were never
        observed against a real CLI version — they predate the real-process test and
        are kept as defensive fallbacks in case an older/newer `codex` build, or a
        differently-configured one, emits one of those shapes instead. `thread_id` is
        checked first since it is the one shape known to actually occur.
        """
        keys = ("thread_id", "session_id", "sessionId", "conversation_id", "conversationId")
        for event in raw_events:
            if isinstance(event, dict):
                for key in keys:
                    value = event.get(key)
                    if isinstance(value, str) and value:
                        return value
                payload = event.get("payload")
                if isinstance(payload, dict):
                    for key in keys:
                        value = payload.get(key)
                        if isinstance(value, str) and value:
                            return value
        return None
