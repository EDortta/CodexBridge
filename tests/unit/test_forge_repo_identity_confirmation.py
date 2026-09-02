"""`forge.github._confirm_repo_identity_live` -- the live, never-cached check

that the gateway's DECLARED `repo_identity` (`gateway/app/services/
forge_routing.py`) still matches this workspace's REAL git remote, run
before every forge operation. WK-20260902-forge-binding, issue #79/#80
(PR B4).

Every refusal here is paired with a positive control reaching the same
branch successfully, per `docs/napkin-lessons.md`'s 2026-09-01 lesson. This
file never touches `gh` at all (`run_gh` is always faked to a value that
would succeed) -- it is entirely about whether the live `git remote get-url`
check lets an operation past itself, not about what a given operation kind
then does.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from agent.codex_bridge_agent.config import AgentSettings
from agent.codex_bridge_agent.forge import github
from agent.codex_bridge_agent.forge.gh_tool import GhResult
from shared.protocol import ForgeOperationKind, ForgeOperationRequest


async def _collect_logs(_name: str, _line: str) -> None:
    return None


def _settings(**overrides) -> AgentSettings:
    return AgentSettings(allow_forge_operations=True, **overrides)


def _fake_run_gh_always_ok():
    calls: list[tuple] = []

    async def fake(*args, **kwargs):
        calls.append((args, kwargs))
        return GhResult(returncode=0, stdout="[]", stderr="")

    return fake, calls


def _fake_run_git(returncode: int, stdout: str, *, remote_seen: list | None = None):
    async def fake(project_root, *args, timeout_seconds=None):
        if remote_seen is not None:
            remote_seen.append((project_root, args, timeout_seconds))
        return returncode, stdout, ""

    return fake


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "remote_url",
    [
        "https://github.com/owner/repo.git\n",
        "https://github.com/owner/repo\n",
        "git@github.com:owner/repo.git\n",
        "ssh://git@github.com/owner/repo.git\n",
        "https://github.com/Owner/Repo.git\n",  # case-insensitive match
    ],
)
async def test_matching_remote_lets_the_operation_through(tmp_path: Path, monkeypatch, remote_url: str):
    fake_run_gh, gh_calls = _fake_run_gh_always_ok()
    monkeypatch.setattr(github, "run_gh", fake_run_gh)
    monkeypatch.setattr(github, "run_git", _fake_run_git(0, remote_url))

    operation = ForgeOperationRequest(kind=ForgeOperationKind.ISSUE_LIST, repo_identity="owner/repo")
    outcome = await github.run_forge_operation(
        project_root=tmp_path, operation=operation, settings=_settings(), task_id="t1", send_log=_collect_logs
    )

    assert outcome.outcome == "succeeded"
    assert len(gh_calls) == 1


@pytest.mark.asyncio
async def test_a_different_repository_on_the_real_remote_is_refused(tmp_path: Path, monkeypatch):
    fake_run_gh, gh_calls = _fake_run_gh_always_ok()
    monkeypatch.setattr(github, "run_gh", fake_run_gh)
    monkeypatch.setattr(github, "run_git", _fake_run_git(0, "https://github.com/someone-else/other.git\n"))

    operation = ForgeOperationRequest(kind=ForgeOperationKind.ISSUE_LIST, repo_identity="owner/repo")
    outcome = await github.run_forge_operation(
        project_root=tmp_path, operation=operation, settings=_settings(), task_id="t1", send_log=_collect_logs
    )

    assert outcome.outcome == "refused"
    assert outcome.reason == "repo_identity_mismatch"
    assert gh_calls == []  # never reached gh -- the mismatch stops it first


@pytest.mark.asyncio
async def test_a_missing_or_unreadable_remote_is_refused(tmp_path: Path, monkeypatch):
    fake_run_gh, gh_calls = _fake_run_gh_always_ok()
    monkeypatch.setattr(github, "run_gh", fake_run_gh)
    monkeypatch.setattr(github, "run_git", _fake_run_git(128, ""))  # git's own "no such remote" exit code

    operation = ForgeOperationRequest(kind=ForgeOperationKind.ISSUE_LIST, repo_identity="owner/repo")
    outcome = await github.run_forge_operation(
        project_root=tmp_path, operation=operation, settings=_settings(), task_id="t1", send_log=_collect_logs
    )

    assert outcome.outcome == "refused"
    assert outcome.reason == "repo_identity_mismatch"
    assert gh_calls == []


@pytest.mark.asyncio
async def test_a_non_github_remote_is_refused(tmp_path: Path, monkeypatch):
    """A remote that parses as a URL but is not GitHub at all -- this module

    is GitHub-only (`forge/github.py`'s module docstring), so there is no
    `owner/repo` to extract and the safe answer is refusal, not a guess."""
    fake_run_gh, gh_calls = _fake_run_gh_always_ok()
    monkeypatch.setattr(github, "run_gh", fake_run_gh)
    monkeypatch.setattr(github, "run_git", _fake_run_git(0, "https://gitlab.com/owner/repo.git\n"))

    operation = ForgeOperationRequest(kind=ForgeOperationKind.ISSUE_LIST, repo_identity="owner/repo")
    outcome = await github.run_forge_operation(
        project_root=tmp_path, operation=operation, settings=_settings(), task_id="t1", send_log=_collect_logs
    )

    assert outcome.outcome == "refused"
    assert outcome.reason == "repo_identity_mismatch"
    assert gh_calls == []


@pytest.mark.asyncio
async def test_the_check_runs_for_a_write_kind_too_not_only_reads(tmp_path: Path, monkeypatch):
    """Positive-adjacent: the mismatch refusal is not special-cased to reads.

    `ISSUE_OPEN` here would otherwise succeed (`run_gh` is faked to a value
    `_run_issue_open`'s own post-condition check accepts) -- proving the
    live check runs, and refuses, before ANY kind-specific `gh` call, write
    included.
    """
    async def fake_run_gh(*args, **kwargs):
        raise AssertionError("run_gh must never be reached when the remote does not match")

    monkeypatch.setattr(github, "run_gh", fake_run_gh)
    monkeypatch.setattr(github, "run_git", _fake_run_git(0, "https://github.com/someone-else/other.git\n"))

    operation = ForgeOperationRequest(
        kind=ForgeOperationKind.ISSUE_OPEN, repo_identity="owner/repo", title="x", body="y"
    )
    outcome = await github.run_forge_operation(
        project_root=tmp_path, operation=operation, settings=_settings(), task_id="t1", send_log=_collect_logs
    )

    assert outcome.outcome == "refused"
    assert outcome.reason == "repo_identity_mismatch"


@pytest.mark.asyncio
async def test_the_check_is_local_and_uses_its_own_configured_timeout(tmp_path: Path, monkeypatch):
    """`forge_remote_check_timeout_seconds` is threaded through, distinct

    from `forge_operation_timeout_seconds` (that one governs `gh`, this one
    governs the local `git remote get-url` call)."""
    fake_run_gh, _ = _fake_run_gh_always_ok()
    monkeypatch.setattr(github, "run_gh", fake_run_gh)
    seen: list = []
    monkeypatch.setattr(github, "run_git", _fake_run_git(0, "https://github.com/owner/repo.git\n", remote_seen=seen))

    operation = ForgeOperationRequest(kind=ForgeOperationKind.ISSUE_LIST, repo_identity="owner/repo")
    await github.run_forge_operation(
        project_root=tmp_path,
        operation=operation,
        settings=_settings(forge_remote_check_timeout_seconds=3.5),
        task_id="t1",
        send_log=_collect_logs,
    )

    assert len(seen) == 1
    project_root, args, timeout_seconds = seen[0]
    assert project_root == tmp_path
    assert args == ("remote", "get-url", "origin")
    assert timeout_seconds == 3.5
