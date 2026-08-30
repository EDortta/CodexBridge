"""ClaudeRunner against a REAL `claude` subprocess — not the fakes used elsewhere.

WK-20260830-chatgpt-entry-provider-and-delivery, issue #41a. Same posture as
`test_codex_runner_real_process.py`: `tests/unit/test_claude_runner.py`
stands entirely on pure logic (command assembly, NDJSON extraction) and never
spawns a real process. This file closes that gap for Claude Code specifically
because `runners/claude.py`'s own docstring records finding these three real
mismatches by running the actual CLI, not by reading its `--help` text:

1. `--disallowedTools` is greedy and consumes a trailing positional prompt
   argument, so the instruction MUST travel over stdin.
   `test_run_task_drives_a_real_claude_process_end_to_end` below exercises
   exactly that path — no fake anywhere, a real subprocess, real stdin write.
2. `--permission-mode plan` writes a side-effect plan file and is the wrong
   read-only mechanism for a headless run;
   `test_run_task_read_only_blocks_a_real_write_attempt` confirms the
   `bypassPermissions` + `--disallowedTools` combination this runner actually
   uses blocks a write cleanly instead.
3. The final answer is the last `result` event's `result` field, not a temp
   file. `test_run_task_drives_a_real_claude_process_end_to_end` asserts on
   it directly.

Gated behind `RUN_REAL_CLAUDE_TESTS=1` (and the `claude` binary on PATH), same
convention as `RUN_REAL_CODEX_TESTS=1`:

    RUN_REAL_CLAUDE_TESTS=1 python3 -m pytest tests/integration/test_claude_runner_real_process.py -v

Each enabled test makes at least one real call to a live model and can take
up to a minute or two.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

from agent.codex_bridge_agent.config import AgentSettings
from agent.codex_bridge_agent.runners.claude import ClaudeRunner


_REASON = (
    "real-claude tests are opt-in: set RUN_REAL_CLAUDE_TESTS=1 to spawn a real "
    "`claude` subprocess (needs the binary on PATH, an authenticated session, "
    "and network access to a live model)."
)
requires_real_claude = pytest.mark.skipif(
    os.environ.get("RUN_REAL_CLAUDE_TESTS") != "1" or shutil.which(AgentSettings().claude_bin) is None,
    reason=_REASON,
)


def _init_scratch_repo(root: Path) -> None:
    env = {**os.environ, "GIT_AUTHOR_NAME": "codexbridge-test", "GIT_AUTHOR_EMAIL": "test@example.invalid",
            "GIT_COMMITTER_NAME": "codexbridge-test", "GIT_COMMITTER_EMAIL": "test@example.invalid"}
    subprocess.run(["git", "init", "-q"], cwd=root, check=True, env=env)
    (root / "README.md").write_text("Scratch fixture repo for a real claude_runner test.\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=root, check=True, env=env)
    subprocess.run(["git", "commit", "-q", "-m", "initial commit"], cwd=root, check=True, env=env)


async def _collect_logs(name: str, text: str) -> None:
    return None


@requires_real_claude
@pytest.mark.asyncio
async def test_run_task_drives_a_real_claude_process_end_to_end(tmp_path: Path) -> None:
    _init_scratch_repo(tmp_path)

    runner = ClaudeRunner(AgentSettings())
    result = await runner.run_task(
        task_id="real-claude-smoke-1",
        project_root=tmp_path,
        instruction="Read README.md and reply with only the word DONE. Do not edit anything.",
        timeout_seconds=90,
        continue_session_id=None,
        send_log=_collect_logs,
    )

    assert result["return_code"] == 0
    assert result["final_state"] == "completed"
    assert result["engine"] == "claude"
    assert result["raw_events"], "expected at least one parsed JSON event from a real claude run"
    assert result["provider_run_ref"], "a fresh run must capture a session id"
    assert "DONE" in result["last_message"]
    assert isinstance(result["cost_usd"], float)


@requires_real_claude
@pytest.mark.asyncio
async def test_run_task_read_only_blocks_a_real_write_attempt(tmp_path: Path) -> None:
    """Finding 2's real-world consequence, proven rather than assumed: the

    read-only denylist actually stops a real `claude` process from writing a
    new file, with a clean is_error-free refusal and no side-effect artifact
    (unlike `--permission-mode plan`, which this runner deliberately does not
    use for read-only — see `runners/claude.py`'s module docstring).
    """
    _init_scratch_repo(tmp_path)

    runner = ClaudeRunner(AgentSettings())
    result = await runner.run_task(
        task_id="real-claude-readonly-smoke-1",
        project_root=tmp_path,
        instruction="Create a new file called should-not-exist.txt containing the text 'nope', using the Write tool.",
        timeout_seconds=90,
        continue_session_id=None,
        send_log=_collect_logs,
        sandbox="read-only",
    )

    assert result["return_code"] == 0
    assert result["final_state"] == "completed"
    assert not (tmp_path / "should-not-exist.txt").exists()
    assert result["no_changes"] is True


@requires_real_claude
@pytest.mark.asyncio
async def test_run_task_actually_writes_when_dispatched_with_workspace_write_sandbox(tmp_path: Path) -> None:
    _init_scratch_repo(tmp_path)
    before = (tmp_path / "README.md").read_text(encoding="utf-8")

    runner = ClaudeRunner(AgentSettings())
    result = await runner.run_task(
        task_id="real-claude-workspace-write-smoke-1",
        project_root=tmp_path,
        instruction=(
            "Add a one-line HTML comment at the very top of README.md that says "
            "'reviewed by claude'. Do not change anything else. Then stop."
        ),
        timeout_seconds=90,
        continue_session_id=None,
        send_log=_collect_logs,
        sandbox="workspace-write",
    )

    assert result["return_code"] == 0
    assert result["final_state"] == "completed"
    after = (tmp_path / "README.md").read_text(encoding="utf-8")
    assert after != before
    assert result["no_changes"] is False


@requires_real_claude
@pytest.mark.asyncio
async def test_run_task_resume_actually_continues_the_real_session(tmp_path: Path) -> None:
    _init_scratch_repo(tmp_path)
    runner = ClaudeRunner(AgentSettings())

    first = await runner.run_task(
        task_id="real-claude-resume-smoke-first",
        project_root=tmp_path,
        instruction="Remember the secret word PINEAPPLE. Reply with only the word OK.",
        timeout_seconds=60,
        continue_session_id=None,
        send_log=_collect_logs,
    )
    assert first["return_code"] == 0
    session_id = first["provider_run_ref"]
    assert session_id, "first run must capture a resumable session id before resume can be tested"

    second = await runner.run_task(
        task_id="real-claude-resume-smoke-second",
        project_root=tmp_path,
        instruction="What was the secret word I told you earlier? Reply with only that word.",
        timeout_seconds=60,
        continue_session_id=session_id,
        send_log=_collect_logs,
    )

    assert second["return_code"] == 0
    assert second["final_state"] == "completed"
    assert second["provider_run_ref"] == session_id, "--resume must continue the SAME session id"
    assert "PINEAPPLE" in second["last_message"].upper()
    assert "--resume" in second["command"]
    assert "--session-id" not in second["command"]
