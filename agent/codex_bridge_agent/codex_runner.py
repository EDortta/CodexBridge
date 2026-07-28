from __future__ import annotations

import asyncio
import json
import time
from datetime import datetime, timezone
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Awaitable, Callable

from agent.codex_bridge_agent.config import AgentSettings
from agent.codex_bridge_agent.git_tools import collect_git_snapshot
from shared.protocol import TaskState
from shared.security import filtered_environment, sanitize_log_line


LogSender = Callable[[str, str], Awaitable[None]]


class CodexRunner:
    def __init__(self, settings: AgentSettings):
        self.settings = settings
        self.running: dict[str, asyncio.subprocess.Process] = {}

    async def cancel(self, task_id: str) -> bool:
        process = self.running.get(task_id)
        if process is None:
            return False
        process.terminate()
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
        started_at = datetime.now(timezone.utc).isoformat()
        offset = 0
        raw_events: list[dict] = []
        allowed_env = filtered_environment({"HOME", "PATH", "LANG", "LC_ALL", "CODEX_HOME", "OPENAI_API_KEY"})
        with NamedTemporaryFile(prefix="codex-last-message-", suffix=".txt", delete=False) as handle:
            output_path = Path(handle.name)
        if continue_session_id:
            cmd = [
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
        else:
            cmd = [
                self.settings.codex_bin,
                "exec",
                "--json",
                "-C",
                str(project_root),
                "-o",
                str(output_path),
                instruction,
            ]
        process = await asyncio.create_subprocess_exec(
            *cmd,
            cwd=str(project_root),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=allowed_env,
        )
        self.running[task_id] = process

        async def pump(stream: asyncio.StreamReader | None, name: str) -> None:
            nonlocal offset
            if stream is None:
                return
            while True:
                line = await stream.readline()
                if not line:
                    break
                raw_text = line.decode("utf-8", errors="replace").rstrip()
                if name == "stdout":
                    try:
                        raw_events.append(json.loads(raw_text))
                    except json.JSONDecodeError:
                        pass
                text = sanitize_log_line(raw_text)
                await send_log(name, text)
                offset += 1

        try:
            await asyncio.wait_for(asyncio.gather(pump(process.stdout, "stdout"), pump(process.stderr, "stderr")), timeout=timeout_seconds)
            returncode = await asyncio.wait_for(process.wait(), timeout=5)
        except asyncio.TimeoutError:
            process.terminate()
            returncode = 124
            await send_log("stderr", "Task exceeded timeout and was terminated.")
        finally:
            self.running.pop(task_id, None)
        duration = round(time.monotonic() - start, 3)
        post = await collect_git_snapshot(project_root, self.settings.max_diff_chars)
        session_id = self._find_session_id(raw_events)
        if output_path.exists():
            last_message = output_path.read_text(encoding="utf-8", errors="replace")[: self.settings.max_result_chars]
        else:
            last_message = ""
        final_state = TaskState.COMPLETED if returncode == 0 else TaskState.FAILED
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
            "raw_events": raw_events,
        }

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
