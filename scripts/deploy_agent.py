#!/usr/bin/env python3
"""Canonical Agent deploy on devel3. No independent foreground Agent process.

  python3 scripts/deploy_agent.py --check
  python3 scripts/deploy_agent.py --apply
  python3 scripts/deploy_agent.py --status ag-...
  python3 scripts/deploy_agent.py --resume ag-...

The current operator config pins the branch/root. This bounded release keeps
those unchanged and creates a local release commit in the approved worktree.
Any interruption is reconciled by deployment ID, never by running --apply again.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
STATE = Path.home() / ".local/state/codexbridge/agent-deploy"
STAGES = STATE / "stages"
JOBS = STATE / "jobs"
PUBLISHER = Path.home() / ".local/state/development-evidences/repo/publisher.py"
ACTIVE = Path("/home/esteban/Sync/Projects/AI/CodexBridge-agent")
SERVICE = "codex-bridge-agent.service"
BRANCH = "feature/file-instruction-ws-bridge"
FILES = ("agent/codex_bridge_agent/file_executor.py",
         "agent/codex_bridge_agent/file_ws_adapter.py")
ID = re.compile(r"^ag-[0-9]{8}T[0-9]{6}Z-[a-f0-9]{8}$")


def cmd(*args: str, timeout: int = 30) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, text=True, capture_output=True, timeout=timeout,
                          check=False)


def required(*args: str) -> str:
    r = cmd(*args)
    if r.returncode:
        raise RuntimeError("command_failed")
    return r.stdout.strip()


def git(path: Path, *args: str) -> str:
    return required("git", "-C", str(path), *args)


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def service_property(name: str) -> str:
    return required("systemctl", "--user", "show", SERVICE, "-p", name, "--value")


def source_bytes(commit: str, name: str) -> bytes:
    r = subprocess.run(["git", "-C", str(ROOT), "show", f"{commit}:{name}"],
                       capture_output=True, timeout=30, check=False)
    if r.returncode:
        raise RuntimeError("source_commit_unavailable")
    return r.stdout


def preflight() -> dict:
    if service_property("ActiveState") != "active":
        raise RuntimeError("agent_inactive")
    pid = service_property("MainPID")
    if not pid.isdecimal() or int(pid) <= 0:
        raise RuntimeError("invalid_main_pid")
    cwd = Path(os.readlink("/proc/" + pid + "/cwd")).resolve(strict=True)
    if cwd != ACTIVE.resolve(strict=True):
        raise RuntimeError("active_worktree_mismatch")
    if service_property("WorkingDirectory") != str(cwd):
        raise RuntimeError("systemd_worktree_mismatch")
    if git(cwd, "branch", "--show-current") != BRANCH:
        raise RuntimeError("active_branch_mismatch")
    if git(cwd, "status", "--porcelain"):
        raise RuntimeError("worktree_dirty")
    config = Path.home() / ".config/codexbridge/file-executor.json"
    if config.is_symlink() or not config.is_file():
        raise RuntimeError("operator_config_missing")
    cfg = json.loads(config.read_text())
    if (cfg.get("branch") != BRANCH or
            Path(cfg.get("root", "")).resolve(strict=True) != cwd):
        raise RuntimeError("operator_config_mismatch")
    source_commit = git(ROOT, "rev-parse", "HEAD")
    if git(ROOT, "status", "--porcelain", "--", "agent", "scripts/deploy_agent.py",
           "scripts/agent_release_worker.py"):
        raise RuntimeError("source_dirty")
    expected = {}
    original = {}
    for name in FILES:
        blob = source_bytes(source_commit, name)
        compile(blob, name, "exec")
        expected[name] = sha(blob)
        current = cwd / name
        if current.is_symlink() or not current.is_file():
            raise RuntimeError("invalid_live_file")
        actual = current.read_bytes()
        if actual != source_bytes(git(cwd, "rev-parse", "HEAD"), name):
            raise RuntimeError("live_file_mismatch")
        original[name] = sha(actual)
    if not any(expected[name] != original[name] for name in FILES):
        raise RuntimeError("no_agent_changes")
    return {
        "active_root": str(cwd), "active_branch": BRANCH,
        "baseline_commit": git(cwd, "rev-parse", "HEAD"),
        "source_commit": source_commit,
        "baseline_sha256": original,
        "desired_sha256": expected,
        "files": list(FILES),
    }


def path_for(job_id: str) -> Path:
    if not ID.fullmatch(job_id):
        raise ValueError("invalid_deploy_id")
    return JOBS / (job_id + ".json")


def save(job: dict) -> None:
    JOBS.mkdir(parents=True, exist_ok=True, mode=0o700)
    target = path_for(job["id"])
    tmp = target.with_suffix(".tmp")
    with tmp.open("w") as output:
        json.dump(job, output, sort_keys=True, indent=2)
        output.write("\n")
    os.chmod(tmp, 0o600)
    os.replace(tmp, target)


def load(job_id: str) -> dict:
    return json.loads(path_for(job_id).read_text())


def stage(job: dict, manifest: dict) -> Path:
    directory = STAGES / job["id"]
    directory.mkdir(parents=True, mode=0o700)
    (directory / "manifest.json").write_text(json.dumps({
        "schema": 1, "profile": "agent-pr145", **manifest,
    }, sort_keys=True))
    for name in FILES:
        dest = directory / name
        dest.parent.mkdir(parents=True, exist_ok=True)
        data = source_bytes(manifest["source_commit"], name)
        if sha(data) != manifest["desired_sha256"][name]:
            raise RuntimeError("staging_hash_mismatch")
        dest.write_bytes(data)
    worker = ROOT / "scripts/agent_release_worker.py"
    (directory / "worker.py").write_bytes(worker.read_bytes())
    return directory


def start(job: dict, directory: Path) -> None:
    unit = "codexbridge-agent-deploy-" + job["id"].replace("ag-", "")
    r = cmd("systemd-run", "--user", "--quiet", "--collect",
            "--unit=" + unit, sys.executable,
            str(directory / "worker.py"), str(directory))
    if r.returncode:
        # The start attempt may have succeeded despite a lost response.
        # Reconcile by ID; NEVER rerun systemd-run automatically.
        raise RuntimeError("start_unconfirmed")


def fetch(job: dict) -> dict | None:
    file = STAGES / job["id"] / "result.json"
    if not file.exists():
        return None
    result = json.loads(file.read_text())
    if result.get("id") != job["id"]:
        raise ValueError("receipt_id_mismatch")
    if result.get("status") not in {"deployed", "failed"}:
        raise ValueError("invalid_receipt_status")
    if result.get("reason") not in {
        "none", "preflight", "manifest_invalid", "root_mismatch",
        "branch_mismatch", "baseline_mismatch", "worktree_dirty",
        "service_inactive", "service_worktree_mismatch", "config_invalid",
        "config_mismatch", "source_invalid", "source_mismatch",
        "installed_mismatch", "apply_failed", "rollback_failed",
        "worker_error", "deploy_locked", "lock_error",
    }:
        raise ValueError("invalid_receipt_reason")
    if result.get("rollback") not in {"success", "failed", "not_needed"}:
        raise ValueError("invalid_receipt_rollback")
    if type(result.get("service_active")) is not bool or type(result.get("ws_verified")) is not bool:
        raise ValueError("invalid_receipt_flags")
    return {key: result[key] for key in (
        "id", "status", "reason", "rollback", "service_active", "ws_verified"
    )}


def publish(job: dict) -> bool:
    if not PUBLISHER.is_file():
        return False
    relative = "CodexBridge/agent-deploy/" + job["id"] + "/manifest.json"
    report = {
        "schema": 1, "project": "CodexBridge", "feature": "agent-deploy",
        "deployment_id": job["id"], "target": "devel3",
        "source_commit": job["source_commit"],
        "baseline_commit": job["baseline_commit"],
        "sha256": job["hashes"],
        "status": "pass" if job["state"] == "success" else "fail",
        "reason": job.get("reason", "unknown"),
        "rollback": job.get("rollback", "not_needed"),
        "service_active": job.get("service_active", False),
        "ws_verified": False,
        "logs_local_only": True, "secrets_included": False,
    }
    tmp_dir = STATE / "evidence"
    tmp_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    envelope = tmp_dir / (job["id"] + ".json")
    envelope.write_text(json.dumps({"relative_path": relative, "report": report}))
    os.chmod(envelope, 0o600)
    for args in (["enqueue", "--file", str(envelope)], ["flush"]):
        completed = cmd(sys.executable, str(PUBLISHER), *args, timeout=160)
        if completed.returncode != 0:
            return False
        if args[0] == "flush" and ("published=" + relative) not in completed.stdout.splitlines():
            return False
    return True


def reconcile(job: dict) -> int:
    result = fetch(job)
    if result is None:
        job["state"] = "pending"
        save(job)
        print("DEPLOY_ID=" + job["id"])
        print("DEPLOY_STATE=pending")
        print("Use --resume with same ID; do not run --apply again.")
        return 3
    job.update(
        state="success" if result["status"] == "deployed" and result["service_active"] else "failed",
        reason=result["reason"], rollback=result["rollback"],
        service_active=result["service_active"],
    )
    save(job)
    try:
        confirmed = publish(job)
    except (OSError, RuntimeError, subprocess.TimeoutExpired):
        confirmed = False
    job["evidence"] = "published" if confirmed else "pending"
    save(job)
    print("DEPLOY_ID=" + job["id"])
    print("DEPLOY_STATE=" + job["state"])
    print("ROLLBACK=" + job["rollback"])
    print("EVIDENCE=" + job["evidence"])
    print("WS_VERIFIED=false")
    return 0 if job["state"] == "success" and confirmed else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--check", action="store_true")
    group.add_argument("--apply", action="store_true")
    group.add_argument("--status", metavar="DEPLOY_ID")
    group.add_argument("--resume", metavar="DEPLOY_ID")
    args = parser.parse_args(argv)
    try:
        if args.status or args.resume:
            job = load(args.status or args.resume)
            if args.status:
                print(json.dumps(job, indent=2, sort_keys=True))
                return 0
            if job.get("state") in {"success", "failed"}:
                if job.get("evidence") == "published":
                    return 0 if job["state"] == "success" else 1
                job["evidence"] = "published" if publish(job) else "pending"
                save(job)
                return 0 if job["state"] == "success" and job["evidence"] == "published" else 1
            return reconcile(job)
        manifest = preflight()
        if not args.apply:
            print("PREFLIGHT=OK")
            print("SOURCE_COMMIT=" + manifest["source_commit"])
            print("BASELINE_COMMIT=" + manifest["baseline_commit"])
            print("FILES=" + str(len(FILES)))
            print("MODE=CHECK_ONLY")
            return 0
        job_id = "ag-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid4().hex[:8]
        job = {"id": job_id, "state": "preparing", "evidence": "pending",
               "source_commit": manifest["source_commit"],
               "baseline_commit": manifest["baseline_commit"],
               "hashes": [
                   {"path": name, "before": manifest["baseline_sha256"][name],
                    "after": manifest["desired_sha256"][name]} for name in FILES
               ]}
        save(job)
        print("DEPLOY_ID=" + job_id, flush=True)
        try:
            directory = stage(job, manifest)
            job["state"] = "staged"
            save(job)
            start(job, directory)
            job["state"] = "running"
            save(job)
            for _ in range(40):
                if fetch(job) is not None:
                    return reconcile(job)
                time.sleep(3)
            return reconcile(job)
        except (OSError, RuntimeError, ValueError, subprocess.TimeoutExpired):
            # A closed terminal or an unacknowledged systemd-run must never
            # trigger a second automatic start.
            job["state"] = "pending"
            save(job)
            print("DEPLOY_STATE=pending")
            print("Use --resume " + job_id)
            return 3
    except (OSError, RuntimeError, ValueError, json.JSONDecodeError,
            subprocess.TimeoutExpired) as exc:
        print("PREFLIGHT=BLOCKED")
        print("REASON=" + (str(exc) if isinstance(exc, RuntimeError) else type(exc).__name__))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
