#!/usr/bin/env python3
"""Read-only diagnosis of the Gateway TEST authorization for CodexBridge.

Run through scripts/run_file_ws_evidence.py for local log, sanitized manifest,
and automatic publication to development-evidences. Never prints credentials.
No database mutations and no sudo on the developer's Agent.
"""
from __future__ import annotations

import argparse
import json
import shlex
import subprocess
import sys

REMOTE = r'''
import asyncio
import json
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
        print("HINT=Check SSH access and sudo -n -u codexbridge authorization")
        return 2
    try:
        result = json.loads(proc.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        print("DIAG_STATUS=invalid_remote_response")
        return 2

    print(json.dumps(result, sort_keys=True))
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
