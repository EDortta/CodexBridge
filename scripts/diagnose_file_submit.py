#!/usr/bin/env python3
"""Read-only diagnosis of the Gateway TEST authorization for CodexBridge.

Run through scripts/run_file_ws_evidence.py for local log, sanitized manifest,
and automatic publication to development-evidences. Never prints credentials.
No database mutations and no sudo on the developer's Agent.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import secrets
import shlex
import subprocess
import sys

REMOTE = r'''
import asyncio
import json
import os
from pathlib import Path
import subprocess

# Reconstruct the running Gateway's environment and cwd BEFORE importing Settings.
# Read in memory only; no secrets, database URL or paths leave frida.
pid = subprocess.check_output(
    ["systemctl", "show", "-p", "MainPID", "--value", "codex-bridge-gateway.service"],
    text=True,
).strip()
if not pid.isdigit() or int(pid) <= 0:
    print(json.dumps({"status": "gateway_not_running"}))
    raise SystemExit(4)
proc = Path("/proc") / pid
try:
    env_entries = (proc / "environ").read_bytes().split(b"\\0")
    for entry in env_entries:
        if not entry.startswith(b"CODEX_BRIDGE_") or b"=" not in entry:
            continue
        key, value = entry.split(b"=", 1)
        os.environ[key.decode()] = value.decode()
    os.chdir(os.readlink(proc / "cwd"))
except (OSError, UnicodeError):
    print(json.dumps({"status": "gateway_environment_unavailable"}))
    raise SystemExit(4)

from gateway.app.db.session import SessionLocal
from gateway.app.models.entities import ExecutorModel, ProjectModel
from gateway.app.services.store import effective_task_modes

async def inspect():
    async with SessionLocal() as db:
        executor = await db.get(ExecutorModel, "devel3")
        project = await db.get(ProjectModel, "codexbridge")
        if executor is None or project is None:
            return {"status": "missing_registration",
                    "executor_registered": executor is not None,
                    "project_registered": project is not None}
        config = json.loads(project.config_json)
        effective = sorted(mode.value for mode in
                           await effective_task_modes(db, executor, project))
        return {
            "status": "ok" if "test" in effective else "test_denied",
            "executor_enabled": bool(executor.enabled),
            "project_enabled": bool(project.enabled),
            "base_allowed_modes": config.get("allowed_modes", []),
            "effective_allowed_modes": effective,
            "node_binding_present": executor.node_id is not None,
            "test_allowed": "test" in effective,
        }

print(json.dumps(asyncio.run(inspect()), sort_keys=True))
'''



def publish_diagnostic(result: dict) -> str:
    """Publish strictly projected policy facts; do not publish remote stderr."""
    if result.get("status") not in {"ok", "test_denied", "missing_registration", "gateway_not_running", "gateway_environment_unavailable"}:
        return "invalid"
    safe = {"status": result["status"]}
    for key in ("executor_enabled", "project_enabled", "test_allowed",
                "node_binding_present", "executor_registered", "project_registered"):
        if type(result.get(key)) is bool:
            safe[key] = result[key]
    for key in ("base_allowed_modes", "effective_allowed_modes"):
        value = result.get(key)
        if isinstance(value, list) and len(value) <= 20 and all(
            isinstance(v, str) and v in {"analyze", "review", "test", "edit", "implement"}
            for v in value
        ):
            safe[key] = value
    now = datetime.now(timezone.utc)
    relative = (
        "CodexBridge/file-submit-authorization/"
        + now.strftime("%Y-%m-%d/%Y%m%dT%H%M%SZ-")
        + secrets.token_hex(4) + "/manifest.json"
    )
    envelope = {"relative_path": relative, "report": {
        "schema": 1, "project": "CodexBridge", "feature": "file-submit-authorization",
        "timestamp_utc": now.isoformat(),
        "status": "success" if safe["status"] == "ok" else "failed",
        "diagnostic": safe,
        "detail": "Read-only Gateway mode authorization; no secrets or raw logs.",
    }}
    publisher = Path.home() / ".local/state/development-evidences/repo/publisher.py"
    if not publisher.is_file():
        return "publisher_unavailable"
    envelope_path = Path.home() / ".local/state/codexbridge/file-submit-diagnostic.json"
    envelope_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    envelope_path.write_text(json.dumps(envelope, sort_keys=True) + "\n")
    envelope_path.chmod(0o600)
    try:
        put = subprocess.run(
            [sys.executable, str(publisher), "enqueue", "--file", str(envelope_path)],
            capture_output=True, timeout=30
        )
        if put.returncode:
            return "enqueue_failed"
        flushed = subprocess.run(
            [sys.executable, str(publisher), "flush"], capture_output=True, timeout=120
        )
        if flushed.returncode:
            return "flush_failed"
        if ("published=" + relative).encode() in flushed.stdout.splitlines():
            return "published"
        return "not_confirmed"
    except (OSError, subprocess.TimeoutExpired):
        return "publisher_failed"
    finally:
        envelope_path.unlink(missing_ok=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="esteban@frida.inovacaosistemas.com.br")
    parser.add_argument("--port", type=int, default=2200)
    args = parser.parse_args()

    # No shell; execute only a fixed, source-controlled read-only query.
    command = [
        "ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=8",
        "-p", str(args.port), args.host,
        "cd /opt/codex-bridge && "
        "sudo -n -u codexbridge /opt/codex-bridge/.venv/bin/python -c "
        + shlex.quote(REMOTE),
    ]
    try:
        proc = subprocess.run(command, text=True, capture_output=True, timeout=35)
    except (OSError, subprocess.TimeoutExpired) as exc:
        print("DIAG_STATUS=transport_error")
        print("ERROR_TYPE=" + type(exc).__name__)
        return 2

    if proc.returncode:
        print("DIAG_STATUS=remote_read_failed")
        print("SSH_EXIT_CODE=" + str(proc.returncode))
        # Stderr might include sensitive diagnostic values: never publish it.
        print("HINT=Check SSH access, Gateway service identity and process environment read access")
        return 2
    try:
        result = json.loads(proc.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        print("DIAG_STATUS=invalid_remote_response")
        return 2

    print("EVIDENCE_PUBLICATION=" + publish_diagnostic(result))
    print("DIAG_STATUS=" + result.get("status", "unknown"))
    if result.get("status") == "test_denied":
        print("DIAG_STATUS=policy_denied")
        return 3
    if result.get("status") == "ok":
        print("DIAG_STATUS=authorized")
        return 0
    print("DIAG_STATUS=missing_registration")
    return 3


if __name__ == "__main__":
    sys.exit(main())
