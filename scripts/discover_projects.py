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
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from shared.project_discovery import suggest_project_id, walk_for_git_repos  # noqa: E402

DEFAULT_ROOT = Path("~/Sync/Projects").expanduser()


@dataclass(frozen=True)
class Candidate:
    path: str
    depth: int
    suggested_project_id: str
    suggested_name: str
    already_in_local_executor_allowlist: bool


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
    repo_dirs = walk_for_git_repos(root, max_depth)

    taken: set[str] = set()
    candidates: list[Candidate] = []
    for repo_dir in sorted(repo_dirs):
        depth = len(repo_dir.relative_to(root).parts)
        project_id = suggest_project_id(repo_dir, taken)
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
