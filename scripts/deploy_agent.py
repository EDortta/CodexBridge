#!/usr/bin/env python3
"""Canonical Agent deployment entrypoint (issue #149).

Current release gate: read-only preflight only. Explicitly refuse --apply
until the release/rollback contract for the effective systemd worktree and
file-executor operator configuration is implemented and tested. No mutation,
no service restart, and no independent Agent process.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
SERVICE = "codex-bridge-agent.service"
SERVICE_MODULE = "agent.codex_bridge_agent.service"
EXPECTED_FILES = (
    "agent/codex_bridge_agent/file_executor.py",
    "agent/codex_bridge_agent/file_ws_adapter.py",
)


class PreflightError(Exception):
    pass


def command(*args: str) -> str:
    completed = subprocess.run(args, check=False, text=True,
                               capture_output=True, timeout=15)
    if completed.returncode:
        raise PreflightError("command_failed")
    return completed.stdout.strip()


def systemd_property(name: str) -> str:
    return command("systemctl", "--user", "show", SERVICE,
                   "--property=" + name, "--value")


def check_current_agent() -> dict:
    if systemd_property("ActiveState") != "active":
        raise PreflightError("agent_inactive")
    raw_pid = systemd_property("MainPID")
    if not raw_pid.isdecimal() or int(raw_pid) <= 0:
        raise PreflightError("invalid_main_pid")
    cwd = Path(os.readlink(Path("/proc") / raw_pid / "cwd")).resolve(strict=True)
    # systemctl show WorkingDirectory may be empty on older systemd; the live
    # process cwd is authoritative for Python -m when no PYTHONPATH overrides.
    working = systemd_property("WorkingDirectory")
    if working and Path(working).resolve(strict=True) != cwd:
        raise PreflightError("working_directory_mismatch")
    if not (cwd / ".git").exists():
        raise PreflightError("worktree_not_git")
    branch = command("git", "-C", str(cwd), "branch", "--show-current")
    revision = command("git", "-C", str(cwd), "rev-parse", "HEAD")
    dirty = command("git", "-C", str(cwd), "status", "--porcelain")
    if dirty:
        raise PreflightError("live_worktree_dirty")
    if not branch:
        raise PreflightError("detached_active_worktree")
    if ROOT.resolve(strict=True) != cwd:
        # The candidate version can come from another checkout. This is a
        # detection, not permission to rewrite a different live worktree.
        candidate_is_live = False
    else:
        candidate_is_live = True

    pid_environ = (Path("/proc") / raw_pid / "environ").read_bytes().split(b"\0")
    environment: dict[str, str] = {}
    for item in pid_environ:
        if b"=" in item:
            k, v = item.split(b"=", 1)
            if k.startswith(b"CODEX_BRIDGE_AGENT_"):
                environment[k.decode()] = v.decode()
    path = environment.get("CODEX_BRIDGE_AGENT_FILE_EXECUTOR_CONFIG_FILE")
    if not path:
        raise PreflightError("missing_file_executor_config")
    operator_config = Path(path)
    if not operator_config.is_absolute():
        operator_config = cwd / operator_config
    if operator_config.is_symlink() or not operator_config.is_file():
        raise PreflightError("invalid_file_executor_config")
    data = json.loads(operator_config.read_text())
    if data.get("project") != "codexbridge":
        raise PreflightError("unexpected_project")
    if data.get("branch") != branch:
        raise PreflightError("operator_branch_mismatch")
    if Path(data.get("root", "")).resolve(strict=True) != cwd:
        raise PreflightError("operator_root_mismatch")
    missing = [p for p in EXPECTED_FILES if not (cwd / p).is_file()]
    if missing:
        raise PreflightError("active_agent_modules_missing")
    candidate_missing = [p for p in EXPECTED_FILES if not (ROOT / p).is_file()]
    if candidate_missing:
        raise PreflightError("candidate_agent_modules_missing")

    # No credential or configuration values leave this process.
    return {
        "status": "preflight_ok",
        "service": SERVICE,
        "active": True,
        "branch": branch,
        "revision": revision,
        "candidate_revision": command("git", "-C", str(ROOT), "rev-parse", "HEAD"),
        "candidate_is_live": candidate_is_live,
        "operator_branch_matches": True,
        "operator_root_matches": True,
        "files": list(EXPECTED_FILES),
        "deployment_supported": False,
        "reason": "transactional_agent_release_not_implemented",
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    selection = parser.add_mutually_exclusive_group()
    selection.add_argument("--check", action="store_true")
    selection.add_argument("--apply", action="store_true")
    args = parser.parse_args(argv)
    if args.apply:
        print("BLOCKED=transactional_agent_release_not_implemented", file=sys.stderr)
        return 2
    try:
        report = check_current_agent()
    except (PreflightError, OSError, ValueError, json.JSONDecodeError,
            subprocess.TimeoutExpired) as error:
        category = error.args[0] if isinstance(error, PreflightError) else type(error).__name__
        print("PREFLIGHT=BLOCKED")
        print("REASON=" + category)
        return 2
    print(json.dumps(report, sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
