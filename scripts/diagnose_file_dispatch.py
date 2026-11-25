#!/usr/bin/env python3
"""Diagnose the actual systemd --user Agent's deterministic dispatch configuration.

Read-only: no command is executed and no inbox item is created.
Publish a sanitized result through the existing evidence publisher.
"""
from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import secrets
import shlex
import stat
import subprocess
import sys

# When invoked as "python scripts/..." Python puts scripts/ first on sys.path.
# Prefer this checkout, not a possibly older editable installation elsewhere.
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

INSPECTION_STAGE = "initial"

def inspect_config() -> tuple[list[str], bool, bool]:
    global INSPECTION_STAGE
    INSPECTION_STAGE = "systemd_environment"
    env = subprocess.run(
        ["systemctl", "--user", "show", "codex-bridge-agent.service",
         "--property=Environment", "--value"],
        capture_output=True, text=True, check=True
    ).stdout.strip()
    # Systemd show emits KEY=VALUE tokens; no values are printed.
    settings = dict(token.split("=", 1) for token in shlex.split(env)
                    if "=" in token)
    for key, val in settings.items():
        if key.startswith("CODEX_BRIDGE_AGENT_"):
            os.environ[key] = val
    INSPECTION_STAGE = "imports"
    from agent.codex_bridge_agent.config import AgentSettings, load_agent_projects
    from agent.codex_bridge_agent.service import _configured_capabilities
    from shared.protocol import Capability
    INSPECTION_STAGE = "settings"
    config = AgentSettings()
    problems = []
    def check(condition: bool, label: str):
        if not condition:
            problems.append(label)
    INSPECTION_STAGE = "projects"
    projects = load_agent_projects(config.allowed_projects_file)
    project = projects.get("codexbridge")
    check(project is not None, "project_not_allowlisted")
    if project is not None:
        check("test" in [str(m.value if hasattr(m, "value") else m)
                         for m in project.allowed_modes], "local_test_not_allowed")
    INSPECTION_STAGE = "capabilities"
    check(Capability.TEST in _configured_capabilities(config),
          "local_test_capability_missing")
    INSPECTION_STAGE = "file_executor_paths"
    config_path = getattr(config, "file_executor_config_file", None)
    inbox_path = getattr(config, "file_executor_inbox", None)
    if not hasattr(config, "file_executor_config_file"):
        problems.append("missing_agent_setting_config_file")
    if not hasattr(config, "file_executor_inbox"):
        problems.append("missing_agent_setting_inbox")
    conf = Path(config_path) if config_path else None
    inbox = Path(inbox_path) if inbox_path else None
    check(conf is not None, "executor_config_unset")
    check(inbox is not None, "executor_inbox_unset")
    data = None
    INSPECTION_STAGE = "operator_configuration"
    if conf is not None:
        check(conf.is_file() and not conf.is_symlink(), "executor_config_missing_or_link")
        if conf.is_file() and not conf.is_symlink():
            check(not (conf.stat().st_mode & 0o022), "executor_config_writable")
            try:
                data = json.loads(conf.read_text())
            except (OSError, ValueError):
                problems.append("executor_config_invalid_json")
    if data is not None:
        check(data.get("project") == "codexbridge", "config_project_mismatch")
        check(data.get("branch") == "feature/file-instruction-ws-bridge",
              "config_branch_mismatch")
        check("unit-tests" in data.get("profiles", {}), "profile_missing")
        if project is not None:
            check(Path(data.get("root", "/unlikely")).resolve() ==
                  Path(project.path).resolve(), "workspace_mismatch")
    INSPECTION_STAGE = "inbox_permissions"
    if inbox is not None:
        check(inbox.is_dir() and not inbox.is_symlink(), "inbox_missing_or_link")
        if inbox.is_dir():
            check(not (inbox.stat().st_mode & 0o077), "inbox_not_private")
    return problems, bool(env), project is not None


def main() -> int:
    try:
        problems, service_detected, project_allowlisted = inspect_config()
        exception_type = None
    except Exception as exc:
        # Never publish exception messages, which may contain local paths or secrets.
        problems, service_detected, project_allowlisted = ["diagnostic_exception"], False, False
        exception_type = type(exc).__name__
    report = {
        "schema": 1, "project": "CodexBridge", "feature": "file-dispatch-config",
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "status": "success" if not problems else "failed",
        "diagnostic": {"checks_failed": problems,
                       "exception_type": exception_type,
                       "exception_stage": INSPECTION_STAGE if exception_type else None,
                       "service_config_detected": service_detected,
                       "project_allowlisted": project_allowlisted}
    }
    relative = ("CodexBridge/file-dispatch-config/"
                + datetime.now(timezone.utc).strftime("%Y-%m-%d/%Y%m%dT%H%M%SZ-")
                + secrets.token_hex(4) + "/manifest.json")
    publisher = Path.home() / ".local/state/development-evidences/repo/publisher.py"
    out = Path.home() / ".local/state/codexbridge"
    out.mkdir(parents=True, exist_ok=True, mode=0o700)
    envelope = out / ("dispatch-diagnostic-" + secrets.token_hex(8) + ".json")
    envelope.write_text(json.dumps({"relative_path": relative, "report": report}) + "\n")
    envelope.chmod(0o600)
    try:
        if not publisher.is_file():
            print("EVIDENCE_PUBLICATION=unavailable")
            return 2
        enqueue = subprocess.run(
            [sys.executable, str(publisher), "enqueue", "--file", str(envelope)],
            capture_output=True, timeout=30
        )
        if enqueue.returncode:
            print("EVIDENCE_PUBLICATION=enqueue_failed")
            return 2
        flushed = subprocess.run(
            [sys.executable, str(publisher), "flush"], capture_output=True, timeout=120
        )
        published = flushed.returncode == 0 and (
            "published=" + relative).encode() in flushed.stdout.splitlines()
        print("DIAG_STATUS=" + report["status"])
        print("EVIDENCE_PUBLICATION=" + ("published" if published else "failed"))
        return 0 if published and not problems else 3
    finally:
        envelope.unlink(missing_ok=True)

if __name__ == "__main__":
    raise SystemExit(main())
