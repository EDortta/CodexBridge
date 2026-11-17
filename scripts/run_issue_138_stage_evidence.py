#!/usr/bin/env python3
"""Stage issue #138 patch on frida and publish a sanitized, immutable ACK.

Staging only; no application, service restart, database changes or migrations.
Publishes the exact staged release ID, source commit and test/preflight result.
Raw subprocess diagnostics remain in a private local log.
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

RELEASE = re.compile(r"^STAGED_ONLY=(issue138-[0-9]{8}T[0-9]{6}Z)$", re.MULTILINE)
COMMIT = re.compile(r"^SOURCE_COMMIT=([a-f0-9]{40})$", re.MULTILINE)


def parse_stage_output(raw: str) -> tuple[str, str]:
    releases = RELEASE.findall(raw)
    commits = COMMIT.findall(raw)
    if len(releases) != 1 or len(commits) != 1 or "APPLY_NOT_EXECUTED=1" not in raw:
        raise ValueError("stage_metadata_missing_or_duplicate")
    return releases[0], commits[0]


def main() -> int:
    try:
        branch = git("symbolic-ref", "--short", "HEAD")
        commit = git("rev-parse", "HEAD")
        evidence_branch = git("symbolic-ref", "--short", "HEAD", cwd=PUBLISHER.parent)
        if branch != "fix/issue-138-oauth-session-ux" or evidence_branch != "main" or not PUBLISHER.is_file():
            raise ValueError("unexpected_checkout")
    except (OSError, subprocess.CalledProcessError, ValueError):
        print("BLOCKED: source or evidence checkout is unavailable", file=sys.stderr)
        return 2

    now = datetime.now(timezone.utc)
    run_id = now.strftime("%H%M%S") + "-" + uuid.uuid4().hex[:8]
    directory = STATE / "codexbridge/issue-138/staging"
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    logfile = directory / (run_id + ".log")
    started = time.monotonic()
    with logfile.open("wb") as stream:
        os.chmod(logfile, 0o600)
        try:
            # Both scripts must pass the local syntax gate before staging.
            syntax = subprocess.run(
                ["bash", "-n", "scripts/stage-frida-issue-138.sh",
                 "scripts/apply-frida-issue-138.sh"],
                cwd=ROOT, stdin=subprocess.DEVNULL, stdout=stream,
                stderr=subprocess.STDOUT, timeout=30,
            )
            if syntax.returncode:
                rc = syntax.returncode
            else:
                contract = subprocess.run(
                    [sys.executable, "-m", "pytest", "-q",
                     "tests/unit/test_issue_138_stage_evidence.py",
                     "tests/unit/test_issue_138_baseline_evidence.py"],
                    cwd=ROOT, stdin=subprocess.DEVNULL, stdout=stream,
                    stderr=subprocess.STDOUT, timeout=120,
                )
                if contract.returncode:
                    rc = contract.returncode
                else:
                    stage = subprocess.run(
                        ["bash", "scripts/stage-frida-issue-138.sh"],
                        cwd=ROOT, stdin=subprocess.DEVNULL, stdout=stream,
                        stderr=subprocess.STDOUT, timeout=180,
                    )
                    rc = stage.returncode
        except (OSError, subprocess.TimeoutExpired):
            rc = 125
    duration = round(time.monotonic() - started, 3)
    stage_id = None
    if rc == 0:
        try:
            stage_id, stage_commit = parse_stage_output(logfile.read_text(encoding="utf-8"))
            if stage_commit != commit:
                rc = 1
                stage_id = None
        except (OSError, ValueError, UnicodeDecodeError):
            rc = 1
    status = "pass" if rc == 0 else "fail"
    relative = (
        "CodexBridge/issue-138-frida-stage/fix-issue-138-oauth-session-ux/"
        f"{now:%Y-%m-%d}/{run_id}/manifest.json"
    )
    report = {
        "schema": 1,
        "project": "CodexBridge",
        "feature": "issue-138-frida-stage",
        "branch": branch,
        "commit": commit,
        "target": "frida",
        "phase": "deploy-test",
        "timestamp_utc": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "status": status,
        "exit_code": rc,
        "duration_seconds": duration,
        "error_category": "none" if rc == 0 else "stage_or_syntax",
        "checks": {
            "stage_only": True,
            "apply_not_executed": True,
            "source_commit_matches": rc == 0,
            "release_id": stage_id,
            "remote_publication_required": True,
        },
        "detail": "Staged only; no live Gateway files, DB or systemd service modified",
    }
    try:
        published = publish(relative, report)
    except (OSError, subprocess.TimeoutExpired):
        published = False
    print(f"STAGE_STATUS={status}")
    print(f"LOCAL_LOG={logfile}")
    if not published:
        print("EVIDENCE_NOT_CONFIRMED", file=sys.stderr)
        return 2
    print(f"EVIDENCE_URL={EVIDENCE_REPO}/blob/main/{relative}")
    if stage_id is not None:
        print(f"STAGED_ONLY={stage_id}")
    return 0 if rc == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
