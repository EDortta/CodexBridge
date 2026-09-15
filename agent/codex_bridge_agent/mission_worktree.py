from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path

from codex_bridge_agent.git_tools import run_git

_SAFE = re.compile(r"[^a-zA-Z0-9_-]+")


class MissionWorktreeError(RuntimeError):
    """A worktree cannot be acquired or released without risking operator work."""


@dataclass(frozen=True)
class MissionWorktree:
    mission_id: str
    attempt_number: int
    repository_root: Path
    worktree_path: Path
    base_branch: str
    base_commit: str
    branch_name: str


def _token(value: str, *, limit: int = 40) -> str:
    cleaned = _SAFE.sub("-", value).strip("-_").lower()[:limit]
    digest = hashlib.sha256(value.encode("utf-8")).hexdigest()[:8]
    return f"{cleaned or 'mission'}-{digest}"


def names_for(mission_id: str, attempt_number: int) -> tuple[str, str]:
    """Return deterministic branch and directory names; never caller paths."""
    if attempt_number < 1:
        raise ValueError("attempt_number must be >= 1")
    token = _token(mission_id)
    leaf = f"{token}-attempt-{attempt_number}"
    return f"codexbridge/{leaf}", leaf


async def acquire_mission_worktree(
    repository_root: Path,
    managed_root: Path,
    mission_id: str,
    attempt_number: int,
    *,
    base_branch: str,
) -> MissionWorktree:
    """Create an isolated, deterministic worktree without touching operator files.

    `repository_root` comes from the authorized Workspace Binding and
    `managed_root` from executor configuration. No public/MCP path is accepted.
    A dirty primary checkout is observed but is not cleaned/reset: Git can
    safely create the isolated worktree from the recorded base commit.
    """
    repository_root = repository_root.resolve(strict=True)
    managed_root = managed_root.resolve(strict=True)

    code, top, err = await run_git(repository_root, "rev-parse", "--show-toplevel")
    if code != 0 or Path(top.strip()).resolve() != repository_root:
        raise MissionWorktreeError(f"workspace binding is not repository root: {err.strip()}")

    code, base, err = await run_git(repository_root, "rev-parse", f"{base_branch}^{{commit}}")
    if code != 0:
        raise MissionWorktreeError(f"base branch cannot be resolved: {err.strip()}")
    base_commit = base.strip()

    branch_name, leaf = names_for(mission_id, attempt_number)
    worktree_path = (managed_root / leaf).resolve()
    if managed_root not in worktree_path.parents:
        raise MissionWorktreeError("derived worktree escaped managed root")

    code, listing, err = await run_git(repository_root, "worktree", "list", "--porcelain")
    if code != 0:
        raise MissionWorktreeError(f"cannot inspect worktrees: {err.strip()}")
    blocks = [block.splitlines() for block in listing.split("\n\n") if block.strip()]
    for block in blocks:
        path_line = next((x[9:] for x in block if x.startswith("worktree ")), None)
        branch_line = next((x[7:] for x in block if x.startswith("branch ")), None)
        if path_line and Path(path_line).resolve() == worktree_path:
            if branch_line == f"refs/heads/{branch_name}":
                return MissionWorktree(mission_id, attempt_number, repository_root, worktree_path, base_branch, base_commit, branch_name)
            raise MissionWorktreeError("managed worktree path is owned by another branch")
        if branch_line == f"refs/heads/{branch_name}":
            raise MissionWorktreeError("mission branch is already attached to another worktree")

    if worktree_path.exists():
        raise MissionWorktreeError("derived worktree path already exists and is not owned by git")

    # A pre-existing unattached branch is ambiguous: never reset or reuse it.
    code, _, _ = await run_git(repository_root, "show-ref", "--verify", "--quiet", f"refs/heads/{branch_name}")
    if code == 0:
        raise MissionWorktreeError("mission branch already exists without owned worktree")

    worktree_path.parent.mkdir(parents=True, exist_ok=True)
    code, _, err = await run_git(
        repository_root,
        "worktree", "add", "-b", branch_name, str(worktree_path), base_commit,
    )
    if code != 0:
        raise MissionWorktreeError(f"git worktree add failed: {err.strip()}")

    return MissionWorktree(mission_id, attempt_number, repository_root, worktree_path, base_branch, base_commit, branch_name)


async def release_mission_worktree(worktree: MissionWorktree) -> bool:
    """Remove only a clean owned worktree. Dirty/unmerged work is preserved."""
    path = worktree.worktree_path.resolve()
    code, status, _ = await run_git(path, "status", "--porcelain")
    if code != 0 or status.strip():
        return False

    code, branch, _ = await run_git(path, "branch", "--show-current")
    if code != 0 or branch.strip() != worktree.branch_name:
        return False

    code, _, _ = await run_git(worktree.repository_root, "worktree", "remove", str(path))
    return code == 0
