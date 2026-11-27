#!/usr/bin/env python3
"""Root-only, fail-closed application of the PR #145 Gateway patch on frida.

Called by deploy_pr145_gateway_with_evidence.py. Never run unattended or
without the bounded two-module manifest and a local backup.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import pwd
import shutil
import stat
import subprocess
import sys
import time
import urllib.request

TARGET = Path("/opt/codex-bridge/gateway/app/services")
BACKUP_ROOT = Path("/var/backups/codexbridge")
FILES = ("agent_hub.py", "store.py")
OLD = (
    "24b8a7b51b55ca37a521b957be0cbc7d76bd434a341a344bc3e4574890bd860e",
    "04bf558d25f149c54d81efc072825facd22dc090f424bd1fef60e866234d1487",
)
NEW = (
    "055d5cf6c0f110359ffc42b2c51e7b8638fcad40ae357f62c1fc700ca57afc8f",
    "291d353a0e26c23a5ca31b1f212e245f0c907253f5f728379e14ff33de9ca9f3",
)


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def service_running() -> bool:
    return subprocess.run(
        ["systemctl", "is-active", "--quiet", "codex-bridge-gateway"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False,
    ).returncode == 0


def healthy() -> bool:
    if not service_running():
        return False
    try:
        with urllib.request.urlopen("http://127.0.0.1:18080/health", timeout=3) as response:
            return response.status == 200 and json.load(response).get("status") == "ok"
    except (OSError, ValueError, json.JSONDecodeError):
        return False


def wait_healthy(seconds: int = 75) -> bool:
    end = time.monotonic() + seconds
    while True:
        if healthy():
            return True
        if time.monotonic() >= end:
            return False
        time.sleep(2)


def restart() -> bool:
    try:
        return subprocess.run(
            ["systemctl", "restart", "codex-bridge-gateway"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=35,
            check=False,
        ).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def diagnosis(backup: Path) -> None:
    try:
        result = subprocess.run(
            ["journalctl", "-u", "codex-bridge-gateway", "-n", "80", "--no-pager"],
            capture_output=True, timeout=15, check=False,
        )
        (backup / "journal-local-only.log").write_bytes(result.stdout[-60000:])
        (backup / "journal-local-only.log").chmod(0o600)
    except (OSError, subprocess.TimeoutExpired):
        pass


def apply(stage: Path) -> dict:
    outcome = {"status": "failed", "reason": "preflight", "rollback": "not_needed",
               "gateway_healthy": False, "backup_created": False}
    su = os.environ.get("SUDO_USER", "")
    if os.geteuid() != 0 or not su or su == "root":
        outcome["reason"] = "sudo_required"
        return outcome
    user = pwd.getpwnam(su)
    allowed = (Path(user.pw_dir) / "codexbridge-staging").resolve(strict=True)
    stage = stage.resolve(strict=True)
    if stage.parent != allowed or not stage.name.startswith("pr145-"):
        outcome["reason"] = "invalid_stage"
        return outcome

    manifest = json.loads((stage / "manifest.json").read_text())
    if manifest != {"schema": 1, "profile": "pr145-gateway",
                    "old_sha256": list(OLD), "new_sha256": list(NEW)}:
        outcome["reason"] = "invalid_manifest"
        return outcome
    if any(
        (stage / name).is_symlink() or not (stage / name).is_file()
        or digest(stage / name) != NEW[idx]
        for idx, name in enumerate(FILES)
    ):
        outcome["reason"] = "stage_hash_mismatch"
        return outcome
    for name in FILES:
        compile((stage / name).read_bytes(), name, "exec")

    if any((TARGET / name).is_symlink() or not (TARGET / name).is_file()
           for name in FILES):
        outcome["reason"] = "invalid_target"
        return outcome
    current = tuple(digest(TARGET / name) for name in FILES)
    if current == NEW:
        outcome.update(status="already_current", reason="none",
                       gateway_healthy=healthy())
        if not outcome["gateway_healthy"]:
            outcome["status"] = "failed"
            outcome["reason"] = "gateway_unhealthy"
        return outcome
    if current != OLD:
        outcome["reason"] = "unknown_installed_baseline"
        return outcome
    if not healthy():
        outcome["reason"] = "gateway_unhealthy_preflight"
        return outcome

    backup = BACKUP_ROOT / stage.name
    if backup.exists():
        outcome["reason"] = "backup_collision"
        return outcome
    backup.mkdir(parents=True, mode=0o700)
    ownership = {}
    for name in FILES:
        source = TARGET / name
        metadata = source.stat()
        ownership[name] = (metadata.st_uid, metadata.st_gid, stat.S_IMODE(metadata.st_mode))
        shutil.copy2(source, backup / name)
        os.chown(backup / name, metadata.st_uid, metadata.st_gid)
    outcome["backup_created"] = True
    changed = False
    try:
        for idx, name in enumerate(FILES):
            source = stage / name
            dest = TARGET / name
            original = dest.stat()
            temporary = dest.with_name("." + name + "." + stage.name + ".tmp")
            if temporary.exists():
                raise RuntimeError("stale_temporary_file")
            with temporary.open("xb") as handle:
                handle.write(source.read_bytes())
                handle.flush()
                os.fsync(handle.fileno())
            os.chown(temporary, original.st_uid, original.st_gid)
            os.chmod(temporary, stat.S_IMODE(original.st_mode))
            if digest(temporary) != NEW[idx]:
                raise RuntimeError("installed_hash_mismatch")
            os.replace(temporary, dest)
            changed = True
        if not restart() or not wait_healthy():
            raise RuntimeError("post_restart_unhealthy")
        if tuple(digest(TARGET / name) for name in FILES) != NEW:
            raise RuntimeError("post_apply_hash_mismatch")
        outcome.update(status="deployed", reason="none", gateway_healthy=True)
    except Exception as exc:
        # Details remain on the host; only bounded, non-sensitive classes
        # are exported by the caller to development-evidences.
        outcome["reason"] = type(exc).__name__
        if changed:
            diagnosis(backup)
            try:
                for name in FILES:
                    dest = TARGET / name
                    source = backup / name
                    temporary = dest.with_name("." + name + ".rollback.tmp")
                    shutil.copy2(source, temporary)
                    uid, gid, mode = ownership[name]
                    os.chown(temporary, uid, gid)
                    os.chmod(temporary, mode)
                    os.replace(temporary, dest)
                restored = tuple(digest(TARGET / name) for name in FILES) == OLD
                outcome["rollback"] = (
                    "success" if restored and restart() and wait_healthy()
                    else "failed"
                )
                outcome["gateway_healthy"] = outcome["rollback"] == "success"
            except Exception:
                outcome["rollback"] = "failed"
        else:
            outcome["rollback"] = "not_needed"
    return outcome


def main() -> int:
    if len(sys.argv) != 2:
        print("STATUS=invalid_arguments")
        return 2
    stage = Path(sys.argv[1])
    result = {"status": "failed", "reason": "unexpected_error",
              "rollback": "unknown", "gateway_healthy": False,
              "backup_created": False}
    try:
        result = apply(stage)
    except Exception as exc:
        result["reason"] = type(exc).__name__
    finally:
        # Receipt is purposely sanitized and readable by staging owner.
        su = os.environ.get("SUDO_USER", "")
        if su and su != "root":
            try:
                owner = pwd.getpwnam(su)
                receipt = stage / "result.json"
                receipt.write_text(json.dumps(result, sort_keys=True) + "\n")
                os.chown(receipt, owner.pw_uid, owner.pw_gid)
                os.chmod(receipt, 0o600)
            except (OSError, ValueError):
                result["reason"] = "receipt_write_failed"
                result["status"] = "failed"
        print("STATUS=" + result["status"])
        print("REASON=" + result["reason"])
        print("ROLLBACK=" + result["rollback"])
    return 0 if result["status"] in {"deployed", "already_current"} and result["gateway_healthy"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
