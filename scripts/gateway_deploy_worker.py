#!/usr/bin/env python3
"""Root worker started by systemd-run, never attached to the operator console.

A nonterminal failed receipt is not evidence of a healthy service. Logs remain
local on frida, and only bounded sanitized outcome fields travel to devel3.
"""
from __future__ import annotations

import fcntl
import hashlib
import json
import os
from pathlib import Path
import pwd
import re
import shutil
import stat
import subprocess
import sys
import time
import urllib.request

DEST = Path("/opt/codex-bridge")
BACKUPS = Path("/var/backups/codexbridge")
IDENT = re.compile(r"^gw-[0-9]{8}T[0-9]{6}Z-[a-f0-9]{8}$")
HEX = re.compile(r"^[a-f0-9]{64}$")


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def active() -> bool:
    return subprocess.run(
        ["systemctl", "is-active", "--quiet", "codex-bridge-gateway"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False
    ).returncode == 0


def health() -> bool:
    if not active():
        return False
    try:
        with urllib.request.urlopen(
            "http://127.0.0.1:18080/health", timeout=3
        ) as response:
            return response.status == 200 and json.load(response).get("status") == "ok"
    except (OSError, ValueError):
        return False


def ready(seconds: int = 75) -> bool:
    deadline = time.monotonic() + seconds
    while True:
        if health():
            return True
        if time.monotonic() >= deadline:
            return False
        time.sleep(2)


def restart() -> bool:
    try:
        return subprocess.run(
            ["systemctl", "restart", "codex-bridge-gateway"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            timeout=35, check=False,
        ).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def journal_local(backup: Path) -> None:
    try:
        output = subprocess.run(
            ["journalctl", "-u", "codex-bridge-gateway", "-n", "80", "--no-pager"],
            capture_output=True, timeout=15, check=False
        )
        path = backup / "gateway-journal-local-only.log"
        path.write_bytes(output.stdout[-60000:])
        path.chmod(0o600)
    except (OSError, subprocess.TimeoutExpired):
        pass


def validate(stage: Path) -> tuple[list[dict], str]:
    user = os.environ.get("SUDO_USER", "")
    # For systemd-run, SUDO_USER isn't forwarded; stage is validated by
    # approved system user home and strict prefix, not by arbitrary argv.
    allowed = Path("/home/esteban/codexbridge-staging").resolve(strict=True)
    stage = stage.resolve(strict=True)
    if stage.parent != allowed or not IDENT.fullmatch(stage.name):
        raise ValueError("invalid_stage")
    manifest_path = stage / "manifest.json"
    if manifest_path.is_symlink():
        raise ValueError("invalid_manifest")
    manifest = json.loads(manifest_path.read_text())
    if (manifest.get("schema") != 1 or manifest.get("profile") != "code-only"
            or manifest.get("target") != "frida"):
        raise ValueError("invalid_manifest")
    entries = manifest.get("files")
    if not isinstance(entries, list) or not entries or len(entries) > 25:
        raise ValueError("invalid_manifest")
    names = set()
    for entry in entries:
        if not isinstance(entry, dict) or set(entry) != {
            "path", "previous_sha256", "target_sha256"
        }:
            raise ValueError("invalid_manifest")
        name = entry["path"]
        if not isinstance(name, str) or not name.startswith("gateway/") or (
            ".." in Path(name).parts or name in names
        ):
            raise ValueError("invalid_manifest")
        names.add(name)
        if not all(isinstance(entry[key], str) and HEX.fullmatch(entry[key])
                   for key in ("previous_sha256", "target_sha256")):
            raise ValueError("invalid_manifest")
        source = stage / name
        destination = DEST / name
        if (source.is_symlink() or not source.is_file() or
                destination.is_symlink() or not destination.is_file()):
            raise ValueError("invalid_target")
        if digest(source) != entry["target_sha256"]:
            raise ValueError("source_mismatch")
        compile(source.read_bytes(), name, "exec")
    return entries, manifest.get("commit", "")


def install(source: Path, destination: Path, marker: str) -> None:
    previous = destination.stat()
    temp = destination.with_name("." + destination.name + "." + marker + ".tmp")
    if temp.exists():
        raise RuntimeError("stale_temporary_file")
    with temp.open("xb") as handle:
        handle.write(source.read_bytes())
        handle.flush()
        os.fsync(handle.fileno())
    os.chmod(temp, stat.S_IMODE(previous.st_mode))
    os.chown(temp, previous.st_uid, previous.st_gid)
    os.replace(temp, destination)


def apply(stage: Path) -> dict:
    ident = stage.name
    receipt = {
        "id": ident, "status": "failed", "reason": "fatal_error",
        "rollback": "not_needed", "healthy": False,
    }
    try:
        entries, _commit = validate(stage)
    except (OSError, ValueError, json.JSONDecodeError, SyntaxError):
        receipt["reason"] = "invalid_manifest"
        return receipt
    current = [digest(DEST / e["path"]) for e in entries]
    previous = [e["previous_sha256"] for e in entries]
    target = [e["target_sha256"] for e in entries]
    if current == target:
        receipt.update(status="already_current", reason="none", healthy=health())
        if not receipt["healthy"]:
            receipt.update(status="failed", reason="preflight_unhealthy")
        return receipt
    if current != previous:
        receipt["reason"] = "baseline_unknown"
        return receipt
    if not health():
        receipt["reason"] = "preflight_unhealthy"
        return receipt

    backup = BACKUPS / ident
    if backup.exists():
        receipt["reason"] = "backup_exists"
        return receipt
    backup.mkdir(parents=True, mode=0o700)
    for e in entries:
        source = DEST / e["path"]
        target_backup = backup / e["path"]
        target_backup.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        shutil.copy2(source, target_backup)
    changed = False
    try:
        for e in entries:
            install(stage / e["path"], DEST / e["path"], ident)
            changed = True
        if not restart():
            raise RuntimeError("restart_failed")
        if not ready():
            raise RuntimeError("post_apply_unhealthy")
        if [digest(DEST / e["path"]) for e in entries] != target:
            raise RuntimeError("source_mismatch")
        receipt.update(status="deployed", reason="none", healthy=True)
    except Exception as error:
        receipt["reason"] = (
            str(error) if isinstance(error, RuntimeError) and str(error) in {
                "restart_failed", "post_apply_unhealthy", "source_mismatch"
            } else "apply_failed"
        )
        if changed:
            journal_local(backup)
            try:
                for e in entries:
                    install(backup / e["path"], DEST / e["path"], ident + "-rollback")
                restored = [digest(DEST / e["path"]) for e in entries] == previous
                if restored and restart() and ready():
                    receipt.update(rollback="success", healthy=True)
                else:
                    receipt.update(rollback="failed", healthy=False)
                    receipt["reason"] = "rollback_failed"
            except Exception:
                receipt.update(rollback="failed", healthy=False)
                receipt["reason"] = "rollback_failed"
        return receipt
    return receipt


def write_receipt(stage: Path, payload: dict) -> None:
    owner = stage.stat().st_uid
    group = stage.stat().st_gid
    target = stage / "result.json"
    if target.exists():
        raise RuntimeError("receipt_already_exists")
    temporary = stage / ".result.tmp"
    with temporary.open("x", encoding="utf-8") as handle:
        json.dump(payload, handle, sort_keys=True)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.chown(temporary, owner, group)
    os.chmod(temporary, 0o600)
    os.replace(temporary, target)


def main() -> int:
    if len(sys.argv) != 2 or os.geteuid() != 0:
        return 2
    stage = Path(sys.argv[1])
    if not IDENT.fullmatch(stage.name):
        return 2
    lock_path = Path("/run/lock/codexbridge-gateway-deploy.lock")
    try:
        with lock_path.open("a+") as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                result = {
                    "id": stage.name, "status": "failed",
                    "reason": "deploy_locked", "rollback": "not_needed",
                    "healthy": False,
                }
            else:
                try:
                    result = apply(stage)
                except Exception:
                    result = {
                        "id": stage.name, "status": "failed",
                        "reason": "fatal_error", "rollback": "failed",
                        "healthy": False,
                    }
    except OSError:
        result = {
            "id": stage.name, "status": "failed", "reason": "fatal_error",
            "rollback": "not_needed", "healthy": False,
        }
    try:
        write_receipt(stage, result)
    except (OSError, RuntimeError):
        return 3
    return 0 if result["status"] in {"deployed", "already_current"} and result["healthy"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
