#!/usr/bin/env python3
"""Validate developer-owned Worker installation and publish sanitized evidence."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import uuid
from datetime import datetime, timezone

HOME = Path.home()
STATE = Path(os.environ.get("XDG_STATE_HOME", str(HOME / ".local/state"))) / "codexbridge-worker"
CONFIG = Path(os.environ.get("XDG_CONFIG_HOME", str(HOME / ".config"))) / "codexbridge-worker"
PUBLISHER = HOME / ".local/state/development-evidences/repo/publisher.py"

def run(args, timeout=30):
    try:
        p = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
        return p.returncode, p.stdout
    except (OSError, subprocess.TimeoutExpired):
        return 125, ""

def main():
    now = datetime.now(timezone.utc)
    id = now.strftime("%H%M%S") + "-" + uuid.uuid4().hex[:8]
    checks = {}
    rc, output = run(["systemctl", "--user", "is-enabled", "codexbridge-worker"])
    checks["user_unit_present"] = rc in (0, 1) and output.strip() in ("enabled", "disabled", "static")
    rc, _ = run(["systemctl", "--user", "is-active", "--quiet", "codexbridge-worker"])
    checks["user_unit_inactive"] = rc != 0
    rc, _ = run(["systemctl", "is-active", "--quiet", "codexbridge-worker"])
    checks["legacy_unit_inactive"] = rc != 0
    checks["state_migrated"] = (STATE / "state.json").is_file()
    checks["machine_credential_migrated"] = (CONFIG / "worker-token").is_file()
    checks["machine_credential_private"] = ((CONFIG / "worker-token").stat().st_mode & 0o077) == 0 if checks["machine_credential_migrated"] else False
    rc, output = run(["git", "ls-remote", "git@github.com:EDortta/CodexBridge.git",
                      "refs/heads/codexbridge-control"])
    checks["developer_git_ssh"] = rc == 0 and "refs/heads/codexbridge-control" in output
    checks["user_context"] = os.geteuid() != 0
    status = "pass" if all(checks.values()) else "attention"
    report = {"schema": 1, "project": "CodexBridge", "feature": "worker-user-preflight",
              "branch": "development", "run_id": id, "timestamp_utc": now.isoformat(),
              "status": status, "checks": checks, "secrets_included": False}
    print(json.dumps(report, indent=2))
    if not PUBLISHER.is_file():
        print("evidence publisher missing", file=sys.stderr)
        return 2
    envelope = {"relative_path": f"CodexBridge/worker-user-preflight/development/{now:%Y-%m-%d}/{id}/manifest.json",
                "report": report}
    with tempfile.TemporaryDirectory() as d:
        path = Path(d) / "envelope.json"
        path.write_text(json.dumps(envelope))
        for cmd in (["enqueue", "--file", str(path)], ["flush"]):
            rc, _ = run([sys.executable, str(PUBLISHER), *cmd], timeout=90)
            if rc:
                print("publisher failed: " + cmd[0], file=sys.stderr)
                return 2
    return 0 if status == "pass" else 1

if __name__ == "__main__":
    raise SystemExit(main())
