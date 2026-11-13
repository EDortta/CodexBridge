#!/usr/bin/env python3
"""Read-only Gateway/Agent communication diagnostics. Raw logs stay local.

Invoke ONLY through scripts/run_deploy_test_with_evidence.py to require
a confirmed remote evidence publication for this verification.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys

DEFAULT_SINCE = "15 minutes ago"
FRIDA = "esteban@frida.inovacaosistemas.com.br"


def run(argv: list[str], *, timeout: int = 35) -> subprocess.CompletedProcess[str]:
    return subprocess.run(argv, capture_output=True, text=True, timeout=timeout, check=False)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--since", default=DEFAULT_SINCE, help="Frida/devel3 local timestamp for post-release diagnostics")
    args = parser.parse_args()

    try:
        # Use a fixed shell program, with timestamp validated for safe shell transport.
        import re
        if args.since != "15 minutes ago" and not re.fullmatch(r"20[0-9]{2}-[0-9]{2}-[0-9]{2} [0-9]{2}:[0-9]{2}:[0-9]{2}", args.since):
            parser.error("invalid --since timestamp")
        remote_command = (
            "set -eu; systemctl is-active --quiet codex-bridge-gateway; "
            "curl -fsS --max-time 8 http://127.0.0.1:18080/health >/dev/null; "
            f"sudo -n journalctl -u codex-bridge-gateway --since '{args.since}' --no-pager -o cat"
        )
        remote = run(["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=8",
                      "-p", "2200", FRIDA, remote_command])
        local = run(["sudo", "-n", "journalctl", "-u", "codex-bridge-agent.service",
                     "--since", args.since, "--no-pager", "-o", "cat"], timeout=20)
        agent_active = run(["systemctl", "is-active", "--quiet", "codex-bridge-agent.service"], timeout=8)
    except subprocess.TimeoutExpired:
        print(json.dumps({"status": "failed", "reason": "diagnostic_timeout"}))
        return 1

    if remote.returncode or local.returncode or agent_active.returncode:
        print(json.dumps({
            "status": "failed",
            "remote_command_exit": remote.returncode,
            "agent_journal_exit": local.returncode,
            "agent_service_exit": agent_active.returncode,
            "detail": "Read local private logs for command errors; no secrets published",
        }))
        return 1

    gateway = remote.stdout
    agent = local.stdout
    errors = gateway.count("ERROR:") + gateway.count("Traceback (most recent call last)")
    sqlite_locks = gateway.count("database is locked")
    accepted = gateway.count('WebSocket /agent/ws?executor_id=devel3" [accepted]')
    agent_failures = agent.count("connection_failed")
    print(json.dumps({
        "status": "passed" if not (errors or sqlite_locks or agent_failures) else "failed",
        "gateway_http_health": "ok",
        "gateway_ws_accepted_since": accepted,
        "gateway_errors_since": errors,
        "gateway_sqlite_locks_since": sqlite_locks,
        "agent_connection_failures_since": agent_failures,
        "agent_systemd_active": True,
        "note": "Acceptance proves handshake only, not ongoing connection or task execution",
    }, sort_keys=True))
    return 0 if not (errors or sqlite_locks or agent_failures) else 1


if __name__ == "__main__":
    raise SystemExit(main())
