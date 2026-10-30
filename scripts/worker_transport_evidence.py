#!/usr/bin/env python3
"""One-shot sanitized Worker transport checks, published by shared evidence queue.

Execute on devel3 as esteban. No secrets, raw stderr, tokens or request bodies
are included in the manifest. Never starts/restarts the systemd service.
"""
from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import uuid

PUBLISHER = Path.home() / ".local/state/development-evidences/repo/publisher.py"
WATCHER = Path("/opt/codexbridge-worker/scripts/worker_watch.py")
STATE = "/var/lib/codexbridge-worker/state.json"


def command(args, *, timeout=60):
    try:
        result = subprocess.run(args, stdin=subprocess.DEVNULL,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                text=True, timeout=timeout)
        return result.returncode, result.stdout
    except (OSError, subprocess.TimeoutExpired):
        return 125, ""


def main():
    timestamp = datetime.now(timezone.utc)
    runid = timestamp.strftime("%H%M%S") + "-" + uuid.uuid4().hex[:8]
    checks = {}
    checks["worker_installed"] = WATCHER.is_file()
    checks["service_installed"] = Path("/etc/systemd/system/codexbridge-worker.service").is_file()
    code, _ = command(["sudo", "-n", "-u", "codexbridge-worker", "git",
                       "ls-remote", "git@github.com:EDortta/CodexBridge.git",
                       "refs/heads/codexbridge-control"], timeout=30)
    checks["worker_git_ssh"] = "ok" if code == 0 else "failed"
    if checks["worker_installed"]:
        code, output = command(
            ["sudo", "-n", "-u", "codexbridge-worker", "env",
             "CODEXBRIDGE_GITHUB_TOKEN_FILE=", "CODEXBRIDGE_GITHUB_TOKEN=",
             "/usr/bin/python3", str(WATCHER),
             "--state-file", STATE, "--once", "--validate-requests"], timeout=60)
        checks["one_shot_observation"] = "ok" if code == 0 else "failed"
        # Do not publish the command's raw output, as request metadata is not
        # part of the evidence contract and may change in future versions.
    else:
        checks["one_shot_observation"] = "not_installed"
    checks["gateway_lease_required"] = True
    checks["github_api_token_required"] = False
    status = "pass" if (checks["worker_git_ssh"] == "ok"
                       and checks["one_shot_observation"] == "ok") else "attention"
    report = {"schema": 1, "project": "CodexBridge", "feature": "worker-ssh-transport",
              "branch": "development", "timestamp_utc": timestamp.isoformat(),
              "run_id": runid, "status": status, "checks": checks,
              "secrets_included": False}
    print(json.dumps(report, indent=2, sort_keys=True))
    if not PUBLISHER.is_file():
        print("publisher missing; evidence not uploaded", file=sys.stderr)
        return 2
    envelope = {"relative_path": f"CodexBridge/worker-ssh-transport/development/{timestamp:%Y-%m-%d}/{runid}/manifest.json",
                "report": report}
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "envelope.json"
        path.write_text(json.dumps(envelope), encoding="utf-8")
        for command_args in (["enqueue", "--file", str(path)], ["flush"]):
            result = subprocess.run([sys.executable, str(PUBLISHER), *command_args])
            if result.returncode:
                return 2
    return 0 if status == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
