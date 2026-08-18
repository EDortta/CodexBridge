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
    ) -> dict:
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
                cmd = self._build_command(project_root, instruction, output_path, continue_session_id)
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
    ) -> list[str]:
        if continue_session_id:
            return [
                self.settings.codex_bin,
                "exec",
                "resume",
                continue_session_id,
                "--json",
                "-C",
                str(project_root),
                "-o",
                str(output_path),
                instruction,
            ]
        return [
            self.settings.codex_bin,
            "exec",
            "--json",
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
        for event in raw_events:
            if isinstance(event, dict):
                for key in ("session_id", "sessionId", "conversation_id", "conversationId"):
                    value = event.get(key)
                    if isinstance(value, str) and value:
                        return value
                payload = event.get("payload")
                if isinstance(payload, dict):
                    for key in ("session_id", "sessionId", "conversation_id", "conversationId"):
                        value = payload.get(key)
                        if isinstance(value, str) and value:
                            return value
        return None
