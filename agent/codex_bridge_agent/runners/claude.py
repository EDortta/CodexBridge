"""Claude Code as a second `Runner`, issue #41a.

Every behavioral claim below was verified live against the `claude` CLI
installed on this host (`claude --version` => 2.1.251) on 2026-08-30, in a
throwaway scratch repo -- never assumed, following the lesson issues #32/#33
already taught this codebase about `codex_runner.py`'s own `_find_session_id`
("verify with the real CLI before merge, not just the docs").

Findings that shaped this file, in order of how much they changed the design:

1. `--disallowedTools` is a greedy, nargs-consuming flag. Passing the
   instruction as a trailing positional argument alongside it makes the CLI
   swallow the instruction into the tool list and fail with "Input must be
   provided either through stdin or as a prompt argument" -- confirmed live.
   The instruction MUST travel over stdin whenever `--disallowedTools` is
   also present. This is exactly the shape
   `job-outreach/scripts/cron-research-new-leads.sh` already uses
   (`claude -p "$(cat "$PROMPT_TEMPLATE")" --disallowedTools "${DISALLOWED[@]}"`
   -- prompt as a single pre-built string, denylist last), not a coincidence.

2. `--permission-mode plan` is the wrong tool for a headless read-only run:
   confirmed live, it silently writes a *plan file* under `~/.claude/plans/`
   as a side effect (planning-mode UX bleeding into a non-interactive
   subprocess) and returns confusing "ExitPlanMode is disabled" text instead
   of a clean refusal. `--permission-mode bypassPermissions` combined with an
   explicit `--disallowedTools` denylist is the pattern this codebase already
   trusts (`codexbridge-autopilot/lib/common.sh`'s own `ap_run_agent`, and
   `job-outreach`'s cron script) and, confirmed live, blocks a `Write` attempt
   cleanly: `is_error: false`, no file written, no side artifact, no scratch
   plan file.

3. `--output-format stream-json --verbose` (no positional prompt, instruction
   via stdin) emits NDJSON exactly like `codex exec --json`: the run's own
   `pump()` loop in this file is line-for-line what `CodexRunner.run_task`
   already uses. Confirmed live event shapes:
   - `{"type":"system","subtype":"init","session_id":"<uuid>",...}` -- always
     the session id, whether freshly generated or supplied via `--session-id`.
   - `{"type":"result","subtype":"success","session_id":"<uuid>",
      "total_cost_usd":<float>,"is_error":<bool>,"result":"<final text>",...}`
     -- the LAST line. `result["result"]` is the final answer text -- this
     replaces Codex's `-o <tempfile>` trick entirely; nothing is written to
     disk to recover the last message.

4. `--session-id <uuid>` ASSIGNS a session id for a fresh run rather than
   scraping one out afterwards -- confirmed live: the assigned uuid comes
   back unchanged in both the `init` and `result` events. This runner still
   also reads `session_id` out of the `init` event (never assumes the CLI
   accepted the one it was given) for defense in depth, the same posture
   `CodexRunner._find_session_id` takes toward `thread_id`.

5. `--resume <session_id>` (no `--session-id`) continues the SAME session id
   and the model correctly recalls prior turns -- confirmed live.
"""

from __future__ import annotations

import asyncio
import json
import shutil
import signal
import time
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from agent.codex_bridge_agent.config import AgentSettings
from agent.codex_bridge_agent.git_tools import collect_git_snapshot
from agent.codex_bridge_agent.runners.base import EngineProbe, LogSender, RunnerCapabilities, RunningTask
from shared.protocol import AgentEngine, TaskState
from shared.security import filtered_environment, sanitize_log_line

# Issue #73 Stage 2, same rationale as `runners/codex.py`'s own constant of
# this name: bounds how long `probe()` waits for `<bin> --version`.
_PROBE_TIMEOUT_SECONDS = 5


SANDBOX_READ_ONLY = "read-only"
SANDBOX_WORKSPACE_WRITE = "workspace-write"
_ALLOWED_SANDBOX_MODES = frozenset({SANDBOX_READ_ONLY, SANDBOX_WORKSPACE_WRITE})

# WK-20260830-chatgpt-entry-provider-and-delivery, council finding F08: this
# set must never be unioned with `runners.codex.CODEX_ENV_ALLOWLIST`'s
# engine-specific member (`OPENAI_API_KEY`, `CODEX_HOME`) -- a Codex
# credential must never reach a Claude subprocess and vice versa. Checked by
# `tests/unit/test_runner_registry.py::test_no_registered_engines_env_allowlist_overlaps_another`.
CLAUDE_ENV_ALLOWLIST = frozenset({"HOME", "PATH", "LANG", "LC_ALL", "CLAUDE_CONFIG_DIR", "ANTHROPIC_API_KEY"})

# There is no OS-level sandbox for Claude Code (`RunnerCapabilities.
# sandbox_enforced_by == "provider-flags"`, never claimed as "os-sandbox").
# Containment is this deterministic denylist -- not just an instruction in
# the prompt -- the same posture `job-outreach/scripts/cron-research-new-leads.sh`
# already documents: "This is a deterministic backstop, not just an
# instruction (prompt-only reliability is not trustworthy for this codebase)."
#
# Read-only: no write-capable tool and no shell at all. This is stricter than
# Codex's own `-s read-only` (which still permits read-only shell commands
# such as `git status`) -- deliberately so, given `sandbox_enforced_by`
# already admits this containment is a denylist, not a kernel-level sandbox.
_READ_ONLY_DISALLOWED_TOOLS = ("Edit", "Write", "NotebookEdit", "Bash")

# Workspace-write: edits and shell are allowed (a task needs to run tests),
# but git's own mutating/network-reaching subcommands are denied even here.
# Commit and push are never the agent's own initiative -- they are a separate
# step the EXECUTOR runs outside this sandbox entirely
# (`agent/codex_bridge_agent/git_delivery.py`, issue TBD/#51 slice) and only
# when the request's own `delivery.allow_push` pre-authorized it. Everything
# else here mirrors the ecosystem's existing denylist precedent almost
# verbatim (`job-outreach/scripts/cron-research-new-leads.sh`'s own
# `DISALLOWED` array).
_WORKSPACE_WRITE_DISALLOWED_TOOLS = (
    "Bash(git push*)",
    "Bash(git commit*)",
    "Bash(git merge*)",
    "Bash(git reset --hard*)",
    "Bash(git worktree*)",
    "Bash(ssh*)",
    "Bash(docker*)",
    "Bash(sudo*)",
    "Bash(*deploy*)",
    "Bash(rm -rf*)",
)


def _disallowed_tools_for(sandbox: str) -> tuple[str, ...]:
    if sandbox == SANDBOX_READ_ONLY:
        return _READ_ONLY_DISALLOWED_TOOLS
    return _WORKSPACE_WRITE_DISALLOWED_TOOLS


class ClaudeRunner:
    """Mirrors `runners.codex.CodexRunner`'s public surface method for method

    (`is_known`/`mark_dispatched`/`forget`/`cancel`/`pause`/`resume`/
    `restart`/`run_task`) -- see that class and `runners/base.py:Runner` for
    what each one means and why. Everything engine-specific lives in
    `_build_command` and in how `run_task` extracts the session id and the
    final message from the NDJSON stream instead of a temp file.
    """

    def __init__(self, settings: AgentSettings):
        self.settings = settings
        self.running: dict[str, RunningTask] = {}
        self.known_tasks: set[str] = set()

    def capabilities(self) -> RunnerCapabilities:
        return RunnerCapabilities(
            engine=AgentEngine.CLAUDE.value,
            supports_resume=True,
            resume_token_kind="claude-session-id",
            supports_sandbox=True,
            sandbox_modes=_ALLOWED_SANDBOX_MODES,
            # The honest field (see this module's docstring, finding 2): no
            # kernel/OS enforcement exists for Claude Code the way `codex exec
            # -s` has one. Containment here is `--disallowedTools`, assembled
            # by this runner -- a real difference a caller must not paper over.
            sandbox_enforced_by="provider-flags",
            supports_pause=True,
            supports_restart=True,
            streams_events=True,
            reports_cost=True,
            cost_class="subscription",
            env_allowlist=CLAUDE_ENV_ALLOWLIST,
        )

    async def probe(self) -> EngineProbe:
        """Issue #73 Stage 2: is `self.settings.claude_bin` actually here, right now.

        Mirrors `runners.codex.CodexRunner.probe` -- see that method's
        docstring for why this never raises and why `detail` never carries a
        filesystem path.
        """
        try:
            resolved = shutil.which(self.settings.claude_bin)
            if resolved is None:
                return EngineProbe(available=False, detail="not found on PATH")
            process = await asyncio.create_subprocess_exec(
                self.settings.claude_bin,
                "--version",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            try:
                stdout, _ = await asyncio.wait_for(process.communicate(), timeout=_PROBE_TIMEOUT_SECONDS)
            except asyncio.TimeoutError:
                process.kill()
                await process.wait()
                return EngineProbe(available=False, detail="probe timed out")
            first_line = stdout.decode("utf-8", errors="replace").splitlines()[0] if stdout else ""
            return EngineProbe(available=True, version=first_line.strip()[:200] or None)
        except Exception:
            # Deliberately everything, not just `OSError`: see this method's
            # docstring. A probe that escapes costs the connection.
            return EngineProbe(available=False, detail="probe failed")

    def is_known(self, task_id: str) -> bool:
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
        if sandbox not in _ALLOWED_SANDBOX_MODES:
            raise ValueError(
                f"sandbox must be one of {sorted(_ALLOWED_SANDBOX_MODES)}, got {sandbox!r}"
            )
        pre = await collect_git_snapshot(project_root, self.settings.max_diff_chars)
        start = time.monotonic()
        deadline = start + timeout_seconds
        started_at = datetime.now(timezone.utc).isoformat()
        allowed_env = filtered_environment(CLAUDE_ENV_ALLOWLIST)
        offset = 0
        item: RunningTask | None = None
        cmd: list[str] = []
        # Assigned up front rather than scraped from the `init` event
        # afterwards (finding 4): removes the whole class of defect
        # `CodexRunner._find_session_id` exists to work around for Codex
        # (issues #32/#33). Reused verbatim across a restart loop iteration,
        # same as Codex's own `continue_session_id` handling.
        session_id = continue_session_id or str(uuid4())

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
                cmd = self._build_command(session_id, continue_session_id, sandbox)
                process = await asyncio.create_subprocess_exec(
                    *cmd,
                    cwd=str(project_root),
                    stdin=asyncio.subprocess.PIPE,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    env=allowed_env,
                )
                if item is None:
                    item = RunningTask(process=process, continue_session_id=session_id)
                else:
                    item.process = process
                    item.paused = False
                self.running[task_id] = item
                # Finding 1: `--disallowedTools` is greedy, so the instruction
                # travels over stdin, never as a trailing positional argument.
                assert process.stdin is not None
                process.stdin.write(instruction.encode("utf-8"))
                process.stdin.write_eof()
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
                # Finding 4, defense in depth: prefer whatever session id the
                # CLI actually reports over the one this runner assigned, the
                # same "never assume the caller's intent was honored" posture
                # `CodexRunner._find_session_id` takes toward `thread_id`.
                reported = self._find_session_id(item.raw_events)
                if reported:
                    session_id = reported
                item.continue_session_id = session_id
                if item.restart_requested:
                    item.restart_requested = False
                    await send_log("stderr", "Task restart requested; relaunching the Claude process.")
                    continue_session_id = item.continue_session_id
                    continue
                final_state = TaskState.CANCELLED if item.cancel_requested else (TaskState.COMPLETED if returncode == 0 else TaskState.FAILED)
                break
        finally:
            self.running.pop(task_id, None)
        duration = round(time.monotonic() - start, 3)
        post = await collect_git_snapshot(project_root, self.settings.max_diff_chars)
        # Finding 3: the final message is the last `result` event's `result`
        # field -- never a temp file, unlike Codex's `-o <path>`.
        last_message = self._find_result_text(item.raw_events if item is not None else [])
        cost = self._find_cost(item.raw_events if item is not None else [])
        return {
            "task_id": task_id,
            "final_state": final_state.value,
            "return_code": returncode,
            "duration_seconds": duration,
            "command": cmd,
            "command_redacted": cmd,
            # WK-20260830: the engine-neutral field `store.store_result`
            # prefers. `codex_session_id` is deliberately NOT set here --
            # only Codex's own runner writes that key, so the two engines'
            # rows never collide on a shared "which key means what" question.
            "provider_run_ref": session_id,
            "engine": AgentEngine.CLAUDE.value,
            "codex_version": "",
            "started_at": started_at,
            "last_message": last_message[: self.settings.max_result_chars],
            "pre_git": pre,
            "post_git": post,
            "tests_ran": self._guess_tests(last_message),
            "no_changes": pre["diff"] == post["diff"] and pre["modified_files"] == post["modified_files"],
            "raw_events": item.raw_events if item is not None else [],
            "cost_usd": cost,
        }

    async def _terminate_gracefully(self, item: RunningTask, process: asyncio.subprocess.Process) -> None:
        if item.paused:
            process.send_signal(signal.SIGCONT)
            item.paused = False
        process.terminate()
        try:
            await asyncio.wait_for(process.wait(), timeout=5)
        except asyncio.TimeoutError:
            process.kill()
            await process.wait()

    def _build_command(self, session_id: str, continue_session_id: str | None, sandbox: str) -> list[str]:
        """No positional prompt (finding 1: it travels over stdin instead).

        `--add-dir` is not needed: the subprocess's own `cwd` is already
        `project_root` (set by `run_task`'s `create_subprocess_exec` call),
        which is what Codex's redundant `-C project_root` accomplishes too --
        the process's actual working directory, not a flag, is what scopes
        both engines to the project.
        """
        cmd = [
            self.settings.claude_bin,
            "-p",
            "--output-format",
            "stream-json",
            "--verbose",
        ]
        if continue_session_id:
            cmd += ["--resume", continue_session_id]
        else:
            cmd += ["--session-id", session_id]
        if sandbox == SANDBOX_READ_ONLY:
            cmd += ["--permission-mode", "bypassPermissions"]
        else:
            cmd += ["--permission-mode", "acceptEdits"]
        cmd += ["--disallowedTools", *_disallowed_tools_for(sandbox)]
        return cmd

    def _guess_tests(self, text: str) -> list[str]:
        tests = []
        for line in text.splitlines():
            lowered = line.lower()
            if "pytest" in lowered or "test" in lowered:
                tests.append(line[:300])
        return tests[:50]

    def _find_session_id(self, raw_events: list[dict]) -> str | None:
        """The `init`/`result` events' `session_id` (finding 3) -- checked

        against every event this runner saw, not just the first, in case a
        future CLI version omits it from `init` but still carries it on
        `result`.
        """
        for event in raw_events:
            if not isinstance(event, dict):
                continue
            value = event.get("session_id")
            if isinstance(value, str) and value:
                return value
        return None

    def _find_result_text(self, raw_events: list[dict]) -> str:
        for event in reversed(raw_events):
            if isinstance(event, dict) and event.get("type") == "result":
                value = event.get("result")
                if isinstance(value, str):
                    return value
        return ""

    def _find_cost(self, raw_events: list[dict]) -> float | None:
        for event in reversed(raw_events):
            if isinstance(event, dict) and event.get("type") == "result":
                value = event.get("total_cost_usd")
                if isinstance(value, (int, float)):
                    return float(value)
        return None
