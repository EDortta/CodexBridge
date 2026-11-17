#!/usr/bin/env python3
"""Run a CodexBridge verification command and always retain evidence.

The raw stdout/stderr remains private on the executor. The immutable, sanitized
manifest is queued to the existing development-evidences publisher even when
the command fails. Publication failure is explicit and never hides test failure.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
SUMMARY = re.compile(r"(\d+) (passed|failed|skipped|errors?|warnings?)\b")
FAILED = re.compile(r"^FAILED (tests/[A-Za-z0-9_./\[\]-]+)", re.MULTILINE)


def _git(*args: str) -> str:
    return subprocess.check_output(
        ["git", *args], cwd=ROOT, text=True, stderr=subprocess.DEVNULL
    ).strip()


def run_evidenced(command: list[str], *, feature: str, timeout: int,
                  state_root: Path, publisher: Path | None) -> tuple[int, dict, Path]:
    if not command:
        raise ValueError("command required")
    started = datetime.now(timezone.utc)
    run_id = started.strftime("%Y%m%dT%H%M%SZ") + "-" + secrets.token_hex(4)
    directory = state_root / "codexbridge" / feature / run_id
    directory.mkdir(mode=0o700, parents=True, exist_ok=False)
    log = directory / "execution.log"
    os.chmod(directory, 0o700)
    begun = time.monotonic()
    rc = 125
    failure = None
    with log.open("wb") as output:
        os.chmod(log, 0o600)
        try:
            process = subprocess.run(
                command, cwd=ROOT, stdout=output, stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL, timeout=timeout, check=False,
            )
            rc = process.returncode
        except subprocess.TimeoutExpired:
            rc, failure = 124, "timeout"
            output.write(b"\nTIMEOUT\n")
        except OSError:
            rc, failure = 125, "spawn_failed"
            output.write(b"\nSPAWN_FAILED\n")
    raw = log.read_bytes()
    text = raw.decode("utf-8", errors="replace")
    counts: dict[str, int] = {}
    for value, label in SUMMARY.findall(text):
        counts[label] = int(value)
    branch = _git("branch", "--show-current")
    commit = _git("rev-parse", "HEAD")
    status = "success" if rc == 0 else "failed"
    report = {
        "schema": 1, "project": "CodexBridge", "feature": feature,
        "phase": "verification", "environment": os.environ.get("CODEXBRIDGE_ENVIRONMENT", "devel3"),
        "branch": branch, "commit": commit,
        "timestamp_utc": started.isoformat(), "status": status,
        "exit_code": rc, "error_category": failure or ("none" if rc == 0 else "verification"),
        "duration_seconds": round(time.monotonic() - begun, 3),
        "checks": {
            "command_kind": "pytest" if "pytest" in " ".join(command) else "script",
            "counts": counts, "failed_test_ids": sorted(set(FAILED.findall(text)))[:100],
            "local_log_sha256": hashlib.sha256(raw).hexdigest(),
            "local_log_bytes": len(raw), "raw_logs_local_only": True,
        },
        "detail": "Sanitized evidence; raw execution output stays private on executor.",
    }
    safe_branch = re.sub(r"[^A-Za-z0-9_.-]", "-", branch)
    relative = f"CodexBridge/{feature}/{safe_branch}/{started:%Y-%m-%d}/{run_id}/manifest.json"
    envelope = {"relative_path": relative, "report": report}
    (directory / "manifest.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    queue = directory / "publisher-envelope.json"
    queue.write_text(json.dumps(envelope, sort_keys=True) + "\n", encoding="utf-8")
    publication = "unavailable"
    if publisher is not None and publisher.is_file():
        try:
            queued = subprocess.run(
                [sys.executable, str(publisher), "enqueue", "--file", str(queue)],
                stdin=subprocess.DEVNULL, capture_output=True, timeout=30
            )
            if queued.returncode == 0:
                publication = "queued"
                flushed = subprocess.run(
                    [sys.executable, str(publisher), "flush"],
                    stdin=subprocess.DEVNULL, capture_output=True, timeout=120
                )
                if flushed.returncode == 0 and f"published={relative}".encode() in flushed.stdout.splitlines():
                    publication = "published"
            else:
                publication = "enqueue_failed"
        except (OSError, subprocess.TimeoutExpired):
            publication = "publisher_error"
    (directory / "publication.json").write_text(
        json.dumps({"status": publication, "relative_path": relative}) + "\n", encoding="utf-8"
    )
    print("STATUS=" + status, flush=True)
    print("EXIT_CODE=" + str(rc), flush=True)
    print("EVIDENCE_DIR=" + str(directory), flush=True)
    print("EVIDENCE_PUBLICATION=" + publication, flush=True)
    if publication == "published":
        print("EVIDENCE_URL=https://github.com/EDortta/development-evidences/blob/main/" + relative, flush=True)
    # A failed command always fails. Publication trouble also fails closed.
    return (rc if rc else (0 if publication == "published" or publisher is None else 2)), report, directory


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--feature", default="file-instruction-ws-bridge")
    p.add_argument("--timeout", type=int, default=300)
    p.add_argument("--no-publish", action="store_true", help="CI only; local manifest remains mandatory")
    p.add_argument("command", nargs=argparse.REMAINDER)
    args = p.parse_args(argv)
    if not re.fullmatch(r"[A-Za-z0-9._-]{1,80}", args.feature):
        p.error("invalid feature")
    command = args.command[1:] if args.command[:1] == ["--"] else args.command
    if not command or args.timeout < 1 or args.timeout > 3600:
        p.error("a command and valid bounded timeout are required")
    root = Path(os.environ.get("XDG_STATE_HOME", str(Path.home() / ".local/state")))
    publisher = None if args.no_publish else (
        Path(os.environ.get("DEVELOPMENT_EVIDENCES_ROOT", str(
            Path.home() / ".local/state/development-evidences/repo"
        ))) / "publisher.py"
    )
    exit_code, _, _ = run_evidenced(command, feature=args.feature, timeout=args.timeout,
                                  state_root=root, publisher=publisher)
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
