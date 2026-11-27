#!/usr/bin/env python3
"""Canonical operator entry point for Frida Gateway code-only deployments.

Examples:
  python3 scripts/deploy_gateway.py --check
  python3 scripts/deploy_gateway.py --apply
  python3 scripts/deploy_gateway.py --status DEPLOY_ID
  python3 scripts/deploy_gateway.py --resume DEPLOY_ID

No interactive SSH PTY. The remote execution runs independently under systemd.
Only a verified, explicit code-only manifest is supported in this revision.
Schema/migration deployments are deliberately rejected pending a separate gate.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import getpass
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import time
import uuid

ROOT = Path(__file__).resolve().parents[1]
STATE = Path(os.environ.get("XDG_STATE_HOME", str(Path.home() / ".local/state")))
JOBS = STATE / "codexbridge/gateway-deploy/jobs"
PUBLISHER = STATE / "development-evidences/repo/publisher.py"
HOST = "esteban@frida.inovacaosistemas.com.br"
PORT = "2200"
GATEWAY_ROOT = "/opt/codex-bridge"
SOURCE_ROOT = Path("gateway")
MANIFEST_FILE = ROOT / "deploy/gateway-release.json"
RUNNER_FILE = ROOT / "scripts/gateway_deploy_worker.py"
ID_RE = re.compile(r"^gw-[0-9]{8}T[0-9]{6}Z-[a-f0-9]{8}$")
SHA_RE = re.compile(r"^[a-f0-9]{64}$")


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def run(argv: list[str], *, stdin: str | None = None, timeout: int = 30) -> subprocess.CompletedProcess[str]:
    return subprocess.run(argv, input=stdin, text=True, capture_output=True,
                          timeout=timeout, check=False)


def ssh(command: str, *, stdin: str | None = None, timeout: int = 30) -> subprocess.CompletedProcess[str]:
    return run(["ssh", "-T", "-o", "BatchMode=yes" if stdin is None else "BatchMode=no",
                "-o", "ConnectTimeout=10", "-p", PORT, HOST, command],
               stdin=stdin, timeout=timeout)


def file_path(job_id: str) -> Path:
    if not ID_RE.fullmatch(job_id):
        raise ValueError("bad_deployment_id")
    return JOBS / (job_id + ".json")


def read_manifest() -> dict:
    data = json.loads(MANIFEST_FILE.read_text(encoding="utf-8"))
    if data.get("schema") != 1 or data.get("target") != "frida" or data.get("profile") != "code-only":
        raise ValueError("unsupported_release_profile")
    entries = data.get("files")
    if not isinstance(entries, list) or not entries or len(entries) > 25:
        raise ValueError("invalid_release_files")
    paths = set()
    for entry in entries:
        if set(entry) != {"path", "previous_sha256", "target_sha256"}:
            raise ValueError("invalid_manifest_entry")
        name = entry["path"]
        if (not isinstance(name, str) or
                not name.startswith("gateway/") or
                name.startswith("gateway/../") or
                ".." in Path(name).parts or
                name in paths or
                not SHA_RE.fullmatch(entry["previous_sha256"]) or
                not SHA_RE.fullmatch(entry["target_sha256"])):
            raise ValueError("invalid_release_path_or_sha")
        paths.add(name)
        source = ROOT / name
        if source.is_symlink() or not source.is_file():
            raise ValueError("missing_release_source")
        if sha(source.read_bytes()) != entry["target_sha256"]:
            raise ValueError("source_sha_mismatch")
        compile(source.read_bytes(), name, "exec")
    return data


def git(*args: str) -> str:
    return subprocess.check_output(["git", "-C", str(ROOT), *args],
                                   text=True, stderr=subprocess.DEVNULL).strip()


def save(record: dict) -> None:
    JOBS.mkdir(parents=True, exist_ok=True, mode=0o700)
    path = file_path(record["id"])
    temp = path.with_suffix(".new")
    temp.write_text(json.dumps(record, sort_keys=True, indent=2) + "\n")
    os.chmod(temp, 0o600)
    os.replace(temp, path)


def load(job_id: str) -> dict:
    return json.loads(file_path(job_id).read_text())


def remote_dir(job_id: str) -> str:
    file_path(job_id)
    return "codexbridge-staging/" + job_id


def preflight() -> tuple[dict, str, str]:
    manifest = read_manifest()
    if not RUNNER_FILE.is_file():
        raise ValueError("missing_deploy_worker")
    if git("status", "--porcelain", "--", "gateway", "deploy/gateway-release.json",
           "scripts/deploy_gateway.py", "scripts/gateway_deploy_worker.py"):
        raise ValueError("uncommitted_release_changes")
    branch = git("branch", "--show-current") or "detached"
    commit = git("rev-parse", "HEAD")
    return manifest, branch, commit


def stage(job: dict) -> None:
    location = remote_dir(job["id"])
    directory = JOBS / job["id"]
    directory.mkdir(parents=True, mode=0o700)
    manifest = read_manifest()
    local_manifest = directory / "manifest.json"
    local_manifest.write_text(json.dumps({
        "schema": 1, "target": "frida", "profile": "code-only",
        "commit": job["commit"], "files": manifest["files"],
    }, sort_keys=True))
    with tempfile.TemporaryDirectory(prefix="gw-bundle-") as scratch:
        root = Path(scratch)
        shutil.copy2(RUNNER_FILE, root / "worker.py")
        shutil.copy2(local_manifest, root / "manifest.json")
        for item in manifest["files"]:
            dest = root / item["path"]
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(ROOT / item["path"], dest)
        check = ssh("mkdir -p ~/" + location + " && chmod 700 ~/" + location)
        if check.returncode != 0:
            raise RuntimeError("stage_ssh_failure")
        files = [root / "worker.py", root / "manifest.json"]
        files.extend(root / x["path"] for x in manifest["files"])
        for source in files:
            path = source.relative_to(root).as_posix()
            parent = "/".join(path.split("/")[:-1])
            if parent:
                mk = ssh("mkdir -p ~/" + location + "/" + parent)
                if mk.returncode != 0:
                    raise RuntimeError("stage_directory_failure")
            transfer = run(["scp", "-q", "-P", PORT, str(source),
                            HOST + ":" + location + "/" + path], timeout=35)
            if transfer.returncode != 0:
                raise RuntimeError("stage_scp_failure")


def start_detached(job: dict) -> None:
    location = remote_dir(job["id"])
    unit = "codexbridge-deploy-" + job["id"].replace("gw-", "")
    # sudo authorization goes over SSH stdin, never argv, logs or env.
    base = "sudo -n systemd-run --quiet --collect --unit=" + unit + (
        " /usr/bin/python3 /home/esteban/" + location + "/worker.py"
        " /home/esteban/" + location
    )
    result = ssh(base)
    if result.returncode == 0:
        return
    # Non-interactive stdin avoids tying the job to a terminal's lifetime.
    password = getpass.getpass("Senha sudo do frida (somente memória): ")
    try:
        command = base.replace("sudo -n ", "sudo -S -p '' ", 1)
        result = ssh(command, stdin=password + "\n")
    finally:
        password = ""
    if result.returncode != 0:
        raise RuntimeError("remote_start_failed")


def fetch_receipt(job: dict) -> dict | None:
    location = remote_dir(job["id"])
    dest = JOBS / job["id"] / "result.json"
    retrieved = run(["scp", "-q", "-P", PORT, HOST + ":" + location + "/result.json",
                     str(dest)], timeout=20)
    if retrieved.returncode != 0:
        return None
    data = json.loads(dest.read_text())
    if not isinstance(data, dict) or data.get("id") != job["id"]:
        raise ValueError("invalid_remote_receipt")
    if data.get("status") not in {"deployed", "already_current", "failed"}:
        raise ValueError("invalid_remote_status")
    if data.get("rollback") not in {"not_needed", "success", "failed"}:
        raise ValueError("invalid_rollback_status")
    if type(data.get("healthy")) is not bool:
        raise ValueError("invalid_health_flag")
    if data.get("reason") not in {
        "none", "invalid_manifest", "source_mismatch", "baseline_unknown",
        "preflight_unhealthy", "backup_exists", "apply_failed",
        "restart_failed", "post_apply_unhealthy", "rollback_failed",
        "invalid_stage", "invalid_target", "deploy_locked", "fatal_error",
    }:
        raise ValueError("invalid_remote_reason")
    return {key: data[key] for key in ("id", "status", "rollback", "healthy", "reason")}


def publish(job: dict) -> bool:
    if not PUBLISHER.is_file():
        return False
    relative = ("CodexBridge/gateway-deploy/" + job["id"] + "/manifest.json")
    report = {
        "schema": 1, "project": "CodexBridge", "feature": "gateway-deploy",
        "target": "frida", "deployment_id": job["id"],
        "commit": job["commit"], "branch": job["branch"],
        "status": "pass" if job["state"] == "success" else "fail",
        "reason": job.get("reason", "unknown"),
        "rollback": job.get("rollback", "not_needed"),
        "health_checked": job.get("healthy", False),
        "files": job["files"],
        "logs_local_only": True, "secrets_included": False,
    }
    with tempfile.TemporaryDirectory() as scratch:
        envelope = Path(scratch) / "evidence.json"
        envelope.write_text(json.dumps({
            "relative_path": relative, "report": report
        }, sort_keys=True))
        for args in (["enqueue", "--file", str(envelope)], ["flush"]):
            result = run([sys.executable, str(PUBLISHER), *args], timeout=150)
            if result.returncode != 0:
                return False
            if args[0] == "flush" and "published=" + relative not in result.stdout.splitlines():
                return False
    return True


def reconcile(job: dict) -> int:
    receipt = fetch_receipt(job)
    if receipt is None:
        job["state"] = "remote_pending_or_unreachable"
        save(job)
        print("DEPLOY_ID=" + job["id"])
        print("DEPLOY_STATE=remote_pending_or_unreachable")
        print("Use --resume " + job["id"] + "; NEVER start a second deploy.")
        return 3
    job.update(
        state="success" if receipt["status"] in {"deployed", "already_current"} and
                           receipt["healthy"] else "failed",
        reason=receipt["reason"],
        rollback=receipt["rollback"],
        healthy=receipt["healthy"],
        remote_status=receipt["status"],
    )
    save(job)
    try:
        published = publish(job)
    except (OSError, ValueError, subprocess.TimeoutExpired):
        published = False
    job["evidence"] = "published" if published else "pending"
    save(job)
    print("DEPLOY_ID=" + job["id"])
    print("DEPLOY_STATE=" + job["state"])
    print("ROLLBACK=" + job["rollback"])
    print("EVIDENCE=" + job["evidence"])
    return 0 if job["state"] == "success" and published else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--check", action="store_true")
    group.add_argument("--apply", action="store_true")
    group.add_argument("--status", metavar="DEPLOY_ID")
    group.add_argument("--resume", metavar="DEPLOY_ID")
    args = parser.parse_args()
    try:
        if args.status or args.resume:
            job = load(args.status or args.resume)
            if args.status:
                print(json.dumps(job, sort_keys=True, indent=2))
                return 0
            # A locally final outcome may only need evidence retry.
            if job.get("state") in {"success", "failed"} and job.get("evidence") == "published":
                return 0 if job["state"] == "success" else 1
            if job.get("state") in {"success", "failed"}:
                try:
                    ok = publish(job)
                except (OSError, ValueError, subprocess.TimeoutExpired):
                    ok = False
                job["evidence"] = "published" if ok else "pending"
                save(job)
                return 0 if ok and job["state"] == "success" else 1
            return reconcile(job)
        manifest, branch, commit = preflight()
        if not args.apply:
            print("PREFLIGHT=OK")
            print("MODE=CHECK_ONLY")
            print("COMMIT=" + commit)
            print("FILES=" + str(len(manifest["files"])))
            return 0
        ident = "gw-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:8]
        job = {
            "id": ident, "state": "preparing", "branch": branch, "commit": commit,
            "files": [entry["path"] for entry in manifest["files"]],
            "evidence": "pending",
        }
        save(job)
        print("DEPLOY_ID=" + ident, flush=True)
        try:
            stage(job)
            job["state"] = "staged"
            save(job)
            start_detached(job)
            job["state"] = "remote_started"
            save(job)
            # Polling only; termination of this process does not terminate
            # the systemd transient service on frida.
            for _ in range(40):
                try:
                    receipt = fetch_receipt(job)
                    if receipt is not None:
                        return reconcile(job)
                except (OSError, subprocess.TimeoutExpired):
                    pass
                time.sleep(3)
            return reconcile(job)
        except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired) as exc:
            # If SSH terminated while systemd-run was starting, do not
            # assume the remote job didn't start. Never retry launch here.
            job["state"] = "remote_pending_or_unreachable" if job["state"] == "staged" else "failed"
            job["reason"] = type(exc).__name__
            save(job)
            if job["state"] == "failed":
                try:
                    job["evidence"] = "published" if publish(job) else "pending"
                except (OSError, ValueError, subprocess.TimeoutExpired):
                    job["evidence"] = "pending"
                save(job)
            print("DEPLOY_STATE=" + job["state"])
            print("Use --resume " + ident + " to recover the result.")
            return 1
    except (OSError, ValueError, subprocess.CalledProcessError, json.JSONDecodeError) as exc:
        print("BLOCKED=" + type(exc).__name__, file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
