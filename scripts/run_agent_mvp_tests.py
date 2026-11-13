#!/usr/bin/env python3
"""Run Agent MVP pytest checks and publish a sanitized immutable manifest.

Only the shared development-evidences publisher commits or pushes evidence.
Raw pytest output remains in a private local file; never enters the manifest.
No service management, deployment, or project-file changes.
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
SAFE_NAME = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_.-]{0,63}$")
SHA = re.compile(r"^[a-f0-9]{40}$")


def git(*arguments: str, cwd: Path = ROOT) -> str:
    return subprocess.check_output(
        ["git", *arguments], cwd=cwd, stderr=subprocess.DEVNULL, text=True
    ).strip()


def publisher_path() -> Path:
    root = os.environ.get("DEVELOPMENT_EVIDENCES_ROOT")
    return Path(root).expanduser() / "publisher.py" if root else (
        Path.home() / ".local/state/development-evidences/repo/publisher.py"
    )


def publish(relative_path: str, report: dict, publisher: Path) -> bool:
    with tempfile.TemporaryDirectory(prefix="codexbridge-evidence-") as directory:
        envelope_file = Path(directory) / "envelope.json"
        envelope_file.write_text(
            json.dumps({"relative_path": relative_path, "report": report},
                       ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        for arguments in (["enqueue", "--file", str(envelope_file)], ["flush"]):
            try:
                completed = subprocess.run(
                    [sys.executable, str(publisher), *arguments],
                    capture_output=True, text=True, timeout=120,
                    stdin=subprocess.DEVNULL,
                )
            except (OSError, subprocess.TimeoutExpired):
                return False
            if completed.returncode:
                return False
            if arguments[0] == "flush":
                # The publisher may flush other queued manifests too. Only
                # THIS run's explicit ACK is sufficient proof of publication.
                if f"published={relative_path}" not in completed.stdout.splitlines():
                    return False
    return True


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--suite", default="mvp-agent-ws")
    parser.add_argument("--environment", default="devel3")
    parser.add_argument(
        "pytest_args", nargs=argparse.REMAINDER,
        help="Optional pytest arguments after --",
    )
    args = parser.parse_args(argv)
    if not SAFE_NAME.fullmatch(args.suite) or not SAFE_NAME.fullmatch(args.environment):
        parser.error("suite and environment must use safe identifiers")

    try:
        branch = git("symbolic-ref", "--short", "HEAD")
        commit = git("rev-parse", "HEAD")
    except (OSError, subprocess.CalledProcessError):
        print("BLOCKED: branch/commit unavailable", file=sys.stderr)
        return 2
    if not SHA.fullmatch(commit):
        print("BLOCKED: invalid commit", file=sys.stderr)
        return 2

    publisher = publisher_path()
    if not publisher.is_file():
        print("BLOCKED: shared publisher.py not found; tests not started", file=sys.stderr)
        return 2
    try:
        evidence_branch = git("symbolic-ref", "--short", "HEAD", cwd=publisher.parent)
    except (OSError, subprocess.CalledProcessError):
        print("BLOCKED: evidence repository not a checkout", file=sys.stderr)
        return 2
    if evidence_branch != "main":
        print("BLOCKED: unexpected evidence repository branch", file=sys.stderr)
        return 2

    pytest_args = args.pytest_args[1:] if args.pytest_args[:1] == ["--"] else args.pytest_args
    if not pytest_args:
        pytest_args = ["tests/unit/test_mvp_agent_ws_lifecycle.py", "-q"]
    command = [sys.executable, "-m", "pytest", *pytest_args]

    now = datetime.now(timezone.utc)
    run_id = now.strftime("%H%M%S") + "-" + uuid4().hex[:8]
    safe_branch = re.sub(r"[^A-Za-z0-9_.-]", "-", branch)
    relative_path = (
        f"CodexBridge/{args.suite}/{safe_branch}/{now:%Y-%m-%d}/"
        f"{run_id}/manifest.json"
    )
    state = Path(os.environ.get("XDG_STATE_HOME", str(Path.home() / ".local/state")))
    log_dir = state / "codexbridge" / "agent-test-logs"
    log_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    log_file = log_dir / f"{run_id}.log"

    started = time.monotonic()
    with log_file.open("wb") as output:
        os.chmod(log_file, 0o600)
        try:
            result = subprocess.run(
                command, cwd=ROOT, stdin=subprocess.DEVNULL,
                stdout=output, stderr=subprocess.STDOUT,
            )
            exit_code = result.returncode
        except OSError:
            exit_code = 125
    duration = round(time.monotonic() - started, 3)

    report = {
        "schema": 1,
        "project": "CodexBridge",
        "feature": args.suite,
        "branch": branch,
        "commit": commit,
        "timestamp_utc": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "phase": "verification",
        "status": "success" if exit_code == 0 else "failed",
        "exit_code": exit_code,
        "duration_seconds": duration,
        "environment": args.environment,
        "error_category": "none" if exit_code == 0 else "verification",
        "checks": {
            "pytest_exit_code": exit_code,
            "suite": args.suite,
            "remote_publication_required": True,
        },
        "detail": (
            "Agent MVP tests passed; raw diagnostics retained locally"
            if exit_code == 0 else
            "Agent MVP tests failed; raw diagnostics retained locally"
        ),
    }

    confirmed = publish(relative_path, report, publisher)
    # Manifest is immutable; report an unconfirmed transmission separately,
    # without mutating the test outcome or discarding the shared outbox.
    if not confirmed:
        print("EVIDENCE_NOT_CONFIRMED; inspect shared publisher queue", file=sys.stderr)
        print(f"TEST_EXIT_CODE={exit_code}")
        print(f"LOCAL_LOG={log_file}")
        return 2

    print(f"TEST_STATUS={report['status']}")
    print(f"TEST_EXIT_CODE={exit_code}")
    print(f"BRANCH={branch}")
    print(f"COMMIT={commit}")
    print(f"DURATION_SECONDS={duration}")
    print(f"EVIDENCE_URL={EVIDENCE_REPO_URL}/blob/main/{relative_path}")
    print(f"LOCAL_LOG={log_file}")
    return 0 if exit_code == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
