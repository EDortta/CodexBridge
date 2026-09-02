"""`forge.github.run_forge_operation` -- argv assembly, the kill switch, local

re-validation, and the `issue_open` post-condition check. WK-20260902-forge-
github-module, issue #80/#79 (PR B2).

Nothing here ever calls `gh_tool.run_gh` for real: it is monkeypatched to a
fake that records every call and returns a scripted `GhResult`, so these
tests are entirely about what `github.py` BUILDS and DECIDES, never about
`gh_tool.py`'s own subprocess plumbing (covered by `tests/unit/test_gh_tool.py`).
Every refusal here is paired with a positive control that reaches the same
branch successfully, per `docs/napkin-lessons.md`'s 2026-09-01 lesson.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from agent.codex_bridge_agent.config import AgentSettings
from agent.codex_bridge_agent.forge import github
from agent.codex_bridge_agent.forge.base import MAX_CAPTURED_OUTPUT, ForgeOutcome
from agent.codex_bridge_agent.forge.gh_tool import GhResult
from shared.protocol import ForgeOperationKind, ForgeOperationRequest


async def _collect_logs(_name: str, _line: str) -> None:
    return None


def _settings(**overrides) -> AgentSettings:
    return AgentSettings(allow_forge_operations=True, **overrides)


@pytest.fixture(autouse=True)
def _live_remote_matches_owner_repo(monkeypatch):
    """WK-20260902-forge-binding (PR B4): `run_forge_operation` now confirms

    `operation.repo_identity` against this workspace's REAL git remote
    (`_confirm_repo_identity_live`) before running anything else. Every test
    in this file uses `repo_identity="owner/repo"` and `tmp_path` as the
    project root -- a bare temp directory with no real git remote at all --
    so without this fixture every single test here would fail the new check
    before ever reaching the behavior it actually means to exercise.
    `tests/unit/test_forge_repo_identity_confirmation.py` is where the check
    itself, including its mismatch/refusal path, is tested directly; this
    fixture exists so it does not have to be re-proven, or worked around, in
    every other test in this module.
    """

    async def fake_run_git(_project_root, *args, timeout_seconds=None):
        assert args[:2] == ("remote", "get-url")
        return 0, "https://github.com/owner/repo.git\n", ""

    monkeypatch.setattr(github, "run_git", fake_run_git)


def _make_fake_run_gh(result_factory):
    """`result_factory` is either a fixed `GhResult` or a callable taking the
    recorded call dict and returning one -- the latter lets a test answer
    based on what argv it actually received (e.g. echoing the body-file
    content back)."""
    calls: list[dict] = []

    async def fake_run_gh(project_root, *args, gh_bin, credential_relative_path, timeout_seconds):
        entry: dict = {
            "project_root": project_root,
            "args": list(args),
            "gh_bin": gh_bin,
            "credential_relative_path": credential_relative_path,
            "timeout_seconds": timeout_seconds,
        }
        if "--body-file" in args:
            body_path = Path(args[args.index("--body-file") + 1])
            entry["body_file_path"] = body_path
            entry["body_file_existed_during_call"] = body_path.exists()
            entry["body_file_content"] = body_path.read_text(encoding="utf-8") if body_path.exists() else None
        calls.append(entry)
        if callable(result_factory):
            return result_factory(entry)
        return result_factory

    return fake_run_gh, calls


# --------------------------------------------------------------------------
# The machine-level kill switch: checked before anything touches `gh`
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_kill_switch_refuses_before_run_gh_is_ever_called(tmp_path: Path, monkeypatch):
    fake_run_gh, calls = _make_fake_run_gh(GhResult(returncode=0, stdout="unused", stderr=""))
    monkeypatch.setattr(github, "run_gh", fake_run_gh)

    operation = ForgeOperationRequest(kind=ForgeOperationKind.ISSUE_LIST, repo_identity="owner/repo")
    outcome = await github.run_forge_operation(
        project_root=tmp_path,
        operation=operation,
        settings=AgentSettings(allow_forge_operations=False),
        task_id="t1",
        send_log=_collect_logs,
    )

    assert outcome.outcome == "refused"
    assert outcome.reason == "executor_forge_disabled"
    assert calls == []  # the fake `run_gh` was never invoked


@pytest.mark.asyncio
async def test_kill_switch_on_lets_a_valid_operation_through(tmp_path: Path, monkeypatch):
    """Positive control for the refusal above."""
    fake_run_gh, calls = _make_fake_run_gh(GhResult(returncode=0, stdout="[]", stderr=""))
    monkeypatch.setattr(github, "run_gh", fake_run_gh)

    operation = ForgeOperationRequest(kind=ForgeOperationKind.ISSUE_LIST, repo_identity="owner/repo")
    outcome = await github.run_forge_operation(
        project_root=tmp_path,
        operation=operation,
        settings=_settings(),
        task_id="t1",
        send_log=_collect_logs,
    )

    assert outcome.outcome == "succeeded"
    assert len(calls) == 1


# --------------------------------------------------------------------------
# issue_open
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_issue_open_builds_the_exact_argv_and_succeeds_on_a_real_postcondition(tmp_path: Path, monkeypatch):
    fake_run_gh, calls = _make_fake_run_gh(
        GhResult(returncode=0, stdout="https://github.com/owner/repo/issues/17\n", stderr="")
    )
    monkeypatch.setattr(github, "run_gh", fake_run_gh)

    operation = ForgeOperationRequest(
        kind=ForgeOperationKind.ISSUE_OPEN, repo_identity="owner/repo", title="Fix the bug", body="Steps to repro"
    )
    outcome = await github.run_forge_operation(
        project_root=tmp_path,
        operation=operation,
        settings=_settings(),
        task_id="t1",
        send_log=_collect_logs,
    )

    assert len(calls) == 1
    args = calls[0]["args"]
    assert args[:-1] == ["issue", "create", "--repo", "owner/repo", "--title", "Fix the bug", "--body-file"]
    assert Path(args[-1]).name.startswith("codexbridge-forge-body-")
    assert calls[0]["body_file_existed_during_call"] is True
    assert calls[0]["body_file_content"] == "Steps to repro"
    # The temp file must not survive the call, success or not.
    assert calls[0]["body_file_path"].exists() is False

    assert outcome.outcome == "succeeded"
    assert outcome.issue_number == 17
    assert outcome.issue_url == "https://github.com/owner/repo/issues/17"


@pytest.mark.asyncio
async def test_issue_open_exit_zero_without_an_issue_url_is_refused_not_succeeded(tmp_path: Path, monkeypatch):
    """The post-condition check: `git_delivery.py` compares the remote sha
    rather than trusting `push`'s exit code; this is the same property
    applied to `gh issue create` -- exit 0 alone is not proof an issue
    exists."""
    fake_run_gh, calls = _make_fake_run_gh(GhResult(returncode=0, stdout="nothing issue-shaped here", stderr=""))
    monkeypatch.setattr(github, "run_gh", fake_run_gh)

    operation = ForgeOperationRequest(kind=ForgeOperationKind.ISSUE_OPEN, repo_identity="owner/repo", title="x")
    outcome = await github.run_forge_operation(
        project_root=tmp_path,
        operation=operation,
        settings=_settings(),
        task_id="t1",
        send_log=_collect_logs,
    )

    assert outcome.outcome == "refused"
    assert outcome.reason.startswith("forge_postcondition_failed")
    assert outcome.issue_number is None
    # Still cleaned up even though the outcome was refused.
    assert calls[0]["body_file_path"].exists() is False


@pytest.mark.asyncio
async def test_issue_open_body_file_is_deleted_even_when_gh_fails(tmp_path: Path, monkeypatch):
    fake_run_gh, calls = _make_fake_run_gh(GhResult(returncode=1, stdout="", stderr="gh: some error"))
    monkeypatch.setattr(github, "run_gh", fake_run_gh)

    operation = ForgeOperationRequest(kind=ForgeOperationKind.ISSUE_OPEN, repo_identity="owner/repo", title="x")
    outcome = await github.run_forge_operation(
        project_root=tmp_path,
        operation=operation,
        settings=_settings(),
        task_id="t1",
        send_log=_collect_logs,
    )

    assert outcome.outcome == "refused"
    assert outcome.reason == "gh_command_failed"
    assert calls[0]["body_file_existed_during_call"] is True
    assert calls[0]["body_file_path"].exists() is False


# --------------------------------------------------------------------------
# issue_comment
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_issue_comment_builds_the_exact_argv_and_succeeds(tmp_path: Path, monkeypatch):
    fake_run_gh, calls = _make_fake_run_gh(
        GhResult(returncode=0, stdout="https://github.com/owner/repo/issues/9#issuecomment-1\n", stderr="")
    )
    monkeypatch.setattr(github, "run_gh", fake_run_gh)

    operation = ForgeOperationRequest(
        kind=ForgeOperationKind.ISSUE_COMMENT, repo_identity="owner/repo", issue_number=9, body="a comment"
    )
    outcome = await github.run_forge_operation(
        project_root=tmp_path,
        operation=operation,
        settings=_settings(),
        task_id="t1",
        send_log=_collect_logs,
    )

    assert len(calls) == 1
    args = calls[0]["args"]
    assert args[:-1] == ["issue", "comment", "9", "--repo", "owner/repo", "--body-file"]
    assert calls[0]["body_file_content"] == "a comment"
    assert calls[0]["body_file_path"].exists() is False

    assert outcome.outcome == "succeeded"
    assert outcome.issue_number == 9


@pytest.mark.asyncio
async def test_issue_comment_without_a_real_issue_number_is_refused_locally_before_run_gh(
    tmp_path: Path, monkeypatch
):
    """Simulates an object that bypassed `ForgeOperationRequest`'s own
    `@model_validator` (e.g. via `model_construct`) -- the executor must not
    trust that the request in hand actually went through it."""
    fake_run_gh, calls = _make_fake_run_gh(GhResult(returncode=0, stdout="unused", stderr=""))
    monkeypatch.setattr(github, "run_gh", fake_run_gh)

    bypassed = ForgeOperationRequest.model_construct(
        kind=ForgeOperationKind.ISSUE_COMMENT,
        repo_identity="owner/repo",
        title=None,
        body="hi",
        issue_number=None,
        state=None,
    )
    outcome = await github.run_forge_operation(
        project_root=tmp_path,
        operation=bypassed,
        settings=_settings(),
        task_id="t1",
        send_log=_collect_logs,
    )

    assert outcome.outcome == "refused"
    assert outcome.reason == "invalid_issue_number"
    assert calls == []


# --------------------------------------------------------------------------
# issue_close
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_issue_close_builds_the_exact_fully_static_argv_and_succeeds(tmp_path: Path, monkeypatch):
    fake_run_gh, calls = _make_fake_run_gh(GhResult(returncode=0, stdout="closed", stderr=""))
    monkeypatch.setattr(github, "run_gh", fake_run_gh)

    operation = ForgeOperationRequest(kind=ForgeOperationKind.ISSUE_CLOSE, repo_identity="owner/repo", issue_number=42)
    outcome = await github.run_forge_operation(
        project_root=tmp_path,
        operation=operation,
        settings=_settings(),
        task_id="t1",
        send_log=_collect_logs,
    )

    assert len(calls) == 1
    assert calls[0]["args"] == ["issue", "close", "42", "--repo", "owner/repo"]
    assert outcome.outcome == "succeeded"
    assert outcome.issue_number == 42


@pytest.mark.asyncio
async def test_issue_close_propagates_a_credential_refusal_from_run_gh(tmp_path: Path, monkeypatch):
    fake_run_gh, calls = _make_fake_run_gh(
        GhResult(returncode=None, stdout="", stderr="", refused_reason="forge_credential_must_be_symlink_outside_repo")
    )
    monkeypatch.setattr(github, "run_gh", fake_run_gh)

    operation = ForgeOperationRequest(kind=ForgeOperationKind.ISSUE_CLOSE, repo_identity="owner/repo", issue_number=1)
    outcome = await github.run_forge_operation(
        project_root=tmp_path,
        operation=operation,
        settings=_settings(),
        task_id="t1",
        send_log=_collect_logs,
    )

    assert len(calls) == 1
    assert outcome.outcome == "refused"
    assert outcome.reason == "forge_credential_must_be_symlink_outside_repo"


# --------------------------------------------------------------------------
# issue_list
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_issue_list_builds_the_exact_fully_static_argv_with_default_state(tmp_path: Path, monkeypatch):
    fake_run_gh, calls = _make_fake_run_gh(GhResult(returncode=0, stdout="[]", stderr=""))
    monkeypatch.setattr(github, "run_gh", fake_run_gh)

    operation = ForgeOperationRequest(kind=ForgeOperationKind.ISSUE_LIST, repo_identity="owner/repo")
    outcome = await github.run_forge_operation(
        project_root=tmp_path,
        operation=operation,
        settings=_settings(),
        task_id="t1",
        send_log=_collect_logs,
    )

    assert calls[0]["args"] == [
        "issue",
        "list",
        "--repo",
        "owner/repo",
        "--state",
        "open",
        "--json",
        "number,title,state,url",
        "--limit",
        "30",
    ]
    assert outcome.outcome == "succeeded"
    assert outcome.issues == []


@pytest.mark.asyncio
async def test_issue_list_honors_an_explicit_state_and_parses_the_json_result(tmp_path: Path, monkeypatch):
    payload = '[{"number": 3, "title": "t", "state": "closed", "url": "https://x/3"}]'
    fake_run_gh, calls = _make_fake_run_gh(GhResult(returncode=0, stdout=payload, stderr=""))
    monkeypatch.setattr(github, "run_gh", fake_run_gh)

    operation = ForgeOperationRequest(kind=ForgeOperationKind.ISSUE_LIST, repo_identity="owner/repo", state="closed")
    outcome = await github.run_forge_operation(
        project_root=tmp_path,
        operation=operation,
        settings=_settings(),
        task_id="t1",
        send_log=_collect_logs,
    )

    assert calls[0]["args"][calls[0]["args"].index("--state") + 1] == "closed"
    assert outcome.outcome == "succeeded"
    assert outcome.issues == [{"number": 3, "title": "t", "state": "closed", "url": "https://x/3"}]


@pytest.mark.asyncio
async def test_issue_list_non_json_output_is_refused_not_succeeded(tmp_path: Path, monkeypatch):
    fake_run_gh, calls = _make_fake_run_gh(GhResult(returncode=0, stdout="not json at all", stderr=""))
    monkeypatch.setattr(github, "run_gh", fake_run_gh)

    operation = ForgeOperationRequest(kind=ForgeOperationKind.ISSUE_LIST, repo_identity="owner/repo")
    outcome = await github.run_forge_operation(
        project_root=tmp_path,
        operation=operation,
        settings=_settings(),
        task_id="t1",
        send_log=_collect_logs,
    )

    assert outcome.outcome == "refused"
    assert outcome.reason.startswith("forge_postcondition_failed")


# --------------------------------------------------------------------------
# repo_identity re-validation: `REPO_IDENTITY_PATTERN` applied again here,
# never trusting that the object in hand actually went through the model's
# own validator (git_delivery property: re-check what the gateway already
# checked, `_REMOTE_NAME_PATTERN` reapplied to `remote` in `git_delivery.py`).
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_malformed_repo_identity_that_bypassed_pydantic_never_reaches_run_gh(tmp_path: Path, monkeypatch):
    fake_run_gh, calls = _make_fake_run_gh(GhResult(returncode=0, stdout="[]", stderr=""))
    monkeypatch.setattr(github, "run_gh", fake_run_gh)

    bypassed = ForgeOperationRequest.model_construct(
        kind=ForgeOperationKind.ISSUE_LIST,
        repo_identity="--flag/x",
        title=None,
        body=None,
        issue_number=None,
        state=None,
    )
    outcome = await github.run_forge_operation(
        project_root=tmp_path,
        operation=bypassed,
        settings=_settings(),
        task_id="t1",
        send_log=_collect_logs,
    )

    assert outcome.outcome == "refused"
    assert outcome.reason == "invalid_repo_identity"
    assert calls == []  # never reached run_gh, so "--flag/x" never reached an argv


@pytest.mark.asyncio
async def test_a_wellformed_repo_identity_that_bypassed_pydantic_still_reaches_run_gh(tmp_path: Path, monkeypatch):
    """Positive control: `model_construct` alone is not what gets refused --
    only a `repo_identity` that fails `REPO_IDENTITY_PATTERN` does."""
    fake_run_gh, calls = _make_fake_run_gh(GhResult(returncode=0, stdout="[]", stderr=""))
    monkeypatch.setattr(github, "run_gh", fake_run_gh)

    bypassed = ForgeOperationRequest.model_construct(
        kind=ForgeOperationKind.ISSUE_LIST,
        repo_identity="owner/repo",
        title=None,
        body=None,
        issue_number=None,
        state=None,
    )
    outcome = await github.run_forge_operation(
        project_root=tmp_path,
        operation=bypassed,
        settings=_settings(),
        task_id="t1",
        send_log=_collect_logs,
    )

    assert outcome.outcome == "succeeded"
    assert len(calls) == 1


# --------------------------------------------------------------------------
# Settings are threaded through to run_gh untouched
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_settings_are_forwarded_to_run_gh(tmp_path: Path, monkeypatch):
    fake_run_gh, calls = _make_fake_run_gh(GhResult(returncode=0, stdout="[]", stderr=""))
    monkeypatch.setattr(github, "run_gh", fake_run_gh)

    operation = ForgeOperationRequest(kind=ForgeOperationKind.ISSUE_LIST, repo_identity="owner/repo")
    await github.run_forge_operation(
        project_root=tmp_path,
        operation=operation,
        settings=_settings(
            forge_gh_bin="/opt/gh/gh",
            forge_credential_relative_path=".credentials/other-token",
            forge_operation_timeout_seconds=12.5,
        ),
        task_id="t1",
        send_log=_collect_logs,
    )

    assert calls[0]["gh_bin"] == "/opt/gh/gh"
    assert calls[0]["credential_relative_path"] == ".credentials/other-token"
    assert calls[0]["timeout_seconds"] == 12.5


def test_captured_output_is_bounded_before_it_leaves_the_executor() -> None:
    """`gh` output is third-party text of unbounded size, and it travels.

    A `ForgeOutcome` crosses the websocket to the gateway and lands in a
    stored result blob. `DeliveryOutcome`, the precedent this module mirrors,
    sidesteps the question by carrying structured facts only and never a
    command's raw output; keeping the output here is a deliberate departure
    for diagnosability, so the bound is what keeps it honest.
    """
    huge = "x" * (MAX_CAPTURED_OUTPUT + 5_000)
    outcome = ForgeOutcome(attempted=True, outcome="refused", reason="boom", stdout=huge, stderr=huge)

    assert len(outcome.stdout) < len(huge)
    assert len(outcome.stderr) < len(huge)
    assert "5000 more characters dropped" in outcome.stdout
    assert outcome.to_dict()["stderr"].startswith("x" * 100)


def test_output_within_the_bound_is_left_exactly_as_gh_produced_it() -> None:
    """Positive control: the cap must not rewrite ordinary output.

    Without this, a bug that truncated everything to the empty string would
    still satisfy the test above.
    """
    modest = "https://github.com/owner/repo/issues/42\n"
    outcome = ForgeOutcome(attempted=True, outcome="succeeded", stdout=modest, stderr="")

    assert outcome.stdout == modest
    assert outcome.stderr == ""
