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


# --------------------------------------------------------------------------
# Issue #66 ARO finding F34: a task.cancel arriving while delivery is still
# in flight. Against a real repository, the same way head_moved is proven
# above -- not a mock asserting the guard was merely called.
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_cancel_pending_before_the_commit_is_refused_without_committing(tmp_path: Path):
    """The checkpoint F34 names explicitly: cancelled before the commit ->

    nothing is committed, the outcome is `refused`, and the staged tree is
    left exactly as `git add` left it -- inspectable, not unstaged.
    """
    _init_repo(tmp_path, branch="feature/uc-200")
    (tmp_path / "app.py").write_text("print('changed')\n", encoding="utf-8")
    head_before = _run(["git", "rev-parse", "HEAD"], tmp_path).stdout.strip()

    outcome = await deliver_changes(
        project_root=tmp_path,
        delivery=_delivery(branch="feature/uc-200"),
        settings=_settings(),
        task_id="t-cancel-1",
        issue_ref=None,
        engine="claude",
        send_log=_collect_logs,
        is_cancelled=lambda: True,
    )

    assert outcome.attempted is True
    assert outcome.outcome == "refused"
    assert outcome.reason == "cancelled_before_commit"
    assert outcome.commit is None
    assert outcome.pushed is False

    # Nothing committed: HEAD did not move.
    head_after = _run(["git", "rev-parse", "HEAD"], tmp_path).stdout.strip()
    assert head_after == head_before
    # And nothing was unstaged either -- the file is still staged, exactly
    # what a cancelled-but-inspectable tree means.
    staged = _run(["git", "diff", "--cached", "--name-only"], tmp_path).stdout.strip()
    assert staged == "app.py"


@pytest.mark.asyncio
async def test_cancellation_is_checked_exactly_once_immediately_before_commit(tmp_path: Path, monkeypatch):
    """Proves the checkpoint's placement, not just its existence: `is_cancelled`

    must not be consulted before `git add` has staged the real changes (an
    earlier check could refuse work that was never actually dangerous yet),
    and it is polled fresh at that one point rather than cached from an
    earlier read.
    """
    import agent.codex_bridge_agent.git_delivery as git_delivery

    _init_repo(tmp_path, branch="feature/uc-201")
    (tmp_path / "app.py").write_text("print('changed')\n", encoding="utf-8")

    calls: list[str] = []
    real_run_git = git_delivery.run_git

    async def recording_run_git(project_root, *args, **kwargs):
        calls.append(args[0] if args else "")
        return await real_run_git(project_root, *args, **kwargs)

    monkeypatch.setattr(git_delivery, "run_git", recording_run_git)

    poll_count = {"n": 0}

    def is_cancelled() -> bool:
        poll_count["n"] += 1
        # Only report cancelled once staging has actually happened -- if the
        # checkpoint fired earlier than intended, "add" would never appear
        # in `calls` at all.
        return "add" in calls

    outcome = await deliver_changes(
        project_root=tmp_path,
        delivery=_delivery(branch="feature/uc-201"),
        settings=_settings(),
        task_id="t-cancel-2",
        issue_ref=None,
        engine="claude",
        send_log=_collect_logs,
        is_cancelled=is_cancelled,
    )

    assert "add" in calls
    assert "commit" not in calls
    assert outcome.outcome == "refused"
    assert outcome.reason == "cancelled_before_commit"
    # Polled exactly once: this module reads the live value at the
    # checkpoint, it does not loop or re-poll.
    assert poll_count["n"] == 1


@pytest.mark.asyncio
async def test_a_cancel_arriving_after_the_commit_checkpoint_does_not_stop_the_push(tmp_path: Path, monkeypatch):
    """The other half of F34's own trade-off, stated in this module's

    docstring: once the pre-commit checkpoint has already passed, a cancel
    becoming true afterward (e.g. while `git push` is running) must not tear
    anything down -- the push still completes and is still verified.
    """
    import agent.codex_bridge_agent.git_delivery as git_delivery

    origin = tmp_path.parent / "origin-cancel.git"
    _run(["git", "init", "-q", "--bare", "-b", "development", str(origin)], tmp_path.parent)

    repo = tmp_path / "work"
    repo.mkdir()
    _init_repo(repo, branch="development")
    _run(["git", "remote", "add", "origin", str(origin)], repo)
    _run(["git", "push", "origin", "development"], repo)
    (repo / "app.py").write_text("print('changed')\n", encoding="utf-8")

    real_run_git = git_delivery.run_git
    cancelled_flag = {"value": False}

    async def push_time_cancel_run_git(project_root, *args, **kwargs):
        result = await real_run_git(project_root, *args, **kwargs)
        if "commit" in args:
            # The cancel arrives AFTER the pre-commit checkpoint has already
            # been read and passed -- i.e. too late to refuse. `commit` is
            # invoked as `-c user.name=... -c user.email=... commit -m ...`,
            # so `args[0]` is `-c`, not `commit` -- membership, not a
            # positional check, the same way the existing force-flag test
            # in this file already scans commit calls.
            cancelled_flag["value"] = True
        return result

    monkeypatch.setattr(git_delivery, "run_git", push_time_cancel_run_git)

    outcome = await deliver_changes(
        project_root=repo,
        delivery=_delivery(branch="feature/uc-202", allow_push=True, base_branch="development"),
        settings=_settings(),
        task_id="t-cancel-3",
        issue_ref=None,
        engine="claude",
        send_log=_collect_logs,
        is_cancelled=lambda: cancelled_flag["value"],
    )

    assert outcome.outcome == "committed_and_pushed"
    assert outcome.pushed is True
    assert outcome.remote_sha == outcome.commit


@pytest.mark.asyncio
async def test_no_is_cancelled_callback_behaves_exactly_like_before(tmp_path: Path):
    """Backward compatibility: every caller that predates F34 (this module's

    own materialize call site, and every other test in this file) never
    passes `is_cancelled` at all -- confirms the default is "never
    cancelled", not a crash on a missing argument.
    """
    _init_repo(tmp_path, branch="feature/uc-203")
    (tmp_path / "app.py").write_text("print('changed')\n", encoding="utf-8")

    outcome = await deliver_changes(
        project_root=tmp_path,
        delivery=_delivery(branch="feature/uc-203"),
        settings=_settings(),
        task_id="t-no-cancel",
        issue_ref=None,
        engine="claude",
        send_log=_collect_logs,
    )

    assert outcome.outcome == "committed_only"
    assert outcome.commit is not None


# --------------------------------------------------------------------------
# Issue #66, WK-20260903-gh66-push-verify: the live smoke test against a
# real GitHub remote (2026-09-03) pushed `feature/preflight-gh66-smoke`
# successfully -- `git ls-remote` against the real remote showed the exact
# commit just made -- yet `deliver_changes` reported `pushed=False,
# reason="push_verification_failed"`. Root cause: the checkout was a
# single-branch clone (`git clone --branch development --depth 3`, and
# `--depth` implies `--single-branch` unless overridden), so
# `remote.origin.fetch` only ever mirrors `development` and `git rev-parse
# origin/<branch>` -- what the old verification ran -- has no local ref to
# read for any OTHER branch, regardless of whether the push reached the
# remote. These tests reproduce that against a real bare remote, not a
# stubbed `run_git`, which is the only way to actually exercise the bug:
# every pre-existing stubbed test in this file (`test_no_command_ever_
# carries_a_force_flag`, `test_a_cancel_arriving_after_the_commit_
# checkpoint_does_not_stop_the_push`) uses a FULL clone, whose refspec
# mirrors every branch and so never trips this at all.
# --------------------------------------------------------------------------


def _clone_single_branch(origin: Path, dest: Path, *, branch: str = "development") -> None:
    """Reproduces the exact checkout shape from the live smoke test: a

    `--branch`+`--depth` clone, which git defaults to `--single-branch` for
    unless `--no-single-branch` is given. `file://` is used (not a bare
    filesystem path) so `--depth` is actually honoured instead of being
    silently ignored the way git does for a local-path source -- the
    narrowed `remote.origin.fetch` this test relies on is a side effect of
    `--single-branch`, not of `--depth` itself, but using the operator's own
    exact command line keeps this test reproducing the real report rather
    than a hand-picked equivalent.
    """
    _run(["git", "clone", "-q", "--branch", branch, "--depth", "3", f"file://{origin}", str(dest)], origin.parent)


@pytest.mark.asyncio
async def test_push_verification_succeeds_against_a_single_branch_clones_narrow_refspec(tmp_path: Path):
    origin = tmp_path.parent / "origin-singlebranch.git"
    _run(["git", "init", "-q", "--bare", "-b", "development", str(origin)], tmp_path.parent)

    seed = tmp_path.parent / "seed-singlebranch"
    seed.mkdir()
    _init_repo(seed, branch="development")
    _run(["git", "remote", "add", "origin", str(origin)], seed)
    _run(["git", "push", "-q", "origin", "development"], seed)

    repo = tmp_path / "work"
    _clone_single_branch(origin, repo)

    # Proves this really is the narrow-refspec scenario the live report
    # described, not an incidental full clone that would pass either way.
    fetch_refspec = _run(["git", "config", "--get-all", "remote.origin.fetch"], repo).stdout.strip()
    assert fetch_refspec == "+refs/heads/development:refs/remotes/origin/development"

    (repo / "app.py").write_text("print('changed')\n", encoding="utf-8")

    outcome = await deliver_changes(
        project_root=repo,
        delivery=_delivery(branch="feature/preflight-gh66-smoke", allow_push=True, base_branch="development"),
        settings=_settings(),
        task_id="t-gh66-live",
        issue_ref="66",
        engine="claude",
        send_log=_collect_logs,
    )

    assert outcome.outcome == "committed_and_pushed"
    assert outcome.pushed is True
    assert outcome.reason is None
    assert outcome.remote_sha == outcome.commit

    # The bug's exact mechanism, confirmed directly: the local
    # remote-tracking ref the OLD code depended on still does not exist,
    # even though the branch is live on the remote (the assertions above
    # already prove that via `ls-remote`, exercised inside `deliver_changes`
    # itself). A `rev-parse`-based check would still fail here today.
    rev_parse = subprocess.run(
        ["git", "rev-parse", "origin/feature/preflight-gh66-smoke"],
        cwd=repo, capture_output=True, text=True,
    )
    assert rev_parse.returncode != 0

    # And the remote genuinely has it, queried independently of the code
    # under test.
    ls_remote = _run(["git", "ls-remote", str(origin), "refs/heads/feature/preflight-gh66-smoke"], repo).stdout
    assert outcome.commit in ls_remote


@pytest.mark.asyncio
async def test_push_verification_flags_a_real_mismatch_distinctly_from_unreachable(tmp_path: Path, monkeypatch):
    """The other half of collapsing two situations into one `reason`: once

    `ls-remote` can be QUERIED but disagrees with the commit just made (a
    genuine race -- another actor overwrote the branch on the remote between
    this module's own push and its verification), that must produce
    `push_verification_failed` with the disagreeing sha attached, distinct
    from the "could not even ask" case the next test covers. Simulated
    against a real bare remote by force-updating the branch's ref on the
    remote itself right after this module's own push lands, not by
    stubbing `ls-remote`'s return value.
    """
    import agent.codex_bridge_agent.git_delivery as git_delivery

    origin = tmp_path.parent / "origin-mismatch.git"
    _run(["git", "init", "-q", "--bare", "-b", "development", str(origin)], tmp_path.parent)

    repo = tmp_path / "work"
    repo.mkdir()
    _init_repo(repo, branch="development")
    _run(["git", "remote", "add", "origin", str(origin)], repo)
    _run(["git", "push", "-q", "origin", "development"], repo)
    (repo / "app.py").write_text("print('changed')\n", encoding="utf-8")

    real_run_git = git_delivery.run_git
    interfering_sha = {"value": None}

    async def racing_run_git(project_root, *args, **kwargs):
        result = await real_run_git(project_root, *args, **kwargs)
        if args and args[0] == "push":
            # Another actor's push lands on the SAME branch on the remote,
            # immediately after this module's own push succeeded and before
            # its verification runs -- a real, independent commit reachable
            # only through the bare remote, not a mocked return value.
            _run(["git", "init", "-q", "-b", "feature/uc-race", str(tmp_path / "racer")], tmp_path)
            racer = tmp_path / "racer"
            _run(["git", "commit", "-q", "--allow-empty", "-m", "racing commit"], racer)
            _run(["git", "remote", "add", "origin", str(origin)], racer)
            _run(["git", "push", "-q", "-f", "origin", "feature/uc-race:feature/uc-103"], racer)
            interfering_sha["value"] = _run(["git", "rev-parse", "HEAD"], racer).stdout.strip()
        return result

    monkeypatch.setattr(git_delivery, "run_git", racing_run_git)

    outcome = await deliver_changes(
        project_root=repo,
        delivery=_delivery(branch="feature/uc-103", allow_push=True, base_branch="development"),
        settings=_settings(),
        task_id="t-race",
        issue_ref=None,
        engine="claude",
        send_log=_collect_logs,
    )

    assert outcome.outcome == "committed_only"
    assert outcome.pushed is False
    assert outcome.reason == "push_verification_failed"
    assert outcome.remote_sha == interfering_sha["value"]
    assert outcome.remote_sha != outcome.commit


@pytest.mark.asyncio
async def test_push_verification_unreachable_is_a_distinct_reason_from_a_real_mismatch(tmp_path: Path, monkeypatch):
    """`ls-remote` itself failing (network gone right after a successful

    push, a transient DNS/TLS failure, the verify timeout firing) must not
    be reported the same way as a successful query that disagrees -- one
    means "we know the push did not land as expected," the other means "we
    no longer know anything." `remote_sha` stays `None` for this case: it
    was never learned.
    """
    import agent.codex_bridge_agent.git_delivery as git_delivery

    origin = tmp_path.parent / "origin-unreachable.git"
    _run(["git", "init", "-q", "--bare", "-b", "development", str(origin)], tmp_path.parent)

    repo = tmp_path / "work"
    repo.mkdir()
    _init_repo(repo, branch="development")
    _run(["git", "remote", "add", "origin", str(origin)], repo)
    _run(["git", "push", "-q", "origin", "development"], repo)
    (repo / "app.py").write_text("print('changed')\n", encoding="utf-8")

    real_run_git = git_delivery.run_git

    async def network_dies_after_push(project_root, *args, **kwargs):
        if args and args[0] == "ls-remote":
            return 128, "", "fatal: unable to access remote: Could not resolve host"
        return await real_run_git(project_root, *args, **kwargs)

    monkeypatch.setattr(git_delivery, "run_git", network_dies_after_push)

    outcome = await deliver_changes(
        project_root=repo,
        delivery=_delivery(branch="feature/uc-104", allow_push=True, base_branch="development"),
        settings=_settings(),
        task_id="t-unreachable",
        issue_ref=None,
        engine="claude",
        send_log=_collect_logs,
    )

    assert outcome.outcome == "committed_only"
    assert outcome.pushed is False
    assert outcome.reason == "push_verification_unreachable"
    assert outcome.remote_sha is None
    # The commit itself is real and untouched -- only verification failed.
    assert outcome.commit is not None
