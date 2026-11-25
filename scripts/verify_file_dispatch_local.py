#!/usr/bin/env python3
"""Exercise the real local file dispatcher once with the user Agent configuration.

Uses the same authorized test profile as submit_file_instruction, never takes
argv or a path from the caller, and publishes a sanitized receipt. No LLM.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import secrets
import shlex
import subprocess
import sys
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

def main() -> int:
    from agent.codex_bridge_agent.config import AgentSettings, load_agent_projects
    from agent.codex_bridge_agent.file_ws_adapter import execute_file_dispatch, FileDispatchDenied

    env = subprocess.run(
        ["systemctl", "--user", "show", "codex-bridge-agent.service",
         "--property=Environment", "--value"],
        check=True, capture_output=True, text=True,
    ).stdout
    for token in shlex.split(env):
        if token.startswith("CODEX_BRIDGE_AGENT_") and "=" in token:
            name, value = token.split("=", 1)
            os.environ[name] = value
    settings = AgentSettings()
    project = load_agent_projects(settings.allowed_projects_file).get("codexbridge")
    now = datetime.now(timezone.utc)
    request_id = "mvp-local-" + now.strftime("%Y%m%dT%H%M%S") + "-" + secrets.token_hex(3)
    instruction = {
        "schemaVersion": 1, "requestId": request_id, "project": "codexbridge",
        "branch": "feature/file-instruction-ws-bridge", "profile": "unit-tests",
    }
    payload = {"project_id": "codexbridge", "engine": "file", "mode": "test",
               "instruction": json.dumps(instruction, separators=(",", ":")),
               "issue_ref": None, "continue_session_id": None}
    safe_denials = {
        "file_executor_not_configured", "file_engine_requires_test",
        "file_engine_excludes_delivery_and_sessions", "invalid_file_instruction",
        "unsafe_operator_config", "bad_operator_config", "project_mismatch",
        "workspace_mismatch", "unsafe_inbox_permissions", "invalid_instruction_type",
        "missing_request_id", "request_id_collision", "project_or_branch_mismatch",
        "profile_not_allowed", "completed_without_receipt", "execution_not_recorded",
    }
    diag = {"requestId": request_id, "status": "failed"}
    if project is None:
        diag["reason"] = "project_not_allowlisted"
    else:
        try:
            receipt = execute_file_dispatch(
                payload, config_path=settings.file_executor_config_file,
                inbox_path=settings.file_executor_inbox,
                approved_project_root=project.path,
            )
            diag.update(status=receipt.get("status", "failed"),
                        exitCode=receipt.get("exitCode"),
                        reason=receipt.get("reason"),
                        timedOut=receipt.get("timedOut", False),
                        profile=receipt.get("profile"))
        except Exception as exc:
            reason = str(exc)
            diag["reason"] = reason if isinstance(exc, FileDispatchDenied) and reason in safe_denials else type(exc).__name__

    # Report only a fixed category; never publish raw test output.
    output = receipt.get("output", "") if "receipt" in locals() else ""
    if isinstance(output, str):
        if "No module named pytest" in output:
            diag["reason"] = "pytest_missing_from_profile_interpreter"
        elif "no tests ran" in output:
            diag["reason"] = "no_tests_collected"
        elif "ERROR collecting" in output or "ImportError while importing test module" in output:
            diag["reason"] = "pytest_collection_error"
        elif " failed" in output and " passed" in output:
            diag["reason"] = "pytest_assertions_failed"
    allowed = {"requestId", "status", "exitCode", "reason", "timedOut", "profile"}
    diag = {k: v for k, v in diag.items() if k in allowed}
    print("FILE_DISPATCH_STATUS=" + str(diag["status"]))
    print("FILE_DISPATCH_REASON=" + str(diag.get("reason", "none")))
    print("FILE_DISPATCH_EXIT_CODE=" + str(diag.get("exitCode", "none")))

    relative = ("CodexBridge/file-dispatch-local/"
                + now.strftime("%Y-%m-%d/%Y%m%dT%H%M%SZ-")
                + secrets.token_hex(4) + "/manifest.json")
    publisher = Path.home() / ".local/state/development-evidences/repo/publisher.py"
    if not publisher.is_file():
        print("EVIDENCE_PUBLICATION=unavailable")
        return 2
    state_dir = Path.home() / ".local/state/codexbridge"
    state_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    envelope = state_dir / ("dispatch-local-" + secrets.token_hex(8) + ".json")
    envelope.write_text(json.dumps({"relative_path": relative, "report": {
        "schema": 1, "project": "CodexBridge", "feature": "file-dispatch-local",
        "timestamp_utc": now.isoformat(), "diagnostic": diag,
        "status": "success" if diag["status"] == "success" else "failed",
    }}) + "\n")
    envelope.chmod(0o600)
    try:
        enqueued = subprocess.run([sys.executable, str(publisher), "enqueue",
                                  "--file", str(envelope)], capture_output=True, timeout=30)
        if enqueued.returncode:
            print("EVIDENCE_PUBLICATION=enqueue_failed")
            return 2
        published = subprocess.run([sys.executable, str(publisher), "flush"],
                                   capture_output=True, timeout=120)
        success = published.returncode == 0 and (
            "published=" + relative).encode() in published.stdout.splitlines()
        print("EVIDENCE_PUBLICATION=" + ("published" if success else "failed"))
        return 0 if success and diag["status"] == "success" else 3
    finally:
        envelope.unlink(missing_ok=True)

if __name__ == "__main__":
    raise SystemExit(main())
