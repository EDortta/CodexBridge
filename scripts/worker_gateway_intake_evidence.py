#!/usr/bin/env python3
"""One-shot authorized Git SSH -> Worker -> Gateway admission with safe evidence.

No dispatch, service startup, root access, API token, or raw log publication.
Run as the developer from the CodexBridge checkout containing .credentials/.
"""
from __future__ import annotations
from datetime import datetime, timezone
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import urllib.error
import uuid

HOME = Path.home()
STATE = Path(os.environ.get("XDG_STATE_HOME", str(HOME / ".local/state"))) / "codexbridge-worker"
CONFIG = Path(os.environ.get("XDG_CONFIG_HOME", str(HOME / ".config"))) / "codexbridge-worker"
WATCHER = Path(os.environ.get("XDG_DATA_HOME", str(HOME / ".local/share"))) / "codexbridge-worker/scripts/worker_watch.py"
CTL = WATCHER.parent / "workerctl.py"
PUBLISHER = HOME / ".local/state/development-evidences/repo/publisher.py"
REQUEST_ID = "smoke-20261030-worker-intake"


def test(checks: dict) -> None:
    if os.geteuid() == 0:
        checks["stage"] = "root_refused"
        return

    command = [sys.executable, str(CTL), "--state-file", str(STATE / "state.json"),
               "enable", "--project", "codexbridge"]
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=15)
        checks["local_activation"] = "ok" if result.returncode == 0 else "failed"
    except (OSError, subprocess.TimeoutExpired):
        checks["local_activation"] = "unavailable"
    if checks["local_activation"] != "ok":
        checks["stage"] = "local_activation"
        return

    try:
        from activate_worker_evidence import run as operator_activate
        auth_checks, lease = operator_activate(Path(".credentials/admin-password.txt"))
        checks["admin_sign_in"] = auth_checks.get("sign_in", "failed")
        checks["gateway_lease"] = auth_checks.get("activation", "failed")
        if checks["gateway_lease"] == "ok":
            checks["gateway_lease_created"] = bool(lease.get("created"))
    except (ImportError, OSError, ValueError):
        checks["gateway_lease"] = "runner_error"
    if checks.get("gateway_lease") != "ok":
        checks["stage"] = "gateway_lease"
        return

    try:
        sys.path.insert(0, str(WATCHER.parent))
        spec = importlib.util.spec_from_file_location("codexbridge_worker_observer", WATCHER)
        if spec is None or spec.loader is None:
            raise RuntimeError("worker observer unavailable")
        worker = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(worker)
        observation, blobs = worker.git_ssh_control(
            "EDortta/CodexBridge", "codexbridge-control", "codexbridge")
        checks["git_control_branch"] = "ok"
        selected = [item for item in observation["requests"]
                    if item["name"] == REQUEST_ID + ".json"]
        checks["smoke_request_found"] = len(selected) == 1
        if len(selected) != 1:
            checks["stage"] = "smoke_request"
            return
    except Exception as exc:
        checks["git_control_branch"] = "failed"
        checks["failure_type"] = type(exc).__name__
        checks["stage"] = "git_control_branch"
        return

    env = {}
    if (CONFIG / "worker.env").is_file():
        for line in (CONFIG / "worker.env").read_text().splitlines():
            if line and not line.lstrip().startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                if key in ("CODEXBRIDGE_GATEWAY_URL", "CODEXBRIDGE_WORKER_TOKEN_FILE"):
                    env[key] = value.strip().strip('"')
    gateway_url = env.get("CODEXBRIDGE_GATEWAY_URL", "")
    token_path = env.get("CODEXBRIDGE_WORKER_TOKEN_FILE", "")
    checks["gateway_https_configured"] = gateway_url.startswith("https://")
    checks["worker_token_readable"] = bool(
        token_path and Path(token_path).is_file()
        and os.access(token_path, os.R_OK))
    if not checks["gateway_https_configured"] or not checks["worker_token_readable"]:
        checks["stage"] = "transport_configuration"
        return

    try:
        # Read only the local machine credential; never print or publish it.
        token = Path(token_path).read_text(encoding="utf-8").strip()
        envelope = blobs[selected[0]["sha"]]
        receipt = worker.gateway_intake(gateway_url, token, observation, envelope)
        checks["gateway_admitted"] = receipt.get("state") == "admitted"
        checks["admission_created"] = receipt.get("created")
        checks["stage"] = "complete" if checks["gateway_admitted"] else "gateway_receipt"
    except urllib.error.HTTPError as exc:
        checks["stage"] = "gateway_intake"
        checks["gateway_http_status"] = exc.code
    except Exception as exc:
        checks["stage"] = "gateway_intake"
        checks["failure_type"] = type(exc).__name__


def main() -> int:
    now = datetime.now(timezone.utc)
    run_id = now.strftime("%H%M%S") + "-" + uuid.uuid4().hex[:8]
    checks = {"stage": "initial", "user_context": os.geteuid() != 0}
    try:
        test(checks)
    except Exception as exc:
        checks["stage"] = "unexpected"
        checks["failure_type"] = type(exc).__name__
    report = {
        "schema": 1, "project": "CodexBridge", "feature": "worker-gateway-intake",
        "branch": "development", "timestamp_utc": now.isoformat(), "run_id": run_id,
        "status": "pass" if checks.get("stage") == "complete" else "attention",
        "checks": checks, "secrets_included": False,
    }
    print(json.dumps(report, indent=2))
    if not PUBLISHER.is_file():
        print("Evidence publisher not available", file=sys.stderr)
        return 2
    envelope = {
        "relative_path": (
            f"CodexBridge/worker-gateway-intake/development/"
            f"{now:%Y-%m-%d}/{run_id}/manifest.json"
        ), "report": report,
    }
    with tempfile.TemporaryDirectory() as temp:
        path = Path(temp) / "envelope.json"
        path.write_text(json.dumps(envelope))
        for args in (["enqueue", "--file", str(path)], ["flush"]):
            proc = subprocess.run([sys.executable, str(PUBLISHER), *args],
                                  stdout=subprocess.DEVNULL,
                                  stderr=subprocess.DEVNULL, timeout=90)
            if proc.returncode:
                print("Evidence publication failed: " + args[0], file=sys.stderr)
                return 2
    return 0 if report["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
