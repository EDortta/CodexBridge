#!/usr/bin/env python3
"""Non-mutating recovery check for one ALREADY completed Agent deployment.

Replays --resume for a published, successful deployment ID. Proves that
recovery does not launch systemd-run, restart the active Agent, advance Git,
rewrite the local receipt, or alter the released module bytes. Does NOT
simulate a client dying during the first deployment; that separate case is
covered by a deterministic fault-injection test.
Use run_file_ws_evidence.py to publish the result of this verification.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts import deploy_agent

FILES = deploy_agent.FILES


class RecoveryError(RuntimeError):
    pass


def checked(*args: str) -> str:
    result = subprocess.run(args, text=True, capture_output=True,
                            check=False, timeout=25)
    if result.returncode:
        raise RecoveryError("command_failed")
    return result.stdout.strip()


def snapshot(job_id: str) -> dict:
    job = deploy_agent.load(job_id)
    if job.get("id") != job_id or job.get("state") != "success" or job.get("evidence") != "published":
        raise RecoveryError("deployment_not_published_success")
    receipt_file = deploy_agent.STAGES / job_id / "result.json"
    if not receipt_file.is_file() or receipt_file.is_symlink():
        raise RecoveryError("receipt_missing")
    receipt = deploy_agent.fetch(job)
    if (receipt is None or receipt["status"] != "deployed"
            or receipt["reason"] != "none"
            or receipt["rollback"] != "not_needed"
            or not receipt["service_active"]):
        raise RecoveryError("invalid_success_receipt")
    if deploy_agent.service_property("ActiveState") != "active":
        raise RecoveryError("agent_inactive")
    pid = deploy_agent.service_property("MainPID")
    if not pid.isdecimal() or int(pid) == 0:
        raise RecoveryError("invalid_agent_pid")
    root = deploy_agent.ACTIVE.resolve(strict=True)
    if checked("git", "-C", str(root), "branch", "--show-current") != deploy_agent.BRANCH:
        raise RecoveryError("branch_changed")
    if checked("git", "-C", str(root), "status", "--porcelain"):
        raise RecoveryError("worktree_dirty")
    digest = {
        name: hashlib.sha256((root / name).read_bytes()).hexdigest()
        for name in FILES
    }
    expected = {item["path"]: item["after"] for item in job["hashes"]}
    if digest != expected:
        raise RecoveryError("release_hashes_mismatch")
    return {
        "pid": int(pid),
        "commit": checked("git", "-C", str(root), "rev-parse", "HEAD"),
        "hashes": digest,
        "receipt_sha256": hashlib.sha256(receipt_file.read_bytes()).hexdigest(),
        "job_sha256": hashlib.sha256(deploy_agent.path_for(job_id).read_bytes()).hexdigest(),
    }


def verify(job_id: str) -> None:
    before = snapshot(job_id)
    completed = subprocess.run(
        [sys.executable, str(deploy_agent.ROOT / "scripts" / "deploy_agent.py"),
         "--resume", job_id],
        capture_output=True, text=True, check=False, timeout=30,
    )
    if completed.returncode != 0:
        raise RecoveryError("resume_not_successful")
    after = snapshot(job_id)
    if before != after:
        raise RecoveryError("resume_modified_live_state")
    print("DEPLOY_ID=" + job_id)
    print("RESUME=IDEMPOTENT")
    print("AGENT_RESTARTED=false")
    print("RELEASE_COMMIT_UNCHANGED=true")
    print("RECEIPT_UNCHANGED=true")
    print("RELEASE_HASHES_UNCHANGED=true")
    print("CHECK=PASS")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--deploy-id", required=True)
    args = parser.parse_args(argv)
    try:
        deploy_agent.path_for(args.deploy_id)
        verify(args.deploy_id)
    except (OSError, ValueError, RecoveryError, json.JSONDecodeError,
            KeyError, subprocess.TimeoutExpired) as exc:
        label = str(exc) if isinstance(exc, RecoveryError) else type(exc).__name__
        print("CHECK=FAILED")
        print("REASON=" + label)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
