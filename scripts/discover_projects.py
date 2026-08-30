#!/usr/bin/env python3
"""Read-only scan of a directory tree for real git repositories.

Run explicitly, by an operator:

    python3 scripts/discover_projects.py                          # scans ~/Sync/Projects, prints JSON
    python3 scripts/discover_projects.py --root ~/Sync/Projects --format table
    python3 scripts/discover_projects.py --out candidates.json

This is step one of a two-step, approval-gated flow for expanding which
projects CodexBridge may operate on (WK-20260830-chatgpt-entry-provider-and-
delivery). It never writes to any allowlist -- it only produces a candidate
list for a human to read, edit down, and approve. `register_projects.py`
is the second step: it turns an *already-approved* list into a diff against
the real allowlist files, and still does not apply that diff itself.

Why this exists: the operator wants CodexBridge/CodexBridgeMobile to
eventually reach every project under `~/Sync/Projects`, but that directory
holds ~60 top-level folders, some with personal/financial data no coding
agent should be pointed at by a blind "register everything" pass. This
script does the mechanical, safe half (find real repos, suggest an id) and
leaves the judgment half (which of these should an agent ever touch) to a
human reading its output.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

DEFAULT_ROOT = Path("~/Sync/Projects").expanduser()

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


def _is_excluded(dir_name: str) -> bool:
    if dir_name in EXCLUDED_DIR_NAMES:
        return True
    if dir_name.startswith(".Trash"):
        return True
    if _SUFFIX_EXCLUDE_RE.search(dir_name):
        return True
    return False


@dataclass(frozen=True)
class Candidate:
    path: str
    depth: int
    suggested_project_id: str
    suggested_name: str
    already_in_local_executor_allowlist: bool


def _walk_for_git_repos(root: Path, max_depth: int) -> list[Path]:
    """Depth-limited scan for directories containing `.git`.

    Descends past a found repo root rather than stopping there, so a
    monorepo's own submodules (each with their own `.git`) are still found as
    separate candidates -- CLAUDE.md's project-scope rule explicitly covers
    "monorepo e submódulos". `.git` itself is never descended into: it holds
    no project code, only git's own bookkeeping.
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
            if _is_excluded(entry.name):
                continue
            _recurse(entry, depth + 1)

    _recurse(root, 0)
    return found


def _suggest_project_id(path: Path, root: Path, taken: set[str]) -> str:
    base = _ID_SANITIZE_RE.sub("-", path.name.lower()).strip("-") or "project"
    if base not in taken:
        return base
    # Disambiguate with the parent folder name -- the shape a real collision
    # takes here is two same-named leaf dirs under different parents (e.g. two
    # `api` submodules in different monorepos), not two unrelated projects
    # that happen to share a name.
    parent_name = _ID_SANITIZE_RE.sub("-", path.parent.name.lower()).strip("-")
    candidate = f"{parent_name}-{base}" if parent_name else base
    if candidate not in taken:
        return candidate
    n = 2
    while f"{candidate}-{n}" in taken:
        n += 1
    return f"{candidate}-{n}"


def _load_local_executor_paths(allowed_projects_file: Path) -> set[str]:
    if not allowed_projects_file.is_file():
        return set()
    try:
        payload = json.loads(allowed_projects_file.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return set()
    paths = set()
    for entry in payload.get("projects", []):
        path = entry.get("path")
        if path:
            paths.add(str(Path(path).expanduser().resolve()))
    return paths


def discover(
    root: Path,
    *,
    max_depth: int = 6,
    local_allowed_projects_file: Path | None = None,
) -> list[Candidate]:
    root = root.expanduser().resolve()
    registered_paths = (
        _load_local_executor_paths(local_allowed_projects_file) if local_allowed_projects_file else set()
    )
    repo_dirs = _walk_for_git_repos(root, max_depth)

    taken: set[str] = set()
    candidates: list[Candidate] = []
    for repo_dir in sorted(repo_dirs):
        depth = len(repo_dir.relative_to(root).parts)
        project_id = _suggest_project_id(repo_dir, root, taken)
        taken.add(project_id)
        candidates.append(
            Candidate(
                path=str(repo_dir),
                depth=depth,
                suggested_project_id=project_id,
                suggested_name=repo_dir.name,
                already_in_local_executor_allowlist=str(repo_dir) in registered_paths,
            )
        )
    return candidates


def _print_table(candidates: list[Candidate]) -> None:
    if not candidates:
        print("(nenhum repositório encontrado)")
        return
    width_id = max(len(c.suggested_project_id) for c in candidates)
    width_path = max(len(c.path) for c in candidates)
    for c in candidates:
        flag = "já registrado" if c.already_in_local_executor_allowlist else "novo"
        print(f"{c.suggested_project_id.ljust(width_id)}  {c.path.ljust(width_path)}  {flag}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT, help="Directory tree to scan (default: ~/Sync/Projects)")
    parser.add_argument("--max-depth", type=int, default=6, help="Max directories to descend below --root (default: 6)")
    parser.add_argument(
        "--local-allowed-projects-file",
        type=Path,
        default=Path("~/.config/codex-bridge-agent/allowed-projects.json").expanduser(),
        help="Local executor allowlist, used only to flag candidates already registered there",
    )
    parser.add_argument("--format", choices=["json", "table"], default="json")
    parser.add_argument("--out", type=Path, default=None, help="Write JSON to this file instead of stdout (format is still respected for stdout)")
    args = parser.parse_args(argv)

    if not args.root.expanduser().is_dir():
        print(f"error: {args.root} is not a directory", file=sys.stderr)
        return 1

    candidates = discover(
        args.root,
        max_depth=args.max_depth,
        local_allowed_projects_file=args.local_allowed_projects_file,
    )

    if args.format == "table":
        _print_table(candidates)
    else:
        payload = json.dumps([asdict(c) for c in candidates], indent=2, ensure_ascii=False)
        if args.out:
            args.out.write_text(payload + "\n", encoding="utf-8")
            print(f"wrote {len(candidates)} candidate(s) to {args.out}", file=sys.stderr)
        else:
            print(payload)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
