"""ClaudeRunner's pure logic: command assembly, NDJSON extraction, sandbox mapping.

WK-20260830-chatgpt-entry-provider-and-delivery, issue #41a. Real-process
behavior (does the actual `claude` CLI honor these flags) is covered
separately and explicitly, in
tests/integration/test_claude_runner_real_process.py -- these tests are pure
and need no binary on PATH.
"""

from __future__ import annotations

from agent.codex_bridge_agent.config import AgentSettings
from agent.codex_bridge_agent.runners.claude import (
    CLAUDE_ENV_ALLOWLIST,
    SANDBOX_READ_ONLY,
    SANDBOX_WORKSPACE_WRITE,
    ClaudeRunner,
)
from agent.codex_bridge_agent.runners.base import Runner


def _runner() -> ClaudeRunner:
    return ClaudeRunner(AgentSettings(claude_bin="claude"))


def test_claude_runner_satisfies_the_runner_protocol():
    assert isinstance(_runner(), Runner)


def test_capabilities_declare_provider_flags_not_os_sandbox():
    caps = _runner().capabilities()
    assert caps.engine == "claude"
    assert caps.sandbox_enforced_by == "provider-flags"
    assert caps.supports_resume is True
    assert caps.resume_token_kind == "claude-session-id"
    assert caps.reports_cost is True
    assert caps.env_allowlist == CLAUDE_ENV_ALLOWLIST


def test_build_command_never_puts_the_instruction_in_argv():
    """The instruction travels over stdin (`run_task` writes it after spawning).

    `--disallowedTools` is a greedy nargs flag -- a trailing positional
    instruction argument gets swallowed into the tool list and the CLI
    refuses to start at all (confirmed live against the real binary). No
    build path may ever put the instruction into the command list.
    """
    runner = _runner()
    for sandbox in (SANDBOX_READ_ONLY, SANDBOX_WORKSPACE_WRITE):
        for resume in (None, "existing-session-id"):
            cmd = runner._build_command("new-session-id", resume, sandbox)
            joined = " ".join(cmd)
            assert "the instruction" not in joined
            assert cmd[0] == "claude"
            assert "-p" in cmd
            assert "--disallowedTools" in cmd


def test_build_command_assigns_a_session_id_for_a_fresh_run():
    cmd = _runner()._build_command("brand-new-uuid", None, SANDBOX_READ_ONLY)
    assert "--session-id" in cmd
    assert cmd[cmd.index("--session-id") + 1] == "brand-new-uuid"
    assert "--resume" not in cmd


def test_build_command_resumes_an_existing_session_instead_of_assigning():
    cmd = _runner()._build_command("brand-new-uuid", "old-session-id", SANDBOX_READ_ONLY)
    assert "--resume" in cmd
    assert cmd[cmd.index("--resume") + 1] == "old-session-id"
    assert "--session-id" not in cmd


def test_read_only_denies_every_write_tool_and_all_of_bash():
    cmd = _runner()._build_command("s", None, SANDBOX_READ_ONLY)
    idx = cmd.index("--disallowedTools")
    denied = cmd[idx + 1 :]
    for tool in ("Edit", "Write", "NotebookEdit", "Bash"):
        assert tool in denied
    assert ["--permission-mode", "bypassPermissions"] == cmd[cmd.index("--permission-mode") : cmd.index("--permission-mode") + 2]


def test_workspace_write_allows_edits_but_still_denies_push_and_commit():
    """Commit and push are never the agent's own initiative -- that is a

    separate step the executor runs outside this sandbox, and only when
    pre-authorized (`shared.policy.push_is_preauthorized`). Even in
    workspace-write mode, the agent process itself must never be able to
    push or commit on its own.
    """
    cmd = _runner()._build_command("s", None, SANDBOX_WORKSPACE_WRITE)
    idx = cmd.index("--disallowedTools")
    denied = cmd[idx + 1 :]
    assert "Edit" not in denied
    assert "Write" not in denied
    assert any("git push" in item for item in denied)
    assert any("git commit" in item for item in denied)
    assert ["--permission-mode", "acceptEdits"] == cmd[cmd.index("--permission-mode") : cmd.index("--permission-mode") + 2]


def test_find_session_id_reads_the_session_id_key():
    runner = _runner()
    events = [
        {"type": "system", "subtype": "init", "session_id": "abc-123"},
        {"type": "assistant", "message": {}},
    ]
    assert runner._find_session_id(events) == "abc-123"


def test_find_session_id_returns_none_when_absent():
    assert _runner()._find_session_id([{"type": "assistant"}]) is None


def test_find_result_text_reads_the_last_result_events_result_field():
    runner = _runner()
    events = [
        {"type": "assistant", "message": {"content": [{"type": "text", "text": "partial"}]}},
        {"type": "result", "subtype": "success", "result": "final answer", "total_cost_usd": 0.01},
    ]
    assert runner._find_result_text(events) == "final answer"


def test_find_result_text_is_empty_string_when_no_result_event():
    assert _runner()._find_result_text([{"type": "assistant"}]) == ""


def test_find_cost_reads_total_cost_usd_from_the_result_event():
    runner = _runner()
    events = [{"type": "result", "total_cost_usd": 0.0897704}]
    assert runner._find_cost(events) == 0.0897704


def test_find_cost_is_none_when_no_result_event():
    assert _runner()._find_cost([{"type": "assistant"}]) is None
