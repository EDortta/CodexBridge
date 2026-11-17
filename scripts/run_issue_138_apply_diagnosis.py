#!/usr/bin/env python3
"""Issue #138: classify failed apply without leaking logs, inspect frida health, publish evidence.

The original output stays local. Only allowlisted error categories and health
booleans are published. This command does not retry the deploy, restart services,
read tokens or alter the remote host.
"""
from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
import uuid

from run_issue_138_baseline_evidence import git, publish, PUBLISHER, ROOT, STATE, EVIDENCE_REPO

FAILED_RUN = "143856-59aa6971"
EXPECTED_RELEASE = "issue138-20261117T143058Z"
ERROR_PATTERNS = {
    "compile": ("Candidate Python syntax check failed",),
    "archive": ("Unexpected archive contents", "Candidate file hash mismatch", "Archive checksum mismatch"),
    "baseline": ("REFUSED: running", "Missing manifest entry", "Missing stage"),
    "discovery": ("OAuth discovery check failed", "refresh grant not advertised"),
    "health": ("Gateway failed health check",),
    "rollback": ("ROLLBACK:", "ROLLBACK_HEALTH="),
    "ssh_auth": ("Permission denied", "sudo: a password is required"),
    "stage": ("Stage incomplete", "Backup target exists"),
    "service": ("Failed to start", "Job for codex-bridge-gateway"),
}


def classify(raw: str) -> dict:
    labels = sorted(name for name, tokens in ERROR_PATTERNS.items()
                    if any(token in raw for token in tokens))
    return {
        "failure_classes": labels or ["unclassified"],
        "rollback_invoked": "ROLLBACK:" in raw,
        "rollback_health_ok": "ROLLBACK_HEALTH=ok" in raw,
        "applied_marker_present": "APPLIED=" in raw,
    }


def inspect_remote() -> dict:
    # Only fixed commands and allowlisted signal values; no remote stdout/logs.
    host = os.environ.get("FRIDA_HOST", "esteban@frida.inovacaosistemas.com.br")
    port = os.environ.get("FRIDA_PORT", "2200")
    if not port.isdigit():
        return {"status": "invalid_port"}
    script = (
        "set -eu; "
        "systemctl is-active --quiet codex-bridge-gateway && echo SERVICE_ACTIVE=1 || echo SERVICE_ACTIVE=0; "
        "curl -fsS --max-time 5 http://127.0.0.1:18080/health >/dev/null 2>&1 && echo HEALTH_OK=1 || echo HEALTH_OK=0; "
        "cd /opt/codex-bridge; "
        "sha256sum gateway/app/main.py gateway/app/api/routes/auth.py "
        "gateway/app/core/config.py gateway/app/core/oauth.py"
    )
    try:
        call = subprocess.run(
            ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=8",
             "-p", port, host, script],
            stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=25,
        )
    except (OSError, subprocess.TimeoutExpired):
        return {"status": "unreachable"}
    if call.returncode:
        return {"status": "unreachable"}
    output = call.stdout
    files = {}
    for line in output.splitlines():
        match = re.fullmatch(r"([0-9a-f]{64})\s+(gateway/app/(?:main.py|api/routes/auth.py|core/config.py|core/oauth.py))", line)
        if match:
            files[match.group(2)] = match.group(1)
    if len(files) != 4:
        return {"status": "incomplete"}
    return {
        "status": "queried",
        "service_active": "SERVICE_ACTIVE=1" in output,
        "health_ok": "HEALTH_OK=1" in output,
        "file_sha256": files,
    }


def main() -> int:
    try:
        branch = git("symbolic-ref", "--short", "HEAD")
        commit = git("rev-parse", "HEAD")
        evidence_branch = git("symbolic-ref", "--short", "HEAD", cwd=PUBLISHER.parent)
        if evidence_branch != "main" or not PUBLISHER.is_file():
            raise ValueError("publisher_unavailable")
    except (OSError, subprocess.CalledProcessError, ValueError):
        print("BLOCKED: evidence checkout invalid", file=sys.stderr)
        return 2
    now = datetime.now(timezone.utc)
    run_id = now.strftime("%H%M%S") + "-" + uuid.uuid4().hex[:8]
    log = STATE / "codexbridge/deploy-test-logs" / (FAILED_RUN + ".log")
    if log.is_file():
        raw = log.read_text(encoding="utf-8", errors="replace")
        failure = classify(raw)
    else:
        failure = {"failure_classes": ["local_log_missing"], "rollback_invoked": False,
                   "rollback_health_ok": False, "applied_marker_present": False}
    remote = inspect_remote()
    safe_branch = re.sub(r"[^a-zA-Z0-9_.-]", "-", branch)
    relative = f"CodexBridge/issue-138-frida-apply-diagnosis/{safe_branch}/{now:%Y-%m-%d}/{run_id}/manifest.json"
    report = {
        "schema": 1,
        "project": "CodexBridge",
        "feature": "issue-138-frida-apply-diagnosis",
        "branch": branch,
        "commit": commit,
        "target": "frida",
        "phase": "deploy-test",
        "timestamp_utc": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "status": "pass" if remote.get("status") == "queried" else "fail",
        "exit_code": 0 if remote.get("status") == "queried" else 1,
        "error_category": "none" if remote.get("status") == "queried" else "remote_unreachable",
        "checks": {
            "source_run_id": FAILED_RUN,
            "release_id": EXPECTED_RELEASE,
            "previous_apply_failure": failure,
            "remote": remote,
            "read_only": True,
            "remote_publication_required": True,
        },
        "detail": "Sanitized read-only post-failure diagnosis; original logs remain local",
    }
    try:
        published = publish(relative, report)
    except (OSError, subprocess.TimeoutExpired):
        published = False
    print("DIAGNOSIS_STATUS=" + report["status"])
    if not published:
        print("EVIDENCE_NOT_CONFIRMED", file=sys.stderr)
        return 2
    print(f"EVIDENCE_URL={EVIDENCE_REPO}/blob/main/{relative}")
    return report["exit_code"]


if __name__ == "__main__":
    raise SystemExit(main())
