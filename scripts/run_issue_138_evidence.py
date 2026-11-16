#!/usr/bin/env python3
"""Issue #138 verification: one command, sanitized evidence published centrally.

Runs the complete test suite, public endpoint timings, and optional local admin
login timing. Raw subprocess output stays in mode-0600 local files. The remotely
published manifest contains only counts, names of failing tests, timings, and
Git provenance. Publication uses development-evidences/publisher.py, never a
custom git push. This tool does not deploy, modify services or print credentials.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import time
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE_REPO_URL = "https://github.com/EDortta/development-evidences"
FAILURE = re.compile(r"^FAILED (tests/[A-Za-z0-9_./-]+::[A-Za-z0-9_\[\]-]+)", re.M)
SUMMARY = re.compile(r"(\d+) (passed|failed|skipped|error|errors|warnings?)\b")
SAFE_ENVIRONMENT = re.compile(r"^[A-Za-z0-9_.-]{1,64}$")
DEFAULT_BASE = "https://codexbridge.inovacaosistemas.com.br"


def git(*arguments: str, cwd: Path = ROOT) -> str:
    return subprocess.check_output(
        ["git", *arguments], cwd=cwd, text=True, stderr=subprocess.DEVNULL
    ).strip()


def run_logged(argv: list[str], output: Path, *, timeout: int, cwd: Path = ROOT) -> tuple[int, float]:
    start = time.monotonic()
    with output.open("wb") as stream:
        os.chmod(output, 0o600)
        try:
            completed = subprocess.run(
                argv, cwd=cwd, stdin=subprocess.DEVNULL, stdout=stream,
                stderr=subprocess.STDOUT, timeout=timeout, check=False,
            )
            return completed.returncode, round(time.monotonic() - start, 3)
        except subprocess.TimeoutExpired:
            stream.write(b"\nTIMEOUT\n")
            return 124, round(time.monotonic() - start, 3)
        except OSError:
            stream.write(b"\nSPAWN_FAILED\n")
            return 125, round(time.monotonic() - start, 3)


def publisher_path() -> Path:
    root = os.environ.get("DEVELOPMENT_EVIDENCES_ROOT")
    return ((Path(root).expanduser() if root else
             Path.home() / ".local/state/development-evidences/repo") / "publisher.py")


def publish(path: str, report: dict, publisher: Path) -> bool:
    with tempfile.TemporaryDirectory(prefix="issue-138-publish-") as folder:
        envelope = Path(folder) / "envelope.json"
        envelope.write_text(
            json.dumps({"relative_path": path, "report": report},
                       ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        for args in (["enqueue", "--file", str(envelope)], ["flush"]):
            try:
                cmd = subprocess.run(
                    [sys.executable, str(publisher), *args],
                    capture_output=True, text=True, timeout=120,
                    stdin=subprocess.DEVNULL, check=False,
                )
            except (OSError, subprocess.TimeoutExpired):
                return False
            if cmd.returncode:
                return False
            if args[0] == "flush" and f"published={path}" not in cmd.stdout.splitlines():
                return False
    return True


def network_probe(base: str, output: Path) -> tuple[int, dict]:
    # URL is explicitly passed to curl; never shell-interpolated.
    endpoints = ["/health", "/.well-known/oauth-authorization-server",
                 "/.well-known/oauth-protected-resource/mcp"]
    results = {}
    failed = False
    for endpoint in endpoints:
        argv = [
            "curl", "--silent", "--show-error", "--output", "/dev/null",
            "--max-time", "20", "--write-out",
            "%{http_code} %{time_namelookup} %{time_connect} "
            "%{time_appconnect} %{time_starttransfer} %{time_total}",
            base.rstrip("/") + endpoint,
        ]
        try:
            proc = subprocess.run(
                argv, capture_output=True, text=True, timeout=25,
                stdin=subprocess.DEVNULL, check=False,
            )
            fields = proc.stdout.strip().split()
            if proc.returncode or len(fields) != 6:
                failed = True
                results[endpoint] = {"status": "failed"}
            else:
                http, *times = fields
                results[endpoint] = {
                    "http_status": int(http),
                    "dns_seconds": float(times[0]),
                    "connect_seconds": float(times[1]),
                    "tls_seconds": float(times[2]),
                    "ttfb_seconds": float(times[3]),
                    "total_seconds": float(times[4]),
                }
                if http != "200":
                    failed = True
        except (OSError, subprocess.TimeoutExpired, ValueError):
            failed = True
            results[endpoint] = {"status": "failed"}
    output.write_text(json.dumps(results, indent=2) + "\n")
    os.chmod(output, 0o600)
    return (1 if failed else 0), results


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--environment", default="devel3")
    parser.add_argument("--base-url", default=DEFAULT_BASE)
    parser.add_argument("--skip-admin-login", action="store_true",
                        help="Skip local admin-login timing if no credentials are available")
    parser.add_argument("--pytest-timeout", type=int, default=900)
    args = parser.parse_args()
    if not SAFE_ENVIRONMENT.fullmatch(args.environment):
        parser.error("invalid environment identifier")
    if not args.base_url.startswith("https://") or any(
        char in args.base_url for char in ("?", "#", "\n", "\r", " ")
    ):
        parser.error("base URL must be HTTPS without query/fragment")
    try:
        branch = git("symbolic-ref", "--short", "HEAD")
        commit = git("rev-parse", "HEAD")
    except (OSError, subprocess.CalledProcessError):
        print("BLOCKED: git branch or commit unavailable", file=sys.stderr)
        return 2
    publisher = publisher_path()
    if not publisher.is_file():
        print("BLOCKED: evidence publisher not installed", file=sys.stderr)
        return 2
    try:
        evidence_branch = git("symbolic-ref", "--short", "HEAD", cwd=publisher.parent)
    except (OSError, subprocess.CalledProcessError):
        print("BLOCKED: evidence checkout unavailable", file=sys.stderr)
        return 2
    if evidence_branch != "main":
        print("BLOCKED: evidence publisher repository must be on main", file=sys.stderr)
        return 2

    now = datetime.now(timezone.utc)
    run_id = now.strftime("%H%M%S") + "-" + uuid4().hex[:8]
    state = Path(os.environ.get("XDG_STATE_HOME", str(Path.home() / ".local/state")))
    directory = state / "codexbridge" / "issue-138" / run_id
    directory.mkdir(parents=True, exist_ok=False, mode=0o700)
    tests_log = directory / "pytest.log"
    print(f"RUN_ID={run_id}", flush=True)
    print("CHECK=pytest_full_suite", flush=True)
    pytest_rc, pytest_seconds = run_logged(
        [sys.executable, "-m", "pytest", "-q", "--tb=short"],
        tests_log, timeout=args.pytest_timeout,
    )
    raw = tests_log.read_text(encoding="utf-8", errors="replace")
    counts = {}
    for value, label in SUMMARY.findall(raw):
        counts[label] = int(value)
    failures = sorted(set(FAILURE.findall(raw)))
    # Do not upload raw logs: test output can include stack traces, paths,
    # user records and secrets. Only constrained test IDs leave the host.
    tests = {
        "exit_code": pytest_rc,
        "duration_seconds": pytest_seconds,
        "counts": counts,
        "failed_test_ids": failures[:100],
        "log_retained_locally": True,
    }
    print("PYTEST_RESULT=" + json.dumps(tests, sort_keys=True), flush=True)

    print("CHECK=public_network_timing", flush=True)
    network_rc, network = network_probe(args.base_url, directory / "network.json")
    print("NETWORK_RESULT=" + json.dumps(network, sort_keys=True), flush=True)

    admin = {"status": "skipped"}
    admin_rc = 0
    if not args.skip_admin_login:
        helper = ROOT.parent / "CodexBridge-gateway" / "get-codexbridge-admin-token.sh"
        credentials = helper.parent / ".credentials" / "codex-bridge-initial-admin-password.ini"
        if not credentials.is_file():
            admin = {"status": "unavailable", "reason": "admin_credentials_missing"}
            admin_rc = 1
        else:
            print("CHECK=admin_login_phases", flush=True)
            admin_log = directory / "admin-login.log"
            admin_rc, duration = run_logged(
                [sys.executable, str(ROOT / "scripts/diagnose_issue_138_admin.py"),
                 "--credentials", str(credentials), "--base-url", args.base_url],
                admin_log, timeout=65,
            )
            try:
                # The diagnostic prints only whitelisted timings/status codes.
                admin = json.loads(admin_log.read_text(encoding="utf-8"))
                if not isinstance(admin, dict):
                    raise ValueError("invalid diagnostic output")
                if admin.get("status") != "pass":
                    admin_rc = 1
            except (OSError, ValueError, json.JSONDecodeError):
                admin = {"status": "failed", "reason": "diagnostic_failed"}
                admin_rc = 1
            admin["total_duration_seconds"] = duration
    print("ADMIN_LOGIN_RESULT=" + json.dumps(admin, sort_keys=True), flush=True)

    status = "success" if not (pytest_rc or network_rc or admin_rc) else "failed"
    report = {
        "schema": 1,
        "project": "CodexBridge",
        "feature": "issue-138-oauth-session",
        "phase": "verification",
        "branch": branch,
        "commit": commit,
        "timestamp_utc": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "environment": args.environment,
        "status": status,
        "exit_code": 0 if status == "success" else 1,
        "error_category": "none" if status == "success" else "verification",
        "checks": {
            "pytest": tests,
            "network": network,
            "network_exit_code": network_rc,
            "admin_login": admin,
            "remote_publication_required": True,
        },
        "detail": "Sanitized verification metadata only; raw logs private on executor",
    }
    relative = (
        "CodexBridge/issue-138-oauth-session/"
        f"{re.sub(r'[^A-Za-z0-9_.-]', '-', branch)}/{now:%Y-%m-%d}/"
        f"{run_id}/manifest.json"
    )
    published = publish(relative, report, publisher)
    print(f"LOCAL_EVIDENCE_DIR={directory}")
    print(f"STATUS={status}")
    if not published:
        print("EVIDENCE_NOT_CONFIRMED: inspect shared publisher queue", file=sys.stderr)
        return 2
    print(f"EVIDENCE_URL={EVIDENCE_REPO_URL}/blob/main/{relative}")
    return 0 if status == "success" else 1


if __name__ == "__main__":
    raise SystemExit(main())
