#!/usr/bin/env python3
"""Activate devel3 Worker through an SSH tunnel; publish non-secret evidence.

Run on devel3, from the project directory containing .credentials/admin-password.txt.
Never copy credentials to Frida or write bearer tokens to disk.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
import uuid

REMOTE = "esteban@frida.inovacaosistemas.com.br"
PUBLISHER = Path.home() / ".local/state/development-evidences/repo/publisher.py"


def post(port, path, payload, token=None):
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = "Bearer " + token
    request = urllib.request.Request(
        "http://127.0.0.1:%d%s" % (port, path),
        data=json.dumps(payload).encode("utf-8"),
        headers=headers, method="POST",
    )
    with urllib.request.urlopen(request, timeout=15) as response:
        return json.load(response)


def choose_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def probe(port):
    try:
        with urllib.request.urlopen("http://127.0.0.1:%d/health" % port, timeout=2) as r:
            return r.status == 200
    except (urllib.error.URLError, OSError):
        return False


def run(password_file):
    checks = {"ssh_tunnel": "failed", "sign_in": "not_attempted",
              "activation": "not_attempted"}
    result = {}
    port = choose_port()
    command = ["ssh", "-N", "-T", "-o", "BatchMode=yes",
               "-o", "ExitOnForwardFailure=yes", "-o", "ConnectTimeout=12",
               "-p", "2200", "-L", "127.0.0.1:%d:127.0.0.1:18080" % port, REMOTE]
    tunnel = subprocess.Popen(command, stdin=subprocess.DEVNULL,
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        for _ in range(40):
            if tunnel.poll() is not None:
                break
            if probe(port):
                checks["ssh_tunnel"] = "ok"
                break
            time.sleep(.2)
        if checks["ssh_tunnel"] != "ok":
            return checks, result
        try:
            password = password_file.read_text(encoding="utf-8").rstrip("\r\n")
        except OSError:
            checks["sign_in"] = "credential_file_unreadable"
            return checks, result
        if not password:
            checks["sign_in"] = "credential_file_empty"
            return checks, result
        try:
            auth = post(port, "/api/v1/auth/sign-in",
                        {"username": "esteban", "password": password})
            checks["sign_in"] = "ok"
        except urllib.error.HTTPError as exc:
            checks["sign_in"] = "http_%d" % exc.code
            return checks, result
        except (OSError, ValueError, KeyError):
            checks["sign_in"] = "transport_or_response_error"
            return checks, result
        try:
            response = post(port, "/control/workers/devel3/activate",
                            {"projectId": "codexbridge",
                             "repository": "EDortta/CodexBridge",
                             "controlBranch": "codexbridge-control"},
                            auth["accessToken"])
            checks["activation"] = "ok"
            # Only whitelisted metadata, never token, cookies, or raw response.
            result = {"lease_id": response.get("leaseId"),
                      "expires_at": response.get("expiresAt"),
                      "created": response.get("created")}
        except urllib.error.HTTPError as exc:
            checks["activation"] = "http_%d" % exc.code
        except (OSError, ValueError, KeyError):
            checks["activation"] = "transport_or_response_error"
        return checks, result
    finally:
        tunnel.terminate()
        try:
            tunnel.wait(timeout=4)
        except subprocess.TimeoutExpired:
            tunnel.kill()
            tunnel.wait()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--password-file", type=Path,
                        default=Path(".credentials/admin-password.txt"))
    parser.add_argument("--no-publish", action="store_true")
    args = parser.parse_args()
    now = datetime.now(timezone.utc)
    run_id = now.strftime("%H%M%S") + "-" + uuid.uuid4().hex[:8]
    checks, details = run(args.password_file)
    report = {"schema": 1, "project": "CodexBridge",
              "feature": "worker-activation", "branch": "development",
              "timestamp_utc": now.isoformat(), "run_id": run_id,
              "status": "pass" if checks.get("activation") == "ok" else "failure",
              "checks": checks, "activation": details, "secrets_included": False}
    print(json.dumps(report, indent=2))
    if args.no_publish:
        return 0 if report["status"] == "pass" else 1
    if not PUBLISHER.is_file():
        print("Evidence publisher unavailable", file=sys.stderr)
        return 2
    envelope = {"relative_path": ("CodexBridge/worker-activation/development/"
                + now.strftime("%Y-%m-%d") + "/" + run_id + "/manifest.json"),
                "report": report}
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "envelope.json"
        path.write_text(json.dumps(envelope), encoding="utf-8")
        for args_ in (["enqueue", "--file", str(path)], ["flush"]):
            action = subprocess.run([sys.executable, str(PUBLISHER), *args_],
                                    capture_output=True, text=True)
            if action.returncode:
                print("evidence %s failed; outbox may be pending" % args_[0],
                      file=sys.stderr)
                return 2
            print(action.stdout.strip())
    return 0 if report["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
