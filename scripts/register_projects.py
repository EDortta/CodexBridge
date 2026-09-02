#!/usr/bin/env python3
"""Turn an operator-approved project list into a diff against the real
allowlist files -- and only a diff. This script never writes to any of the
files it reads.

Run explicitly, by an operator, after curating `discover_projects.py`'s
output down to an approved list:

    python3 scripts/register_projects.py --from approved.json \\
        --registry-file /path/to/registry.json \\
        --local-allowed-projects-file ~/.config/codex-bridge-agent/allowed-projects.json \\
        --out diff-report.md

`--from` takes a JSON array of `{"project_id": ..., "name": ..., "path": ...}`
objects -- the same shape `discover_projects.py` emits, trimmed down by a
human to only the entries that should actually be reachable. Every other
`--*-file` flag is optional and independently gated: pass only the files you
actually want a diff against. A file that does not exist yet is treated as
empty (a fresh registry), never as an error.

Why this is diff-only: WK-20260830-chatgpt-entry-provider-and-delivery's
project-access model has no wildcard -- access is an explicit allowlist in
up to four places (the gateway's `registry.json` in two lists, an executor's
own `allowed-projects.json`, and a user's `allowed_projects` in
`users.json`), and some of those four places are live production
configuration on `frida`. Writing to any of them is a production config
change (`docs/limits.md`), which stays a human's decision made once per
file, every time -- this script's whole job is to make that decision fast
and mechanical to review, never to make it.

This script only ever ADDS. It never removes or modifies an existing entry:
narrowing access is a distinct, more sensitive decision (whose project is
this operator taking access away from, and why) that a diff generator
should not make by inferring it from an approved list's absence.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ApprovedProject:
    project_id: str
    name: str
    path: str


def _load_approved(path: Path) -> list[ApprovedProject]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    approved = []
    seen_ids: set[str] = set()
    for entry in payload:
        project_id = entry["project_id"]
        if project_id in seen_ids:
            raise ValueError(f"duplicate project_id in approved list: {project_id!r}")
        seen_ids.add(project_id)
        approved.append(ApprovedProject(project_id=project_id, name=entry["name"], path=entry["path"]))
    return approved


def _load_json_or_empty(path: Path, empty: dict) -> dict:
    if not path.is_file():
        return dict(empty)
    return json.loads(path.read_text(encoding="utf-8"))


def diff_registry_projects(approved: list[ApprovedProject], registry_file: Path) -> tuple[list[dict], list[str]]:
    """Additions to the gateway registry's top-level `projects` list.

    Returns (new_project_entries, notes) -- `notes` flags an approved id that
    already exists in the file under a *different* path, since that is a
    collision this script must surface, not silently skip or overwrite.
    """
    registry = _load_json_or_empty(registry_file, {"executors": [], "projects": []})
    existing = {p["project_id"]: p for p in registry.get("projects", [])}

    additions: list[dict] = []
    notes: list[str] = []
    for project in approved:
        if project.project_id in existing:
            existing_path = existing[project.project_id].get("path")
            if existing_path != project.path:
                notes.append(
                    f"project_id {project.project_id!r} already exists in {registry_file} with path "
                    f"{existing_path!r}, approved list has {project.path!r} -- resolve by hand, not added."
                )
            continue
        additions.append(
            {
                "project_id": project.project_id,
                "name": project.name,
                "path": project.path,
                "allowed_modes": ["analyze", "review", "edit", "test", "implement"],
                "max_timeout_seconds": 3600,
                "sensitive_patterns": ["deploy", "migration", "push"],
                "enabled": True,
            }
        )
    return additions, notes


def diff_executor_allowed_projects(
    approved: list[ApprovedProject], registry_file: Path, executor_id: str
) -> tuple[list[str], list[str]]:
    """Additions to one executor's `allowed_projects` list inside the gateway registry."""
    registry = _load_json_or_empty(registry_file, {"executors": [], "projects": []})
    executors = registry.get("executors", [])
    match = next((e for e in executors if e.get("executor_id") == executor_id), None)
    notes: list[str] = []
    if match is None:
        notes.append(f"executor_id {executor_id!r} not found in {registry_file} -- nothing to diff.")
        return [], notes
    current = set(match.get("allowed_projects", []))
    additions = [p.project_id for p in approved if p.project_id not in current]
    return additions, notes


def diff_local_allowed_projects(approved: list[ApprovedProject], allowed_projects_file: Path) -> tuple[list[dict], list[str]]:
    payload = _load_json_or_empty(allowed_projects_file, {"projects": []})
    existing = {p["project_id"]: p for p in payload.get("projects", [])}
    additions: list[dict] = []
    notes: list[str] = []
    for project in approved:
        if project.project_id in existing:
            existing_path = existing[project.project_id].get("path")
            if existing_path != project.path:
                notes.append(
                    f"project_id {project.project_id!r} already exists in {allowed_projects_file} with path "
                    f"{existing_path!r}, approved list has {project.path!r} -- resolve by hand, not added."
                )
            continue
        additions.append(
            {
                "project_id": project.project_id,
                "name": project.name,
                "path": project.path,
                "allowed_modes": ["analyze", "review", "edit", "test", "implement"],
                "max_timeout_seconds": 3600,
                "sensitive_patterns": ["deploy", "migration", "push"],
                "enabled": True,
            }
        )
    return additions, notes


def diff_user_allowed_projects(
    approved: list[ApprovedProject], user_registry_file: Path, user_id: str
) -> tuple[list[str], list[str]]:
    payload = _load_json_or_empty(user_registry_file, {"users": []})
    users = payload.get("users", [])
    match = next((u for u in users if u.get("user_id") == user_id or u.get("email", "").lower() == user_id.lower()), None)
    notes: list[str] = []
    if match is None:
        notes.append(f"user {user_id!r} not found in {user_registry_file} -- nothing to diff.")
        return [], notes
    current = set(match.get("allowed_projects", []))
    additions = [p.project_id for p in approved if p.project_id not in current]
    return additions, notes


def _render_report(sections: list[tuple[str, object, list[str]]]) -> str:
    lines = ["# register_projects.py -- diff report (not applied)", ""]
    lines.append(
        "Nothing in this report has been written anywhere. Each section below is "
        "what *would* change in one file if a human applies it by hand."
    )
    for title, additions, notes in sections:
        lines.append("")
        lines.append(f"## {title}")
        lines.append("")
        if notes:
            for note in notes:
                lines.append(f"- NOTE: {note}")
        if not additions:
            lines.append("(nada a adicionar)")
            continue
        if isinstance(additions[0], str):
            for item in additions:
                lines.append(f"- add {item!r}")
        else:
            lines.append("```json")
            lines.append(json.dumps(additions, indent=2, ensure_ascii=False))
            lines.append("```")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--from", dest="from_file", type=Path, required=True, help="Operator-approved project list (JSON)")
    parser.add_argument("--registry-file", type=Path, default=None, help="Gateway registry.json to diff against")
    parser.add_argument("--executor-id", type=str, default=None, help="Also diff this executor's allowed_projects (requires --registry-file)")
    parser.add_argument("--local-allowed-projects-file", type=Path, default=None, help="Executor's own allowed-projects.json to diff against")
    parser.add_argument("--user-registry-file", type=Path, default=None, help="users.json to diff against (requires --user-id)")
    parser.add_argument("--user-id", type=str, default=None, help="User id or email whose allowed_projects to diff (requires --user-registry-file)")
    parser.add_argument("--out", type=Path, default=None, help="Write the report here instead of stdout")
    args = parser.parse_args(argv)

    if bool(args.user_registry_file) != bool(args.user_id):
        parser.error("--user-registry-file and --user-id must be given together")
    if args.executor_id and not args.registry_file:
        parser.error("--executor-id requires --registry-file")

    if not args.from_file.is_file():
        print(f"error: {args.from_file} not found", file=sys.stderr)
        return 1
    approved = _load_approved(args.from_file)

    sections: list[tuple[str, object, list[str]]] = []

    if args.registry_file:
        additions, notes = diff_registry_projects(approved, args.registry_file)
        sections.append((f"Gateway registry projects[] ({args.registry_file})", additions, notes))
        if args.executor_id:
            exec_additions, exec_notes = diff_executor_allowed_projects(approved, args.registry_file, args.executor_id)
            sections.append(
                (f"Gateway registry executor {args.executor_id!r} allowed_projects ({args.registry_file})", exec_additions, exec_notes)
            )

    if args.local_allowed_projects_file:
        additions, notes = diff_local_allowed_projects(approved, args.local_allowed_projects_file)
        sections.append((f"Local executor allowed-projects.json ({args.local_allowed_projects_file})", additions, notes))

    if args.user_registry_file:
        additions, notes = diff_user_allowed_projects(approved, args.user_registry_file, args.user_id)
        sections.append((f"User {args.user_id!r} allowed_projects ({args.user_registry_file})", additions, notes))

    if not sections:
        print("error: pass at least one of --registry-file / --local-allowed-projects-file / --user-registry-file", file=sys.stderr)
        return 1

    report = _render_report(sections)
    if args.out:
        args.out.write_text(report, encoding="utf-8")
        print(f"wrote report to {args.out}", file=sys.stderr)
    else:
        print(report)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
