#!/usr/bin/env python3
"""Detached, fail-closed local Agent release worker. Managed by systemd --user.

The active Agent's operator configuration pins a particular branch and root.
We therefore update the two approved tracked modules *on that same branch* in
a local release commit, rather than silently switching the worktree.
A failed restart is rolled back with an explicit revert commit.
No settings, allowlists, secrets or unrelated files are modified.
"""
from __future__ import annotations

import fcntl
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time

STATE = Path.home() / ".local/state/codexbridge/agent-deploy"
UNIT = "codex-bridge-agent.service"
FILES = ("agent/codex_bridge_agent/file_executor.py",
         "agent/codex_bridge_agent/file_ws_adapter.py")


def cmd(*args: str, cwd: Path | None = None, timeout: int = 35) -> str:
    done = subprocess.run(args, cwd=cwd, text=True, capture_output=True,
                          timeout=timeout, check=False)
    if done.returncode:
        raise RuntimeError("command_failed")
    return done.stdout.strip()


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def service_pid() -> int:
    try:
        if cmd("systemctl", "--user", "is-active", UNIT) != "active":
            return 0
        value = cmd("systemctl", "--user", "show", UNIT,
                    "-p", "MainPID", "--value")
        return int(value) if value.isdecimal() else 0
    except (RuntimeError, OSError, subprocess.TimeoutExpired):
        return 0


def restart() -> bool:
    try:
        cmd("systemctl", "--user", "restart", UNIT, timeout=35)
        return True
    except (RuntimeError, OSError, subprocess.TimeoutExpired):
        return False


def ready(previous_pid: int, seconds: int = 75) -> bool:
    deadline = time.monotonic() + seconds
    while True:
        current = service_pid()
        if current > 0 and current != previous_pid:
            return True
        if time.monotonic() >= deadline:
            return False
        time.sleep(2)


def git(root: Path, *args: str) -> str:
    return cmd("git", "-C", str(root), *args)


def receipt(stage: Path, payload: dict) -> None:
    target = stage / "result.json"
    if target.exists():
        raise RuntimeError("receipt_exists")
    tmp = stage / ".result.tmp"
    with tmp.open("x", encoding="utf-8") as stream:
        json.dump(payload, stream, sort_keys=True)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    os.chmod(tmp, 0o600)
    os.replace(tmp, target)


def apply(stage: Path) -> dict:
    result = {"id": stage.name, "status": "failed", "reason": "preflight",
              "rollback": "not_needed", "service_active": False,
              "ws_verified": False}
    manifest = json.loads((stage / "manifest.json").read_text())
    if (manifest.get("schema") != 1 or manifest.get("profile") != "agent-pr145"
            or list(manifest.get("files", [])) != list(FILES)):
        result["reason"] = "manifest_invalid"
        return result
    root = Path(manifest["active_root"]).resolve(strict=True)
    # Only deploy to the exact originally authorized worktree, never symlinks.
    if str(root) != "/home/esteban/Sync/Projects/AI/CodexBridge-agent":
        result["reason"] = "root_mismatch"
        return result
    if git(root, "branch", "--show-current") != "feature/file-instruction-ws-bridge":
        result["reason"] = "branch_mismatch"
        return result
    if git(root, "rev-parse", "HEAD") != manifest["baseline_commit"]:
        result["reason"] = "baseline_mismatch"
        return result
    if git(root, "status", "--porcelain"):
        result["reason"] = "worktree_dirty"
        return result
    if service_pid() <= 0:
        result["reason"] = "service_inactive"
        return result
    old_pid = service_pid()
    if Path(os.readlink(Path("/proc") / str(old_pid) / "cwd")).resolve() != root:
        result["reason"] = "service_worktree_mismatch"
        return result
    config = Path("/home/esteban/.config/codexbridge/file-executor.json")
    if config.is_symlink() or not config.is_file():
        result["reason"] = "config_invalid"
        return result
    cfg = json.loads(config.read_text())
    if (cfg.get("branch") != "feature/file-instruction-ws-bridge" or
            Path(cfg.get("root", "")).resolve() != root):
        result["reason"] = "config_mismatch"
        return result
    # Bytes come from staged, pinned commit, not from a moving checkout.
    for name in FILES:
        source = stage / name
        dest = root / name
        if source.is_symlink() or dest.is_symlink() or not source.is_file():
            result["reason"] = "source_invalid"
            return result
        if digest(source) != manifest["desired_sha256"][name]:
            result["reason"] = "source_mismatch"
            return result
        if digest(dest) != manifest["baseline_sha256"][name]:
            result["reason"] = "installed_mismatch"
            return result
        compile(source.read_bytes(), name, "exec")
    backup = stage / "backup"
    backup.mkdir(mode=0o700)
    for name in FILES:
        path = backup / name
        path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(root / name, path)
    modified = False
    committed = False
    try:
        for name in FILES:
            dest = root / name
            tmp = dest.with_name("." + dest.name + ".agent-release.tmp")
            if tmp.exists():
                raise RuntimeError("stale_temp")
            shutil.copy2(stage / name, tmp)
            os.replace(tmp, dest)
            modified = True
        git(root, "add", "--", *FILES)
        git(root, "commit", "-m", "release(agent): apply PR145 reconciliation modules")
        committed = True
        if git(root, "status", "--porcelain"):
            raise RuntimeError("post_commit_dirty")
        if not restart() or not ready(old_pid):
            raise RuntimeError("restart_or_readiness_failed")
        if any(digest(root / name) != manifest["desired_sha256"][name] for name in FILES):
            raise RuntimeError("post_apply_hash_mismatch")
        result.update(status="deployed", reason="none",
                      service_active=True, release_commit=git(root, "rev-parse", "HEAD"))
    except Exception:
        result["reason"] = "apply_failed"
        if modified:
            try:
                if committed:
                    if git(root, "status", "--porcelain"):
                        raise RuntimeError("dirty_during_rollback")
                    git(root, "revert", "--no-edit", "HEAD")
                else:
                    for name in FILES:
                        shutil.copy2(backup / name, root / name)
                    git(root, "reset", "--", *FILES)
                restored = all(digest(root / name) == manifest["baseline_sha256"][name]
                               for name in FILES)
                if not restored:
                    raise RuntimeError("rollback_hash_mismatch")
                restore_pid = service_pid()
                if restart() and ready(restore_pid):
                    result.update(rollback="success", service_active=True)
                else:
                    result.update(rollback="failed", reason="rollback_failed")
            except Exception:
                result.update(rollback="failed", reason="rollback_failed")
    return result


def main() -> int:
    if len(sys.argv) != 2:
        return 2
    stage = Path(sys.argv[1]).resolve()
    if (stage.parent != (STATE / "stages").resolve() or
            not stage.name.startswith("ag-")):
        return 2
    lock_file = STATE / "agent-release.lock"
    lock_file.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    result = {"id": stage.name, "status": "failed", "reason": "worker_error",
              "rollback": "not_needed", "service_active": False,
              "ws_verified": False}
    try:
        with lock_file.open("a+") as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                result["reason"] = "deploy_locked"
            else:
                try:
                    result = apply(stage)
                except Exception:
                    result["reason"] = "worker_error"
    except OSError:
        result["reason"] = "lock_error"
    try:
        receipt(stage, result)
    except (OSError, RuntimeError):
        return 3
    return 0 if result["status"] == "deployed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
