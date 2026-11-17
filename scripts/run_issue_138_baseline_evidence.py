#!/usr/bin/env python3
"""Run read-only frida OAuth baseline diagnosis and publish a sanitized manifest.

Only SHA-256 hashes, path identifiers, match classification, and Git commit
identifiers leave devel3. Raw stdout/stderr stay in a private 0600 log.
Uses the shared development-evidences publisher with an explicit remote ACK.
Never deploys, changes config, restarts services, or accesses secrets.
"""
from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import time
import uuid

ROOT = Path(__file__).resolve().parents[1]
STATE = Path(os.environ.get("XDG_STATE_HOME", str(Path.home() / ".local/state")))
PUBLISHER = Path(os.environ.get("DEVELOPMENT_EVIDENCES_ROOT", str(STATE / "development-evidences/repo"))) / "publisher.py"
EVIDENCE_REPO = "https://github.com/EDortta/development-evidences"
EXPECTED = (
    "gateway/app/main.py",
    "gateway/app/api/routes/auth.py",
    "gateway/app/core/config.py",
    "gateway/app/core/oauth.py",
)
SHA256 = re.compile(r"^[0-9a-f]{64}$")
COMMIT = re.compile(r"^[0-9a-f]{40}$")
STATUS = {
    "matches_development", "already_matches_patch",
    "historical_git_version", "unknown_version_or_not_in_recent_local_history",
}


def git(*args: str, cwd: Path = ROOT) -> str:
    return subprocess.check_output(
        ["git", *args], cwd=cwd, text=True, stderr=subprocess.DEVNULL
    ).strip()


def parse_diagnostic(raw: str) -> dict:
    result: dict[str, dict] = {}
    for block in raw.split("\nFILE=")[1:]:
        lines = block.strip().splitlines()
        path = lines[0].strip()
        if path not in EXPECTED or path in result:
            raise ValueError("invalid_or_duplicate_file")
        kv = {}
        for line in lines[1:]:
            if "=" in line:
                key, value = line.split("=", 1)
                kv[key] = value.strip()
        if kv.get("STATUS") not in STATUS:
            raise ValueError("invalid_classification")
        hashes = {}
        for key in ("REMOTE_SHA256", "DEVELOPMENT_SHA256", "PATCH_SHA256"):
            value = kv.get(key, "")
            if not SHA256.fullmatch(value):
                raise ValueError("invalid_hash")
            hashes[key.lower()] = value
        item = {"classification": kv["STATUS"], **hashes}
        if kv["STATUS"] == "historical_git_version":
            matched = kv.get("MATCHED_COMMIT", "")
            if not COMMIT.fullmatch(matched):
                raise ValueError("invalid_matched_commit")
            item["matched_commit"] = matched
        result[path] = item
    if set(result) != set(EXPECTED) or "LIVE_FILES_UNCHANGED=1" not in raw:
        raise ValueError("incomplete_diagnostic")
    return result


def publish(relative_path: str, report: dict) -> bool:
    with tempfile.TemporaryDirectory(prefix="issue138-baseline-") as directory:
        envelope = Path(directory) / "envelope.json"
        envelope.write_text(
            json.dumps({"relative_path": relative_path, "report": report},
                       indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        for args in (["enqueue", "--file", str(envelope)], ["flush"]):
            proc = subprocess.run(
                [sys.executable, str(PUBLISHER), *args],
                capture_output=True, text=True, stdin=subprocess.DEVNULL,
                timeout=120, check=False,
            )
            if proc.returncode:
                return False
            if args[0] == "flush" and f"published={relative_path}" not in proc.stdout.splitlines():
                return False
    return True


def main() -> int:
    try:
        branch = git("symbolic-ref", "--short", "HEAD")
        commit = git("rev-parse", "HEAD")
        evidence_branch = git("symbolic-ref", "--short", "HEAD", cwd=PUBLISHER.parent)
        if not COMMIT.fullmatch(commit) or evidence_branch != "main" or not PUBLISHER.is_file():
            raise ValueError("publisher_guard_failed")
    except (OSError, subprocess.CalledProcessError, ValueError):
        print("BLOCKED: invalid Git checkout or evidence publisher", file=sys.stderr)
        return 2

    now = datetime.now(timezone.utc)
    run_id = now.strftime("%H%M%S") + "-" + uuid.uuid4().hex[:8]
    directory = STATE / "codexbridge/issue-138/baseline"
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    logfile = directory / (run_id + ".log")
    started = time.monotonic()
    with logfile.open("wb") as stream:
        os.chmod(logfile, 0o600)
        try:
            process = subprocess.run(
                ["bash", str(ROOT / "scripts/diagnose-frida-issue-138-baseline.sh")],
                cwd=ROOT, stdout=stream, stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL, timeout=180, check=False,
            )
            rc = process.returncode
        except (OSError, subprocess.TimeoutExpired):
            rc = 125
    duration = round(time.monotonic() - started, 3)
    data = {}
    error = "none"
    if rc == 0:
        try:
            data = parse_diagnostic(logfile.read_text(encoding="utf-8"))
        except (OSError, ValueError, UnicodeDecodeError):
            rc, error = 1, "invalid_diagnostic_output"
    else:
        error = "remote_probe_failed"
    status = "pass" if rc == 0 else "fail"
    safe_branch = re.sub(r"[^A-Za-z0-9_.-]", "-", branch)
    relative = (
        f"CodexBridge/issue-138-frida-baseline/{safe_branch}/"
        f"{now:%Y-%m-%d}/{run_id}/manifest.json"
    )
    report = {
        "schema": 1,
        "project": "CodexBridge",
        "feature": "issue-138-frida-baseline",
        "branch": branch,
        "commit": commit,
        "target": "frida",
        "phase": "deploy-test",
        "timestamp_utc": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "status": status,
        "exit_code": rc,
        "duration_seconds": duration,
        "error_category": error,
        "checks": {"read_only": True, "live_files_unchanged": rc == 0,
                   "files": data, "evidence_publication_required": True},
        "detail": "Read-only hashes and Git revisions only; raw diagnostic retained locally",
    }
    try:
        confirmed = publish(relative, report)
    except (OSError, subprocess.TimeoutExpired):
        confirmed = False
    print(f"STATUS={status}")
    print(f"LOCAL_LOG={logfile}")
    if not confirmed:
        print("EVIDENCE_NOT_CONFIRMED: check shared publisher queue", file=sys.stderr)
        return 2
    print(f"EVIDENCE_URL={EVIDENCE_REPO}/blob/main/{relative}")
    return 0 if rc == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
