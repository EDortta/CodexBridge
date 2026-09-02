"""Read-only filesystem discovery of real git repositories.

Shared by `scripts/discover_projects.py` (an operator's manual, offline scan
of `~/Sync/Projects`) and `agent/codex_bridge_agent/config.py`'s auto-project
fallback (WK-20260830-chatgpt-entry-provider-and-delivery). One
implementation, so a project_id the discovery tool suggests and the id the
running executor resolves at dispatch time are always computed the same way
-- a project called "hub" in one is called "hub" in the other, never a
near-miss.
"""

from __future__ import annotations

import re
from pathlib import Path

# Directory names never descended into, and never reported as a repo root by
# themselves. Deliberately generic -- this file ships in a public repo, so it
# must not name any of the operator's actual project folders (some of which
# are personal/financial and must never appear in a public commit).
EXCLUDED_DIR_NAMES = frozenset(
    {
        ".git",
        ".venv",
        "venv",
        "env",
        "node_modules",
        "__pycache__",
        ".tox",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        "dist",
        "build",
        ".next",
        ".nuxt",
        "target",
        ".idea",
        ".vscode",
        ".stfolder",
        ".stversions",
        ".cache",
        "System Volume Information",
    }
)

_SUFFIX_EXCLUDE_RE = re.compile(r"\.(bak|old|orig)$", re.IGNORECASE)
_ID_SANITIZE_RE = re.compile(r"[^a-z0-9]+")


def is_excluded(dir_name: str) -> bool:
    if dir_name in EXCLUDED_DIR_NAMES:
        return True
    if dir_name.startswith(".Trash"):
        return True
    if _SUFFIX_EXCLUDE_RE.search(dir_name):
        return True
    return False


def walk_for_git_repos(root: Path, max_depth: int) -> list[Path]:
    """Depth-limited scan for directories containing `.git`.

    Descends past a found repo root rather than stopping there, so a
    monorepo's own submodules (each with their own `.git`) are still found as
    separate candidates -- CLAUDE.md's project-scope rule explicitly covers
    "monorepo e submódulos". `.git` itself is never descended into: it holds
    no project code, only git's own bookkeeping. Symlinked directories are
    never followed, so a symlink cannot be used to walk this scan outside
    `root`.
    """
    found: list[Path] = []

    def _recurse(directory: Path, depth: int) -> None:
        if depth > max_depth:
            return
        try:
            entries = sorted(directory.iterdir())
        except (PermissionError, OSError):
            return
        has_git = any(entry.name == ".git" for entry in entries)
        if has_git:
            found.append(directory)
        for entry in entries:
            if not entry.is_dir() or entry.is_symlink():
                continue
            if is_excluded(entry.name):
                continue
            _recurse(entry, depth + 1)

    _recurse(root, 0)
    return found


def suggest_project_id(path: Path, taken: set[str]) -> str:
    """A short, stable, unique-among-`taken` id for `path`'s own directory name.

    `taken` accumulates across a single discovery run (or a single
    resolution index build): the first repo named `api` seen keeps the plain
    id; a later, different `api` gets its parent folder's name prefixed to
    stay unique. Called with the *same* `taken` set, in the same directory
    order, this is deterministic -- which is what lets an id suggested by
    `discover_projects.py` and one resolved later by the running executor
    agree.
    """
    base = _ID_SANITIZE_RE.sub("-", path.name.lower()).strip("-") or "project"
    if base not in taken:
        return base
    parent_name = _ID_SANITIZE_RE.sub("-", path.parent.name.lower()).strip("-")
    candidate = f"{parent_name}-{base}" if parent_name else base
    if candidate not in taken:
        return candidate
    n = 2
    while f"{candidate}-{n}" in taken:
        n += 1
    return f"{candidate}-{n}"


def build_project_id_index(root: Path, max_depth: int) -> dict[str, Path]:
    """Every real repo under `root`, keyed by its `suggest_project_id`.

    This is the read side of the same computation `discover_projects.py`'s
    CLI performs -- reused rather than reimplemented so the two never drift.
    """
    root = root.expanduser().resolve()
    repo_dirs = walk_for_git_repos(root, max_depth)
    taken: set[str] = set()
    index: dict[str, Path] = {}
    for repo_dir in sorted(repo_dirs):
        project_id = suggest_project_id(repo_dir, taken)
        taken.add(project_id)
        index[project_id] = repo_dir
    return index
