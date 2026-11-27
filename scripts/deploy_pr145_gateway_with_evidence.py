#!/usr/bin/env python3
"""LEGACY PR-specific deploy. Use scripts/deploy_gateway.py for every new code-only Gateway release.

Run on devel3 from a checked-out CodexBridge branch containing PR #145:
  python3 scripts/deploy_pr145_gateway_with_evidence.py --apply

SSH and remote sudo may prompt interactively; no credentials are persisted.
The publisher stores a sanitized manifest in development-evidences/main.
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
import tempfile
import time
import uuid

ROOT = Path(__file__).resolve().parents[1]
PROFILE = "pr145-gateway"
HOST = "esteban@frida.inovacaosistemas.com.br"
PORT = "2200"
FILES = ("agent_hub.py", "store.py")
OLD = (
    "24b8a7b51b55ca37a521b957be0cbc7d76bd434a341a344bc3e4574890bd860e",
    "04bf558d25f149c54d81efc072825facd22dc090f424bd1fef60e866234d1487",
)
NEW = (
    "055d5cf6c0f110359ffc42b2c51e7b8638fcad40ae357f62c1fc700ca57afc8f",
    "291d353a0e26c23a5ca31b1f212e245f0c907253f5f728379e14ff33de9ca9f3",
)
STATE = Path(os.environ.get("XDG_STATE_HOME", str(Path.home() / ".local/state")))
PUBLISHER = STATE / "development-evidences/repo/publisher.py"


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def git(*arguments: str) -> str:
    return subprocess.check_output(
        ["git", "-C", str(ROOT), *arguments],
        stderr=subprocess.DEVNULL, text=True,
    ).strip()


def verify_sources() -> tuple[str, str]:
    revision = git("rev-parse", "HEAD")
    branch = git("symbolic-ref", "--short", "HEAD")
    for idx, name in enumerate(FILES):
        source = ROOT / "gateway/app/services" / name
        if source.is_symlink() or not source.is_file():
            raise ValueError("missing_or_symlinked_source")
        if sha256(source.read_bytes()) != NEW[idx]:
            raise ValueError("source_hash_mismatch")
        compile(source.read_bytes(), name, "exec")
    return revision, branch


def run(args: list[str], **kwargs) -> int:
    try:
        return subprocess.run(args, check=False, **kwargs).returncode
    except (OSError, subprocess.TimeoutExpired):
        return 125


def publish(report: dict, relative: str) -> bool:
    if not PUBLISHER.is_file():
        return False
    # The evidence repository has one trusted branch for immutable manifests.
    try:
        check = subprocess.check_output(
            ["git", "-C", str(PUBLISHER.parent), "branch", "--show-current"],
            text=True, stderr=subprocess.DEVNULL,
        ).strip()
        if check != "main":
            return False
        with tempfile.TemporaryDirectory(prefix="codexbridge-deploy-proof-") as d:
            envelope = Path(d) / "evidence.json"
            envelope.write_text(json.dumps(
                {"relative_path": relative, "report": report},
                sort_keys=True, indent=2,
            ) + "\n")
            for command in (["enqueue", "--file", str(envelope)], ["flush"]):
                res = subprocess.run(
                    [sys.executable, str(PUBLISHER), *command],
                    capture_output=True, text=True, check=False, timeout=180,
                )
                if res.returncode != 0:
                    return False
                if command[0] == "flush" and (
                    "published=" + relative not in res.stdout.splitlines()
                ):
                    return False
            return True
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return False


def read_receipt(path: Path) -> dict:
    record = json.loads(path.read_text())
    if not isinstance(record, dict):
        raise ValueError("invalid_receipt")
    permitted = {
        "status": {"deployed", "already_current", "failed"},
        "reason": {
            "none", "preflight", "sudo_required", "invalid_stage",
            "invalid_manifest", "stage_hash_mismatch", "invalid_target",
            "gateway_unhealthy", "unknown_installed_baseline",
            "gateway_unhealthy_preflight", "backup_collision",
            "RuntimeError", "OSError", "ValueError", "PermissionError",
            "FileNotFoundError", "TimeoutExpired", "unexpected_error",
            "receipt_write_failed",
        },
        "rollback": {"not_needed", "success", "failed", "unknown"},
    }
    if any(record.get(key) not in values for key, values in permitted.items()):
        raise ValueError("invalid_receipt")
    if type(record.get("gateway_healthy")) is not bool or type(record.get("backup_created")) is not bool:
        raise ValueError("invalid_receipt")
    return {key: record[key] for key in (
        "status", "reason", "rollback", "gateway_healthy", "backup_created"
    )}


def main(argv: list[str] | None = None) -> int:
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--apply", action="store_true", help="Actually deploy with remote sudo")
    args = cli.parse_args(argv)
    if not args.apply:
        cli.error("explicit --apply required; no deployment performed")

    started = time.monotonic()
    now = datetime.now(timezone.utc)
    stage_id = "pr145-" + now.strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:8]
    relative = (
        "CodexBridge/gateway-pr145-deploy/development/"
        + now.strftime("%Y-%m-%d") + "/" + stage_id + "/manifest.json"
    )
    report = {
        "schema": 1,
        "project": "CodexBridge",
        "feature": "gateway-pr145-deploy",
        "target": "frida",
        "timestamp_utc": now.isoformat(),
        "source_commit": None,
        "source_branch": None,
        "installed_predecessor_sha256": dict(zip(FILES, OLD)),
        "requested_sha256": dict(zip(FILES, NEW)),
        "status": "fail",
        "reason": "preflight_not_completed",
        "rollback": "unknown",
        "gateway_healthy": False,
        "backup_created": False,
        "remote_status": "not_attempted",
        "log_local_only": True,
        "secrets_included": False,
    }
    try:
        commit, branch = verify_sources()
        report.update(source_commit=commit, source_branch=branch)
        remote_dir = "codexbridge-staging/" + stage_id
        with tempfile.TemporaryDirectory(prefix="codexbridge-pr145-") as d:
            path = Path(d)
            manifest = {
                "schema": 1, "profile": PROFILE,
                "old_sha256": list(OLD), "new_sha256": list(NEW),
            }
            (path / "manifest.json").write_text(json.dumps(manifest) + "\n")
            for name in FILES:
                (path / name).write_bytes(
                    (ROOT / "gateway/app/services" / name).read_bytes()
                )
            (path / "apply.py").write_bytes(
                (ROOT / "scripts/apply_pr145_gateway.py").read_bytes()
            )
            remote = "$HOME/" + remote_dir
            if run(["ssh", "-p", PORT, HOST,
                    "mkdir -p ~/" + remote_dir + " && chmod 700 ~/" + remote_dir]) != 0:
                raise RuntimeError("ssh_stage_failed")
            for name in ("manifest.json", *FILES, "apply.py"):
                if run(["scp", "-q", "-P", PORT, str(path / name),
                        HOST + ":" + remote_dir + "/" + name]) != 0:
                    raise RuntimeError("scp_stage_failed")
            report["remote_status"] = "invoked"
            # -tt preserves sudo's interactive password prompt. We do not
            # capture its output or collect credentials, even on failure.
            exit_code = run(
                ["ssh", "-tt", "-p", PORT, HOST,
                 "sudo python3 " + remote + "/apply.py " + remote],
            )
            receipt = path / "result.json"
            fetched = run([
                "scp", "-q", "-P", PORT,
                HOST + ":" + remote_dir + "/result.json", str(receipt)
            ]) == 0
            if not fetched:
                raise RuntimeError("remote_receipt_unavailable")
            result = read_receipt(receipt)
            report.update(
                status="pass" if exit_code == 0 and result["status"] in {
                    "deployed", "already_current"
                } and result["gateway_healthy"] else "fail",
                reason=result["reason"],
                rollback=result["rollback"],
                gateway_healthy=result["gateway_healthy"],
                backup_created=result["backup_created"],
                remote_status=result["status"],
            )
    except Exception as exc:
        # Never export raw exceptions, SSH output, host paths or credentials.
        report["reason"] = type(exc).__name__
    report["duration_seconds"] = round(time.monotonic() - started, 3)

    confirmed = publish(report, relative)
    print("DEPLOY_STATUS=" + report["status"])
    print("REMOTE_STATUS=" + report["remote_status"])
    print("ROLLBACK_STATUS=" + report["rollback"])
    print("GATEWAY_HEALTHY=" + str(report["gateway_healthy"]).lower())
    print("EVIDENCE_STATUS=" + ("published" if confirmed else "not_confirmed"))
    if confirmed:
        print("EVIDENCE_PATH=" + relative)
    # Fail closed if the deployment or evidence confirmation failed.
    return 0 if confirmed and report["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
