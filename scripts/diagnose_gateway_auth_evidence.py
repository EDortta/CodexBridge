#!/usr/bin/env python3
"""Non-secret operational checks and immutable evidence publication.

Runs on devel3 only. Frida receives no Git checkout or Git commands.
The existing development-evidences publisher exclusively handles Git writes.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import uuid

STATE = Path.home() / ".local/state/development-evidences"
PUBLISHER = STATE / "repo/publisher.py"
REMOTE = "esteban@frida.inovacaosistemas.com.br"
PORT = "2200"

# The remote inspection does not print paths with sensitive configuration
# values, passwords, hashes, e-mails, or token contents.
REMOTE_CHECK = r"""
import json, pathlib, subprocess
env = pathlib.Path('/etc/codex-bridge/env')
result = {'gateway_env_present': env.exists()}
if env.exists():
    lines = env.read_text().splitlines()
    entries = dict(line.split('=', 1) for line in lines if '=' in line and not line.lstrip().startswith('#'))
    value = entries.get('CODEX_BRIDGE_USER_REGISTRY_FILE', '')
    result['configured_registry_is_auth'] = value == '/etc/codex-bridge/auth/users.json'
    result['configured_registry_is_legacy'] = value == '/etc/codex-bridge/users.json'
    if value.startswith('/etc/codex-bridge/') and '..' not in pathlib.Path(value).parts:
        path = pathlib.Path(value)
        result['configured_registry_exists'] = path.is_file()
        try:
            payload = json.loads(path.read_text())
            users = payload.get('users', []) if isinstance(payload, dict) else []
            admins = [u for u in users if u.get('user_id') == 'esteban']
            result['configured_admin_count'] = len(admins)
            if len(admins) == 1:
                admin = admins[0]
                result['configured_admin_enabled'] = admin.get('enabled') is True
                result['configured_admin_role'] = 'admin' in admin.get('roles', [])
                result['configured_admin_hash_format'] = str(admin.get('password_hash', '')).startswith('pbkdf2_sha256$')
        except (OSError, ValueError, TypeError):
            result['configured_registry_readable_json'] = False
result['gateway_active'] = subprocess.run(['systemctl', 'is-active', '--quiet', 'codex-bridge-gateway']).returncode == 0
print("CODEXBRIDGE_EVIDENCE_JSON=" + json.dumps(result, sort_keys=True))
"""


def run_check() -> dict:
    # Interactive SSH/sudo owns the terminal. The remote test writes ONLY
    # whitelisted booleans/counts to a temporary file readable by esteban.
    # No sensitive stdout/stderr is ever copied into published evidence.
    import shlex
    marker = uuid.uuid4().hex
    remote_path = f"/tmp/codexbridge-evidence-{marker}.json"
    command = (
        "sudo python3 -c " + shlex.quote(REMOTE_CHECK)
        + " > " + shlex.quote(remote_path)
        + " && chmod 600 " + shlex.quote(remote_path)
    )
    try:
        # Do not capture the pseudo-terminal: sudo must be able to prompt.
        completed = subprocess.run(
            ["ssh", "-tt", "-o", "ConnectTimeout=12", "-p", PORT, REMOTE, command],
            timeout=180,
        )
        if completed.returncode:
            return {"remote_access": "ssh_or_sudo_failed"}
        # The remote file contains only sanitized result JSON.
        result = subprocess.run(
            ["ssh", "-o", "BatchMode=yes", "-p", PORT, REMOTE,
             "cat " + shlex.quote(remote_path) + " && rm -f " + shlex.quote(remote_path)],
            capture_output=True, text=True, timeout=30,
        )
        if result.returncode:
            return {"remote_access": "evidence_transfer_failed"}
        data = result.stdout.strip()
        if not data.startswith("CODEXBRIDGE_EVIDENCE_JSON="):
            raise ValueError("unexpected evidence response")
        obj = json.loads(data.removeprefix("CODEXBRIDGE_EVIDENCE_JSON="))
        if not isinstance(obj, dict):
            raise ValueError("not object")
        obj["remote_access"] = "ok"
        return obj
    except (OSError, subprocess.TimeoutExpired, ValueError, TypeError):
        return {"remote_access": "unavailable"}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--no-publish", action="store_true")
    args = parser.parse_args()
    now = datetime.now(timezone.utc)
    run_id = now.strftime("%H%M%S") + "-" + uuid.uuid4().hex[:8]
    checks = run_check()
    status = "pass" if (
        checks.get("remote_access") == "ok"
        and checks.get("gateway_active") is True
        and checks.get("configured_registry_exists") is True
        and checks.get("configured_admin_count") == 1
        and checks.get("configured_admin_enabled") is True
        and checks.get("configured_admin_role") is True
        and checks.get("configured_admin_hash_format") is True
    ) else "attention"
    report = {
        "schema": 1, "project": "CodexBridge",
        "feature": "gateway-auth-diagnostics",
        "branch": "development",
        "timestamp_utc": now.isoformat(),
        "run_id": run_id, "status": status,
        "checks": checks,
        "secrets_included": False,
    }
    print(json.dumps(report, indent=2, sort_keys=True))
    if args.no_publish:
        return 0 if status == "pass" else 1
    if not PUBLISHER.is_file():
        print("Evidence publisher not found; no publication attempted.", file=sys.stderr)
        return 2
    envelope = {
        "relative_path": (
            f"CodexBridge/gateway-auth-diagnostics/development/"
            f"{now:%Y-%m-%d}/{run_id}/manifest.json"
        ),
        "report": report,
    }
    with tempfile.TemporaryDirectory() as temp:
        path = Path(temp) / "envelope.json"
        path.write_text(json.dumps(envelope))
        for action in (["enqueue", "--file", str(path)], ["flush"]):
            result = subprocess.run(
                [sys.executable, str(PUBLISHER), *action],
                capture_output=True, text=True,
            )
            if result.returncode:
                print(f"Evidence publisher {action[0]} failed; local outbox may contain pending evidence.",
                      file=sys.stderr)
                return 2
            print(result.stdout.strip())
    return 0 if status == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
