from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from codex_bridge_agent.mission_worktree import (
    MissionWorktreeError,
    acquire_mission_worktree,
    names_for,
    release_mission_worktree,
)


def git(path: Path, *args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=path, text=True).strip()


def init_repo(path: Path) -> None:
    path.mkdir()
    subprocess.check_call(["git", "init", "-b", "development"], cwd=path)
    subprocess.check_call(["git", "config", "user.email", "test@example.invalid"], cwd=path)
    subprocess.check_call(["git", "config", "user.name", "Test"], cwd=path)
    (path / "README.md").write_text("base\n")
    subprocess.check_call(["git", "add", "README.md"], cwd=path)
    subprocess.check_call(["git", "commit", "-m", "base"], cwd=path)


def test_names_are_deterministic_and_path_free() -> None:
    first = names_for("mission/../../operator path", 2)
    second = names_for("mission/../../operator path", 2)
    assert first == second
    assert ".." not in first[0]
    assert "/../../" not in first[0]
    assert first[1].endswith("attempt-2")


@pytest.mark.asyncio
async def test_parallel_missions_get_distinct_worktrees_and_pinned_base(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    managed = tmp_path / "managed"
    managed.mkdir()
    init_repo(repo)
    base = git(repo, "rev-parse", "development")

    one = await acquire_mission_worktree(repo, managed, "m-1", 1, base_branch="development")
    two = await acquire_mission_worktree(repo, managed, "m-2", 1, base_branch="development")

    assert one.worktree_path != two.worktree_path
    assert one.branch_name != two.branch_name
    assert one.base_commit == two.base_commit == base
    assert git(one.worktree_path, "rev-parse", "HEAD") == base
    assert git(two.worktree_path, "rev-parse", "HEAD") == base


@pytest.mark.asyncio
async def test_acquisition_is_idempotent_for_same_attempt(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    managed = tmp_path / "managed"
    managed.mkdir()
    init_repo(repo)
    first = await acquire_mission_worktree(repo, managed, "m-1", 1, base_branch="development")
    second = await acquire_mission_worktree(repo, managed, "m-1", 1, base_branch="development")
    assert second == first


@pytest.mark.asyncio
async def test_dirty_operator_checkout_is_never_cleaned(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    managed = tmp_path / "managed"
    managed.mkdir()
    init_repo(repo)
    (repo / "operator.txt").write_text("do not touch\n")

    worktree = await acquire_mission_worktree(repo, managed, "m-1", 1, base_branch="development")

    assert (repo / "operator.txt").read_text() == "do not touch\n"
    assert "operator.txt" in git(repo, "status", "--porcelain")
    assert not (worktree.worktree_path / "operator.txt").exists()


@pytest.mark.asyncio
async def test_cleanup_preserves_dirty_mission_work(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    managed = tmp_path / "managed"
    managed.mkdir()
    init_repo(repo)
    worktree = await acquire_mission_worktree(repo, managed, "m-1", 1, base_branch="development")
    (worktree.worktree_path / "work.txt").write_text("unmerged operator-visible evidence\n")

    assert await release_mission_worktree(worktree) is False
    assert worktree.worktree_path.exists()


@pytest.mark.asyncio
async def test_unowned_existing_path_is_refused(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    managed = tmp_path / "managed"
    managed.mkdir()
    init_repo(repo)
    _, leaf = names_for("m-1", 1)
    (managed / leaf).mkdir()

    with pytest.raises(MissionWorktreeError, match="already exists"):
        await acquire_mission_worktree(repo, managed, "m-1", 1, base_branch="development")
