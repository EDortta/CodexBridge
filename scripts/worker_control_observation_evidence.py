#!/usr/bin/env python3
"""Evidence of an ACTIVE user Worker reading its actual Git control branch."""
from datetime import datetime, timezone
from pathlib import Path
import json
import os
import subprocess
import sys
import tempfile
import uuid

HOME = Path.home()
STATE = Path(os.environ.get("XDG_STATE_HOME", str(HOME / ".local/state"))) / "codexbridge-worker/state.json"
WATCHER = Path(os.environ.get("CODEXBRIDGE_WATCHER_PATH", str(Path(os.environ.get("XDG_DATA_HOME", str(HOME / ".local/share"))) / "codexbridge-worker/scripts/worker_watch.py")))
PUBLISHER = HOME / ".local/state/development-evidences/repo/publisher.py"

def main():
    now = datetime.now(timezone.utc)
    run_id = now.strftime("%H%M%S") + "-" + uuid.uuid4().hex[:8]
    checks = {"state_exists": STATE.is_file(), "watcher_exists": WATCHER.is_file()}
    if STATE.is_file():
        try:
            data = json.loads(STATE.read_text())
            item = data.get("projects", {}).get("codexbridge", {})
            activation = data.get("activations", {}).get("codexbridge", {})
            expires = datetime.fromisoformat(activation["expires_at"].replace("Z", "+00:00"))
            checks["project_registered"] = item.get("repository") == "EDortta/CodexBridge" and item.get("control_branch") == "codexbridge-control"
            checks["local_activation_active"] = expires > now and "disabled_at" not in activation
        except (OSError, ValueError, KeyError, TypeError):
            checks["project_registered"] = False
            checks["local_activation_active"] = False
    else:
        checks["project_registered"] = False
        checks["local_activation_active"] = False
    checks["control_branch_read"] = False
    checks["validated_request_count"] = None
    if checks["watcher_exists"] and checks["local_activation_active"]:
        try:
            import importlib.util
            sys.path.insert(0, str(WATCHER.parent))
            spec = importlib.util.spec_from_file_location("worker_watch_diagnostic", WATCHER)
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            observation, envelopes = mod.git_ssh_control(
                "EDortta/CodexBridge", "codexbridge-control", "codexbridge")
            checks["control_branch_read"] = (
                observation["repository"] == "EDortta/CodexBridge"
                and observation["branch"] == "codexbridge-control")
            checks["validated_request_count"] = len(envelopes)
        except Exception as exc:
            # Only controlled scalar diagnostics; never log exception text,
            # Git stderr, paths, tokens, request payload or remote URL.
            checks["failure_type"] = type(exc).__name__
            checks["failure_errno"] = getattr(exc, "errno", None)
            checks["failure_exit_code"] = getattr(exc, "returncode", None)
            checks["failure_function"] = __import__("traceback").extract_tb(exc.__traceback__)[-1].name
    report = {"schema": 1, "project": "CodexBridge",
              "feature": "worker-control-observation", "branch": "development",
              "run_id": run_id, "timestamp_utc": now.isoformat(),
              "status": "pass" if all(checks[k] for k in ("project_registered", "local_activation_active", "control_branch_read")) else "attention",
              "checks": checks, "secrets_included": False}
    print(json.dumps(report, indent=2))
    if not PUBLISHER.is_file():
        print("Publisher not found", file=sys.stderr)
        return 2
    envelope = {
        "relative_path": f"CodexBridge/worker-control-observation/development/{now:%Y-%m-%d}/{run_id}/manifest.json",
        "report": report,
    }
    with tempfile.TemporaryDirectory() as temp:
        path = Path(temp) / "envelope.json"
        path.write_text(json.dumps(envelope))
        for argv in (["enqueue", "--file", str(path)], ["flush"]):
            r = subprocess.run([sys.executable, str(PUBLISHER), *argv],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=90)
            if r.returncode:
                print("Evidence publication failed (" + argv[0] + ")", file=sys.stderr)
                return 2
    return 0 if report["status"] == "pass" else 1

if __name__ == "__main__":
    raise SystemExit(main())
