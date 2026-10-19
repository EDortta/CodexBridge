#!/usr/bin/env python3
"""Configure a LOCAL CodexBridge Worker project's eight-hour monitoring window.

This stage-one CLI does not poll GitHub, install a service, grant execution
permissions, contact Frida, or run commands on any node. Later components
must obtain independent Gateway-side authorization before any execution.
"""

from __future__ import annotations

import argparse
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import re
import sys
import tempfile
from typing import Iterator

WINDOW = timedelta(hours=8)
MAX_ACTIVE = 3
SCHEMA_VERSION = 1
CONTROL_BRANCH = "codexbridge-control"
_PROJECT_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,79}\Z")
_REPO_PART = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,99}\Z")
_BRANCH = re.compile(r"[A-Za-z0-9][A-Za-z0-9._/-]{0,127}\Z")


class WorkerctlError(Exception):
    """Operator-actionable state or configuration error (fail closed)."""


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _timestamp(dt: datetime) -> str:
    if dt.tzinfo is None or dt.utcoffset() is None:
        raise WorkerctlError("the clock must provide a timezone-aware datetime")
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _parse_timestamp(value: object) -> datetime:
    if not isinstance(value, str):
        raise WorkerctlError("invalid timestamp in state file")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise WorkerctlError("invalid timestamp in state file") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise WorkerctlError("state timestamps must contain a timezone")
    return parsed.astimezone(timezone.utc)


def _valid_project_id(value: str) -> str:
    if not _PROJECT_ID.fullmatch(value) or value in {".", ".."}:
        raise WorkerctlError("project id must contain 1-80 ASCII letters, numbers, dots, underscores or hyphens")
    return value


def _valid_repository(value: str) -> str:
    parts = value.split("/")
    if len(parts) != 2 or any(not _REPO_PART.fullmatch(part) or part in {".", ".."} for part in parts):
        raise WorkerctlError("repository must be a GitHub owner/name identifier (no URL or local path)")
    return value


def _valid_branch(value: str) -> str:
    if (
        not _BRANCH.fullmatch(value)
        or ".." in value
        or "//" in value
        or value.endswith(("/", ".", ".lock"))
        or any(part.startswith(".") for part in value.split("/"))
    ):
        raise WorkerctlError("invalid control branch name")
    return value


def _empty_state() -> dict:
    return {"schema_version": SCHEMA_VERSION, "projects": {}, "activations": {}}


def _validate_state(state: object) -> dict:
    if not isinstance(state, dict) or set(state) != {"schema_version", "projects", "activations"}:
        raise WorkerctlError("unsupported or malformed Worker state file")
    if type(state["schema_version"]) is not int or state["schema_version"] != SCHEMA_VERSION:
        raise WorkerctlError("unsupported Worker state schema version")
    projects, activations = state["projects"], state["activations"]
    if not isinstance(projects, dict) or not isinstance(activations, dict):
        raise WorkerctlError("invalid projects or activations in state file")
    known_repos: set[str] = set()
    for project, item in projects.items():
        if not isinstance(project, str):
            raise WorkerctlError("invalid project id in state file")
        _valid_project_id(project)
        if not isinstance(item, dict) or set(item) != {"repository", "control_branch"}:
            raise WorkerctlError("invalid project registration in state file")
        if not all(isinstance(item[key], str) for key in item):
            raise WorkerctlError("invalid repository or control branch in state file")
        _valid_repository(item["repository"])
        _valid_branch(item["control_branch"])
        repo_key = item["repository"].lower()
        if repo_key in known_repos:
            raise WorkerctlError("same GitHub repository is registered under multiple projects")
        known_repos.add(repo_key)
    for project, activation in activations.items():
        if project not in projects or not isinstance(activation, dict):
            raise WorkerctlError("activation references unknown project or is malformed")
        if set(activation) not in ({"enabled_at", "expires_at"}, {"enabled_at", "expires_at", "disabled_at"}):
            raise WorkerctlError("invalid activation fields")
        enabled = _parse_timestamp(activation["enabled_at"])
        expires = _parse_timestamp(activation["expires_at"])
        if expires - enabled != WINDOW:
            raise WorkerctlError("activation duration differs from eight hours")
        if "disabled_at" in activation and _parse_timestamp(activation["disabled_at"]) < enabled:
            raise WorkerctlError("disabled_at is earlier than enabled_at")
    return state


def _status(activation: dict | None, now: datetime) -> str:
    if activation is None:
        return "inactive"
    if "disabled_at" in activation:
        return "disabled"
    enabled = _parse_timestamp(activation["enabled_at"])
    expires = _parse_timestamp(activation["expires_at"])
    # Refuse to turn a clock rewind into extended access. A running Worker
    # must recheck the window for every order, not only once on startup.
    if now < enabled:
        return "clock_error"
    return "active" if now < expires else "expired"


def register(state: dict, project: str, repository: str, branch: str = CONTROL_BRANCH, now: datetime | None = None) -> str:
    _valid_project_id(project)
    _valid_repository(repository)
    _valid_branch(branch)
    registration = {"repository": repository, "control_branch": branch}
    current = state["projects"].get(project)
    if current == registration:
        return "unchanged"
    for key, value in state["projects"].items():
        if key != project and value["repository"].lower() == repository.lower():
            raise WorkerctlError("repository is already registered under another project")
    if current and _status(state["activations"].get(project), now or _utc_now()) in {"active", "clock_error"}:
        raise WorkerctlError("disable the active project before changing its GitHub repository/branch")
    state["projects"][project] = registration
    return "registered"


def enable(state: dict, project: str, now: datetime) -> str:
    _timestamp(now)  # reject naive clocks
    now = now.astimezone(timezone.utc)
    if project not in state["projects"]:
        raise WorkerctlError(f"project {project!r} is not registered; run 'register' first")
    current = _status(state["activations"].get(project), now)
    if current == "clock_error":
        raise WorkerctlError("clock is earlier than this project's previous activation; refusing to extend access")
    if current == "active":
        return "already active (expiry unchanged)"
    statuses = [_status(a, now) for a in state["activations"].values()]
    if "clock_error" in statuses:
        raise WorkerctlError("clock rollback detected; refusing new activations")
    other_active = statuses.count("active")
    if other_active >= MAX_ACTIVE:
        raise WorkerctlError("three projects are already active; disable one or wait for expiry")
    state["activations"][project] = {
        "enabled_at": _timestamp(now),
        "expires_at": _timestamp(now + WINDOW),
    }
    return "enabled"


def disable(state: dict, project: str, now: datetime) -> str:
    _timestamp(now)
    if project not in state["projects"]:
        raise WorkerctlError(f"project {project!r} is not registered")
    activation = state["activations"].get(project)
    if activation is None or "disabled_at" in activation:
        return "already disabled/inactive"
    if now.astimezone(timezone.utc) < _parse_timestamp(activation["enabled_at"]):
        raise WorkerctlError("clock is earlier than the activation; refusing to modify it")
    activation["disabled_at"] = _timestamp(now)
    return "disabled"


def list_projects(state: dict, now: datetime) -> list[dict]:
    _timestamp(now)
    rows = []
    for project, entry in sorted(state["projects"].items()):
        activation = state["activations"].get(project)
        rows.append({
            "project": project,
            "repository": entry["repository"],
            "control_branch": entry["control_branch"],
            "status": _status(activation, now.astimezone(timezone.utc)),
            "expires_at": activation["expires_at"] if activation else None,
        })
    return rows


def default_state_file() -> Path:
    override = os.environ.get("CODEXBRIDGE_WORKERCTL_STATE")
    if override:
        return Path(override).expanduser()
    if os.name == "nt":
        root = Path(os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData" / "Local")))
        return root / "CodexBridge" / "workerctl.json"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "CodexBridge" / "workerctl.json"
    return Path(os.environ.get("XDG_STATE_HOME", str(Path.home() / ".local" / "state"))) / "codexbridge" / "workerctl.json"


@contextmanager
def _locked_file(path: Path) -> Iterator[None]:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    lock = path.with_name(path.name + ".lock")
    if lock.is_symlink():
        raise WorkerctlError("state lock must not be a symbolic link")
    flags = os.O_RDWR | os.O_CREAT
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    fd = os.open(lock, flags, 0o600)
    try:
        with os.fdopen(fd, "r+b") as handle:
            if os.name == "nt":
                import msvcrt
                # Windows record locks require at least one byte in the file.
                handle.seek(0, os.SEEK_END)
                if handle.tell() == 0:
                    handle.write(b"\x00")
                    handle.flush()
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK, 1)
                try:
                    yield
                finally:
                    handle.seek(0)
                    msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
                try:
                    yield
                finally:
                    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    except OSError as exc:
        raise WorkerctlError(f"unable to lock Worker state: {exc.strerror or exc}") from exc


def _read_state(path: Path) -> dict:
    if path.is_symlink():
        raise WorkerctlError("state path must not be a symbolic link")
    if not path.exists():
        return _empty_state()
    try:
        if path.stat().st_size > 1_048_576:
            raise WorkerctlError("Worker state file is unexpectedly large")
        return _validate_state(json.loads(path.read_text(encoding="utf-8")))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise WorkerctlError(f"Worker state cannot be read safely: {exc}") from exc


def _write_state(path: Path, state: dict) -> None:
    _validate_state(state)
    if path.is_symlink():
        raise WorkerctlError("state path must not be a symbolic link")
    temp_name = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                         prefix=".workerctl-", suffix=".tmp", delete=False) as handle:
            temp_name = handle.name
            if os.name != "nt":
                os.chmod(temp_name, 0o600)
            json.dump(state, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, path)
    finally:
        if temp_name and os.path.exists(temp_name):
            os.unlink(temp_name)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state-file", type=Path, default=default_state_file(), help="Local state JSON (never commit this file)")
    sub = parser.add_subparsers(dest="command", required=True)
    reg = sub.add_parser("register", help="Register one GitHub project/branch, without enabling it")
    reg.add_argument("--project", required=True)
    reg.add_argument("--repository", required=True, help="GitHub owner/repo; no URL")
    reg.add_argument("--branch", default=CONTROL_BRANCH, help="Dedicated control branch")
    for name in ("enable", "disable"):
        sub.add_parser(name, help=f"{name} eight-hour monitoring for one project").add_argument("--project", required=True)
    show = sub.add_parser("list", help="List registrations, active windows and expiry")
    show.add_argument("--json", action="store_true", help="Machine-readable output")
    args = parser.parse_args(argv)
    try:
        state_path = args.state_file.expanduser()
        with _locked_file(state_path):
            state = _read_state(state_path)
            now = _utc_now()
            if args.command == "register":
                result = register(state, args.project, args.repository, args.branch, now)
            elif args.command == "enable":
                result = enable(state, args.project, now)
            elif args.command == "disable":
                result = disable(state, args.project, now)
            else:
                rows = list_projects(state, now)
                if args.json:
                    print(json.dumps(rows, indent=2))
                elif not rows:
                    print("No registered projects.")
                else:
                    for row in rows:
                        print(f"{row['project']}: {row['status']}; {row['repository']} "
                              f"[{row['control_branch']}]; expires: {row['expires_at'] or '-'}")
                return 0
            if result not in {"unchanged", "already active (expiry unchanged)", "already disabled/inactive"}:
                _write_state(state_path, state)
            print(f"{args.project}: {result}")
            return 0
    except (WorkerctlError, OSError) as exc:
        print(f"workerctl: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
