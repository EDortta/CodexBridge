"""CodexRunner against a REAL `codex` subprocess — not the fake used everywhere else.

`tests/unit/test_codex_runner.py` and `tests/unit/test_agent_service.py` both stand on
a "controllable stand-in for the real subprocess" (their own words). Before this file,
`grep -rln 'asyncio.create_subprocess_exec' tests/` matched nothing under `agent/`
tests — the whole pause/resume/restart/cancel state machine had been proven correct
against a fake that can never disagree with `codex_runner.py`'s assumptions about what
the real CLI does. This file closes exactly that gap by driving one real `codex exec`
(codex-cli 0.147.0) subprocess end-to-end through `CodexRunner.run_task`, against a
disposable scratch git repo (never a real project, never given a remote).

Two real, reproducible mismatches between what `codex_runner.py` assumed and what the
installed `codex` 0.147.0 binary actually does came out of writing this file — both
demonstrated live below, not inferred from reading the code. Both are now FIXED
(issues #32 and #33); the tests below assert the fixed behavior against the real CLI,
not just that the bugs exist.

1. (issue #32, fixed) `CodexRunner._find_session_id` used to look only for
   `session_id`, `sessionId`, `conversation_id` or `conversationId`, top-level or
   nested under `event["payload"]`. Real `codex exec --json` opens the stream with
   `{"type": "thread.started", "thread_id": "<uuid>"}` — a key `_find_session_id`
   never checked, so `codex_session_id` always came back `None`.
   `_find_session_id` now also checks `thread_id` (checked first, since it's the
   shape actually observed); `test_run_task_drives_a_real_codex_process_end_to_end`
   below asserts `codex_session_id` is populated from a real run.

2. (issue #33, fixed) The resume branch of `_build_command` used to build
   `[codex, exec, resume, <id>, --json, -C, <dir>, -o, <file>, instruction]`. The real
   `codex exec resume` subcommand does not accept `-C`/`--cd` at all (confirmed via
   `codex exec resume --help`); it used to reject the flag with exit code 2 before
   running anything: `error: unexpected argument '-C' found`. `_build_command` no
   longer passes `-C` in the resume branch — the project directory still reaches the
   subprocess via `cwd=` on `create_subprocess_exec`, which is how `resume` itself
   scopes sessions (see its `--all` flag: "disables cwd filtering").
   `test_run_task_resume_actually_resumes_the_real_session` below drives a real
   resume, end to end, using the session id captured from a real first run — both
   bugs had to be fixed together for that to be possible at all.

A third finding, not asserted as a hard regression here because it depends on the
executor host's local trust registry rather than on `codex_runner.py` itself:
`_build_command` never passes `-s`/`--sandbox` (or any approval override), and
`codex exec`'s default sandbox is read-only with approvals disabled in non-interactive
mode. Writes only succeed for a project directory codex has *already* marked
`trust_level = "trusted"` in `~/.codex/config.toml` on the machine running the agent.
A freshly-registered project — exactly the scratch repo this test creates — runs
fully read-only: exit 0, `TaskState.COMPLETED`, `no_changes: True`, and the model's
own last-message explaining it could not write. `test_run_task_drives_a_real_codex_process_end_to_end`
asserts the structural half of that (`no_changes is True`, the file is byte-identical
before/after) without asserting on the model's prose, which is not stable across
runs. See `docs/napkin-lessons.md` for the full writeup, including the direct
`codex exec -s workspace-write ...` run that confirms this diagnosis (a pre-trusted
or explicitly sandboxed directory does receive the edit).

Gated behind `RUN_REAL_CODEX_TESTS=1` (and the `codex` binary being on PATH) so the
default `pytest` run — and CI, which has neither the binary nor a logged-in
`~/.codex` — stays exactly as fast and hermetic as it is today. Run explicitly with:

    RUN_REAL_CODEX_TESTS=1 python3 -m pytest tests/integration/test_codex_runner_real_process.py -v

Each enabled test makes at least one real network call to a live model and can take
up to a minute or two.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

from agent.codex_bridge_agent.codex_runner import CodexRunner
from agent.codex_bridge_agent.config import AgentSettings


_REASON = (
    "real-codex tests are opt-in: set RUN_REAL_CODEX_TESTS=1 to spawn a real "
    "`codex` subprocess (needs the binary on PATH, a logged-in ~/.codex, and "
    "network access to a live model)."
)
requires_real_codex = pytest.mark.skipif(
    os.environ.get("RUN_REAL_CODEX_TESTS") != "1" or shutil.which(AgentSettings().codex_bin) is None,
    reason=_REASON,
)


def _init_scratch_repo(root: Path) -> None:
    """A disposable, throwaway git repo — never a real project, never a remote.

    Mirrors what `collect_git_snapshot`/`codex exec -C` need: an actual git
    repository with committed content, so pre/post diffing means something.
    """
    env = {**os.environ, "GIT_AUTHOR_NAME": "codexbridge-test", "GIT_AUTHOR_EMAIL": "test@example.invalid",
            "GIT_COMMITTER_NAME": "codexbridge-test", "GIT_COMMITTER_EMAIL": "test@example.invalid"}
    subprocess.run(["git", "init", "-q"], cwd=root, check=True, env=env)
    (root / "README.md").write_text("Scratch fixture repo for a real codex_runner test.\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=root, check=True, env=env)
    subprocess.run(["git", "commit", "-q", "-m", "initial commit"], cwd=root, check=True, env=env)


async def _collect_logs(name: str, text: str) -> None:
    # run_task requires an async LogSender; the real test doesn't need to inspect
    # streamed logs, only the final result, so this just satisfies the signature.
    return None


@requires_real_codex
@pytest.mark.asyncio
async def test_run_task_drives_a_real_codex_process_end_to_end(tmp_path: Path) -> None:
    """A real `codex exec --json -C <dir> -o <file> <instruction>` subprocess,
    driven entirely through `CodexRunner.run_task` — no fakes anywhere in this
    call. Confirms the parts of the contract that hold against the real CLI, and
    pins down (as executable assertions, not prose) the two parts that don't.
    """
    _init_scratch_repo(tmp_path)
    before = (tmp_path / "README.md").read_text(encoding="utf-8")

    runner = CodexRunner(AgentSettings())
    result = await runner.run_task(
        task_id="real-codex-smoke-1",
        project_root=tmp_path,
        instruction=(
            "Add a one-line HTML comment at the very top of README.md that says "
            "'reviewed by codex'. Do not change anything else in the file or "
            "repository. Then stop."
        ),
        timeout_seconds=120,
        continue_session_id=None,
        send_log=_collect_logs,
    )

    # The process really ran and really exited 0 — a real codex-cli banner, not
    # a guess about one.
    assert result["return_code"] == 0
    assert result["final_state"] == "completed"
    assert result["codex_version"].startswith("codex-cli")

    # Real JSON events were actually parsed off the real subprocess's stdout.
    assert result["raw_events"], "expected at least one parsed JSON event from a real `codex exec --json` run"
    first_event = result["raw_events"][0]
    assert first_event.get("type") == "thread.started"
    assert "thread_id" in first_event, (
        "codex-cli 0.147.0 identifies the resumable session under 'thread_id' on "
        "the thread.started event"
    )

    # Finding (1), fixed: _find_session_id now reads 'thread_id' off the real
    # thread.started event, so a real run's session id is actually captured. If
    # this assertion ever starts failing, either _find_session_id regressed or
    # codex changed its event shape again — update this test and the docstring
    # above together, don't just delete the assertion.
    assert result["codex_session_id"] == first_event["thread_id"]

    # Finding (3, structural half): the scratch repo is not pre-registered as
    # trusted anywhere, `_build_command` passes no sandbox override, and
    # codex exec's non-interactive default is read-only with approvals
    # disabled — so nothing was actually written, even though the process
    # reported success. Assert on the file content and the runner's own diff,
    # not on the model's prose (which is not byte-stable across runs).
    after = (tmp_path / "README.md").read_text(encoding="utf-8")
    assert after == before
    assert result["no_changes"] is True
    assert result["pre_git"]["diff"] == result["post_git"]["diff"] == ""


@requires_real_codex
@pytest.mark.asyncio
async def test_run_task_resume_actually_resumes_the_real_session(tmp_path: Path) -> None:
    """Finding (2), now fixed, driven through `run_task` itself end to end:
    `_build_command`'s resume branch no longer passes `-C <project_root>`, so
    `codex exec resume <id> --json -o <file> <instruction>` is what actually
    reaches the real CLI, and the real CLI accepts it.

    This needs a real session id to resume with, which needs finding (1) fixed
    too (`_find_session_id` reading `thread_id`) — so this test exercises both
    fixes together: a first real run captures a resumable `codex_session_id`,
    then a second real run resumes it and the real CLI actually accepts the
    command instead of rejecting it with exit code 2 before doing anything.
    """
    _init_scratch_repo(tmp_path)
    runner = CodexRunner(AgentSettings())

    first = await runner.run_task(
        task_id="real-codex-resume-smoke-first",
        project_root=tmp_path,
        instruction="Say the word PING and do nothing else.",
        timeout_seconds=60,
        continue_session_id=None,
        send_log=_collect_logs,
    )
    assert first["return_code"] == 0
    session_id = first["codex_session_id"]
    assert session_id, "first run must capture a resumable session id before resume can be tested"

    second = await runner.run_task(
        task_id="real-codex-resume-smoke-second",
        project_root=tmp_path,
        instruction="Say the word PONG and do nothing else.",
        timeout_seconds=60,
        continue_session_id=session_id,
        send_log=_collect_logs,
    )

    # The real CLI no longer rejects the command outright (it used to, exit code
    # 2, before this fix — see the docstring above and issue #33).
    assert second["return_code"] == 0
    assert second["final_state"] == "completed"
    assert second["command"][2] == "resume"
    assert second["command"][3] == session_id
    assert "-C" not in second["command"], (
        "codex exec resume does not accept -C/--cd; _build_command must not pass it"
    )
