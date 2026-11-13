#!/usr/bin/env python3
"""Run a deployment validation and publish a sanitized, verifiable evidence record.

Do not pass secrets in command arguments: argv is never published, but local
process listings can expose it. The command's stdout/stderr remain local.
"""
from __future__ import annotations

import argparse
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
PUBLISHER = STATE / "development-evidences/repo/publisher.py"
EVIDENCE_REPO = "https://github.com/EDortta/development-evidences"
SAFE_NAME = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_.-]{0,63}$")


def git(*args: str, cwd: Path = ROOT) -> str:
    return subprocess.check_output(["git", *args], cwd=cwd, text=True,
                                   stderr=subprocess.DEVNULL).strip()


def run_validation(command: list[str], *, log_path: Path) -> tuple[int, float]:
    log_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    started = time.monotonic()
    with log_path.open("wb") as output:
        os.chmod(log_path, 0o600)
        try:
            completed = subprocess.run(command, cwd=ROOT, stdin=subprocess.DEVNULL,
                                       stdout=output, stderr=subprocess.STDOUT)
            return completed.returncode, round(time.monotonic() - started, 3)
        except OSError:
            return 125, round(time.monotonic() - started, 3)


def publish(report: dict, relative_path: str, *, publisher: Path = PUBLISHER) -> bool:
    if not publisher.is_file():
        return False
    envelope = {"relative_path": relative_path, "report": report}
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "envelope.json"
        path.write_text(json.dumps(envelope), encoding="utf-8")
        for args in (["enqueue", "--file", str(path)], ["flush"]):
            result = subprocess.run([sys.executable, str(publisher), *args],
                                    capture_output=True, text=True, timeout=120)
            if result.returncode:
                return False
            if args[0] == "flush" and f"published={relative_path}" not in result.stdout:
                # A zero return code without this record's remote ACK is insufficient.
                return False
    return True


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--feature", required=True)
    parser.add_argument("--target", required=True)
    parser.add_argument("--phase", choices=("deploy-test", "release-validation"), default="deploy-test")
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args(argv)
    if not SAFE_NAME.fullmatch(args.feature) or not SAFE_NAME.fullmatch(args.target):
        parser.error("feature and target must be safe names")
    command = args.command[1:] if args.command[:1] == ["--"] else args.command
    if not command:
        parser.error("missing validation command after --")
    try:
        branch = git("symbolic-ref", "--short", "HEAD")
        commit = git("rev-parse", "HEAD")
        evidence_branch = git("symbolic-ref", "--short", "HEAD",
                              cwd=STATE / "development-evidences/repo")
    except (OSError, subprocess.CalledProcessError):
        print("BLOCKED: Git branch, commit or evidence checkout unavailable", file=sys.stderr)
        return 2
    if not re.fullmatch(r"[0-9a-f]{40}", commit):
        return 2
    # The publisher only ever pushes its checked-out evidence branch.
    if evidence_branch != "main":
        print("BLOCKED: unexpected evidence repository branch", file=sys.stderr)
        return 2

    now = datetime.now(timezone.utc)
    run_id = now.strftime("%H%M%S") + "-" + uuid.uuid4().hex[:8]
    safe_branch = re.sub(r"[^a-zA-Z0-9_.-]", "-", branch)
    relative = (f"CodexBridge/{args.feature}/{safe_branch}/"
                f"{now:%Y-%m-%d}/{run_id}/manifest.json")
    log = STATE / "codexbridge/deploy-test-logs" / f"{run_id}.log"
    code, duration = run_validation(command, log_path=log)
    report = {
        "schema": 1, "project": "CodexBridge", "feature": args.feature,
        "branch": branch, "commit": commit, "target": args.target,
        "phase": args.phase, "timestamp_utc": now.isoformat(),
        "run_id": run_id, "status": "pass" if code == 0 else "fail",
        "exit_code": code, "duration_seconds": duration,
        "error_category": "none" if code == 0 else "other",
        "log_local_only": True, "secrets_included": False,
    }
    try:
        confirmed = publish(report, relative)
    except (OSError, subprocess.TimeoutExpired):
        confirmed = False
    if not confirmed:
        print("BLOCKED: validation evidence not confirmed on remote; check shared outbox",
              file=sys.stderr)
        print(f"LOCAL_LOG={log}")
        return 2
    print(f"RESULT={report['status']} EXIT_CODE={code}")
    print(f"EVIDENCE_REPO={EVIDENCE_REPO}")
    print(f"EVIDENCE_BRANCH={evidence_branch}")
    print(f"EVIDENCE_PATH={relative}")
    print(f"EVIDENCE_URL={EVIDENCE_REPO}/blob/{evidence_branch}/{relative}")
    print(f"LOCAL_LOG={log}")
    return 0 if code == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
