"""`git_delivery.deliver_changes` against real throwaway git repos.

WK-20260830-chatgpt-entry-provider-and-delivery, slice of issue #51. Every
repo here is built fresh under pytest's own `tmp_path` per test -- never a
real project, never given a remote unless the test itself creates one as
another throwaway `tmp_path` directory to push into.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from agent.codex_bridge_agent.config import AgentSettings
from agent.codex_bridge_agent.git_delivery import (
    MAX_STAGED_PATHS,
    _is_forbidden_path,
    _parse_porcelain_z,
    _parse_shortstat,
    deliver_changes,
)
from shared.protocol import DeliveryRequest


GIT_ENV = {
    "GIT_AUTHOR_NAME": "codexbridge-test",
    "GIT_AUTHOR_EMAIL": "test@example.invalid",
    "GIT_COMMITTER_NAME": "codexbridge-test",
    "GIT_COMMITTER_EMAIL": "test@example.invalid",
}


def _run(args: list[str], cwd: Path) -> subprocess.CompletedProcess:
    import os

    return subprocess.run(args, cwd=cwd, check=True, capture_output=True, text=True, env={**os.environ, **GIT_ENV})


def _init_repo(root: Path, *, branch: str = "development") -> None:
    _run(["git", "init", "-q", "-b", branch], root)
    (root / "README.md").write_text("initial\n", encoding="utf-8")
    _run(["git", "add", "README.md"], root)
    _run(["git", "commit", "-q", "-m", "initial commit"], root)


async def _collect_logs(_name: str, _line: str) -> None:
    return None


def _settings(**overrides) -> AgentSettings:
    return AgentSettings(allow_git_delivery=True, **overrides)


def _delivery(**overrides) -> DeliveryRequest:
    fields = {"branch": "feature/uc-1", "allow_push": False, "base_branch": "development", "remote": "origin"}
    fields.update(overrides)
    return DeliveryRequest(**fields)


# --------------------------------------------------------------------------
# Pure parsing helpers
# --------------------------------------------------------------------------


def test_parse_porcelain_z_handles_a_real_rename_record():
    """Confirmed against real `git status --porcelain=v1 -z` output for a

    rename (`git mv old.txt new.txt` + an edit): the byte sequence is
    `RM new.txt\\0old.txt\\0` -- current path first, then the orig path,
    which must be consumed but never reported as a path to stage.
    """
    raw = "RM new.txt\x00old.txt\x00?? untracked.txt\x00"
    assert _parse_porcelain_z(raw) == ["new.txt", "untracked.txt"]


def test_parse_porcelain_z_empty_output_is_no_paths():
    assert _parse_porcelain_z("") == []


def test_parse_shortstat_reads_all_three_counters():
    assert _parse_shortstat(" 2 files changed, 5 insertions(+), 1 deletion(-)") == (2, 5, 1)


def test_parse_shortstat_missing_fields_default_to_zero():
    assert _parse_shortstat(" 1 file changed, 3 insertions(+)") == (1, 3, 0)


@pytest.mark.parametrize(
    "path,expected_reason",
    [
        (".env", "env_file"),
        (".env.local", "env_file"),
        (".credentials/openai.json", "credentials_dir"),
        ("nested/.credentials/x.json", "credentials_dir"),
        ("id_rsa", "ssh_key"),
        ("id_rsa.pub", "ssh_key"),
        ("secrets/private.pem", "key_file"),
        ("secrets/private.key", "key_file"),
        ("app/node_modules/pkg/index.js", "node_modules"),
        ("codex_bridge.db", "dev_database"),
        (".git/HEAD", "git_internal"),
    ],
)
def test_forbidden_paths_are_named_by_reason(path, expected_reason):
    assert _is_forbidden_path(path) == expected_reason


def test_ordinary_source_paths_are_not_forbidden():
    assert _is_forbidden_path("src/app.py") is None
    assert _is_forbidden_path("docs/README.md") is None


def test_forbidden_paths_defend_the_forge_github_token_specifically():
    """WK-20260902-forge-github-module, issue #80/#79 (PR B2): the forge

    credential this PR added (`AgentSettings.forge_credential_relative_path`,
    default `.credentials/github-token`) relies on this pre-existing guard --
    `_is_forbidden_path`'s `.credentials` check, `git_delivery.py:56-80` --
    to keep the token's resolved bytes from ever reaching a commit even if
    `gh_tool.run_gh`'s own symlink-outside-repo guard were somehow bypassed.
    Named here, by the forge feature, so a future "cleanup" of
    `_is_forbidden_path` does not remove it for looking unused: this test is
    what proves it is load-bearing for forge, not only for the generic
    `.credentials/` case `test_forbidden_paths_are_named_by_reason` above
    already covers.
    """
    assert _is_forbidden_path(".credentials/github-token") == "credentials_dir"


# --------------------------------------------------------------------------
# deliver_changes: refusals
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_refuses_main_regardless_of_the_kill_switch(tmp_path: Path):
    _init_repo(tmp_path)
    outcome = await deliver_changes(
        project_root=tmp_path,
        delivery=_delivery(branch="main", allow_push=True),
        settings=_settings(),
        task_id="t1",
        issue_ref=None,
        engine="claude",
        send_log=_collect_logs,
    )
    assert outcome.outcome == "refused"
    assert outcome.reason == "protected_branch"


@pytest.mark.asyncio
async def test_refuses_a_branch_that_fails_the_pushable_pattern(tmp_path: Path):
    """Defense in depth: even though `DeliveryRequest` itself accepts any

    string, `PUSHABLE_BRANCH_PATTERN` is re-checked here independent of
    whatever the gateway already decided -- a compromised gateway must not be
    able to grant an arbitrary branch by lying about having checked it.
    """
    _init_repo(tmp_path)
    outcome = await deliver_changes(
        project_root=tmp_path,
        delivery=_delivery(branch="not-a-pushable-branch-shape"),
        settings=_settings(),
        task_id="t1",
        issue_ref=None,
        engine="claude",
        send_log=_collect_logs,
    )
    assert outcome.outcome == "refused"
    assert outcome.reason == "branch_not_allowed"


@pytest.mark.asyncio
async def test_refuses_when_the_executor_kill_switch_is_off(tmp_path: Path):
    _init_repo(tmp_path)
    outcome = await deliver_changes(
        project_root=tmp_path,
        delivery=_delivery(),
        settings=AgentSettings(allow_git_delivery=False),
        task_id="t1",
        issue_ref=None,
        engine="claude",
        send_log=_collect_logs,
    )
    assert outcome.outcome == "refused"
    assert outcome.reason == "executor_delivery_disabled"


@pytest.mark.asyncio
async def test_refuses_an_invalid_remote_name_that_could_be_parsed_as_a_flag(tmp_path: Path):
    """`DeliveryRequest.remote` has no shape constraint of its own; a value

    like "--force" passed straight into `git push --set-upstream <remote>
    <branch>` argv would be interpreted as a FLAG, not a remote name, since
    this module builds argv lists rather than a shell string. This is the
    guard that closes that gap.
    """
    _init_repo(tmp_path)
    outcome = await deliver_changes(
        project_root=tmp_path,
        delivery=_delivery(allow_push=True, remote="--force"),
        settings=_settings(),
        task_id="t1",
        issue_ref=None,
        engine="claude",
        send_log=_collect_logs,
    )
    assert outcome.outcome == "refused"
    assert outcome.reason == "invalid_remote"


@pytest.mark.asyncio
async def test_refuses_push_when_the_named_remote_does_not_exist(tmp_path: Path):
    _init_repo(tmp_path)
    outcome = await deliver_changes(
        project_root=tmp_path,
        delivery=_delivery(allow_push=True, remote="origin"),
        settings=_settings(),
        task_id="t1",
        issue_ref=None,
        engine="claude",
        send_log=_collect_logs,
    )
    assert outcome.outcome == "refused"
    assert outcome.reason == "no_remote"


@pytest.mark.asyncio
async def test_skips_cleanly_when_there_is_nothing_to_commit(tmp_path: Path):
    _init_repo(tmp_path)
    outcome = await deliver_changes(
        project_root=tmp_path,
        delivery=_delivery(),
        settings=_settings(),
        task_id="t1",
        issue_ref=None,
        engine="claude",
        send_log=_collect_logs,
    )
    assert outcome.outcome == "skipped"
    assert outcome.reason == "no_changes"


@pytest.mark.asyncio
async def test_refuses_a_credentials_file_even_among_other_real_changes(tmp_path: Path):
    _init_repo(tmp_path)
    (tmp_path / "app.py").write_text("print('hi')\n", encoding="utf-8")
    (tmp_path / ".credentials").mkdir()
    (tmp_path / ".credentials" / "token.json").write_text("{}", encoding="utf-8")

    outcome = await deliver_changes(
        project_root=tmp_path,
        delivery=_delivery(),
        settings=_settings(),
        task_id="t1",
        issue_ref=None,
        engine="claude",
        send_log=_collect_logs,
    )
    assert outcome.outcome == "refused"
    assert outcome.reason.startswith("forbidden_path:credentials_dir")
    # Nothing must be staged or committed on this path.
    status = _run(["git", "status", "--porcelain"], tmp_path).stdout
    assert status.strip() != ""


@pytest.mark.asyncio
async def test_refuses_a_change_too_large_to_have_been_authorized(tmp_path: Path):
    _init_repo(tmp_path)
    for i in range(MAX_STAGED_PATHS + 5):
        (tmp_path / f"file-{i}.txt").write_text("x\n", encoding="utf-8")

    outcome = await deliver_changes(
        project_root=tmp_path,
        delivery=_delivery(),
        settings=_settings(),
        task_id="t1",
        issue_ref=None,
        engine="claude",
        send_log=_collect_logs,
    )
    assert outcome.outcome == "refused"
    assert outcome.reason == "too_many_paths"


# --------------------------------------------------------------------------
# deliver_changes: the successful paths
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_commits_on_a_new_branch_without_pushing(tmp_path: Path):
    _init_repo(tmp_path)
    (tmp_path / "app.py").write_text("print('changed')\n", encoding="utf-8")

    outcome = await deliver_changes(
        project_root=tmp_path,
        delivery=_delivery(branch="feature/uc-99", allow_push=False),
        settings=_settings(),
        task_id="task-123",
        issue_ref="57",
        engine="claude",
        send_log=_collect_logs,
    )

    assert outcome.outcome == "committed_only"
    assert outcome.pushed is False
    assert outcome.created_branch is True
    assert outcome.commit is not None
    assert outcome.staged_paths == ["app.py"]
    assert outcome.files_changed == 1

    branch = _run(["git", "branch", "--show-current"], tmp_path).stdout.strip()
    assert branch == "feature/uc-99"
    log = _run(["git", "log", "-1", "--pretty=%B"], tmp_path).stdout
    assert "Task-Id: task-123" in log
    assert "Issue: 57" in log
    assert "Engine: claude" in log


@pytest.mark.asyncio
async def test_staging_never_uses_add_all_or_a_bare_dot(tmp_path: Path, monkeypatch):
    """The shared working-tree gate: staging is always by explicit path.

    Patches `run_git` to record every argv this module builds and asserts
    none of them is a wildcard stage.
    """
    import agent.codex_bridge_agent.git_delivery as git_delivery

    _init_repo(tmp_path)
    (tmp_path / "app.py").write_text("print('changed')\n", encoding="utf-8")

    calls: list[tuple[str, ...]] = []
    real_run_git = git_delivery.run_git

    async def recording_run_git(project_root, *args, **kwargs):
        calls.append(args)
        return await real_run_git(project_root, *args, **kwargs)

    monkeypatch.setattr(git_delivery, "run_git", recording_run_git)

    await deliver_changes(
        project_root=tmp_path,
        delivery=_delivery(branch="feature/uc-100"),
        settings=_settings(),
        task_id="t1",
        issue_ref=None,
        engine="claude",
        send_log=_collect_logs,
    )

    add_calls = [c for c in calls if c[0] == "add"]
    assert len(add_calls) == 1
    assert add_calls[0][1] == "--"
    assert "-A" not in add_calls[0]
    assert "." not in add_calls[0]
    assert "app.py" in add_calls[0]

    commit_calls = [c for c in calls if "commit" in c]
    for call in commit_calls:
        assert "-a" not in call


@pytest.mark.asyncio
async def test_no_command_ever_carries_a_force_flag(tmp_path: Path, monkeypatch):
    import agent.codex_bridge_agent.git_delivery as git_delivery

    origin = tmp_path.parent / "origin.git"
    _run(["git", "init", "-q", "--bare", "-b", "development", str(origin)], tmp_path.parent)

    repo = tmp_path / "work"
    repo.mkdir()
    _init_repo(repo)
    _run(["git", "remote", "add", "origin", str(origin)], repo)
    _run(["git", "push", "origin", "development"], repo)
    (repo / "app.py").write_text("print('changed')\n", encoding="utf-8")

    calls: list[tuple[str, ...]] = []
    real_run_git = git_delivery.run_git

    async def recording_run_git(project_root, *args, **kwargs):
        calls.append(args)
        return await real_run_git(project_root, *args, **kwargs)

    monkeypatch.setattr(git_delivery, "run_git", recording_run_git)

    outcome = await deliver_changes(
        project_root=repo,
        delivery=_delivery(branch="feature/uc-101", allow_push=True, base_branch="development"),
        settings=_settings(),
        task_id="t1",
        issue_ref=None,
        engine="claude",
        send_log=_collect_logs,
    )

    assert outcome.outcome == "committed_and_pushed"
    assert outcome.pushed is True
    assert outcome.remote_sha == outcome.commit

    for call in calls:
        joined = " ".join(call)
        assert "--force" not in joined
        assert "--force-with-lease" not in joined
        assert "+refs" not in joined

    push_calls = [c for c in calls if c[0] == "push"]
    assert len(push_calls) == 1
    assert push_calls[0] == ("push", "--set-upstream", "origin", "feature/uc-101")


@pytest.mark.asyncio
async def test_head_moving_between_status_and_commit_is_refused_not_forced(tmp_path: Path, monkeypatch):
    """Simulates another process writing to the branch in the gap between

    this module reading `git status` and committing. Nothing must be
    unstaged or force-corrected -- the tree is left exactly as it is, and the
    caller is told both shas so the situation is inspectable.
    """
    import agent.codex_bridge_agent.git_delivery as git_delivery

    _init_repo(tmp_path, branch="feature/uc-102")
    (tmp_path / "app.py").write_text("print('changed')\n", encoding="utf-8")

    real_run_git = git_delivery.run_git
    call_count = {"add": 0}

    async def interfering_run_git(project_root, *args, **kwargs):
        result = await real_run_git(project_root, *args, **kwargs)
        if args and args[0] == "add":
            call_count["add"] += 1
            # Another commit lands on this branch right after staging, before
            # this module re-reads HEAD -- exactly the race the re-read guards.
            _run(["git", "commit", "-q", "--allow-empty", "-m", "concurrent write"], project_root)
        return result

    monkeypatch.setattr(git_delivery, "run_git", interfering_run_git)

    outcome = await deliver_changes(
        project_root=tmp_path,
        delivery=_delivery(branch="feature/uc-102"),
        settings=_settings(),
        task_id="t1",
        issue_ref=None,
        engine="claude",
        send_log=_collect_logs,
    )

    assert call_count["add"] == 1
    assert outcome.outcome == "refused"
    assert outcome.reason.startswith("head_moved:")
    # The concurrent commit is untouched -- nothing was reset or force-pushed.
    log = _run(["git", "log", "-1", "--pretty=%s"], tmp_path).stdout.strip()
    assert log == "concurrent write"
