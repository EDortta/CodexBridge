#!/usr/bin/env python3
"""One-shot live PR145 interruption observer. Run only with explicit operator authorization.

Operator runs this *before* a distinct file-instruction request is submitted
through the connected MCP. The observer watches ONLY that request ID; after it
sees the exact .running instruction, it restarts only the user Agent service.
It then waits for the durable local "interrupted" result. The remote Gateway
task/result must be verified separately. Raw data is never printed.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time

UNIT = "codex-bridge-agent.service"
EXPECTED_ROOT = Path("/home/esteban/Sync/Projects/AI/CodexBridge-agent")
CONFIG = Path.home() / ".config/codexbridge/file-executor.json"
INBOX = Path.home() / ".local/state/codexbridge/file-inbox"
VALID_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,100}\Z")


class Refuse(RuntimeError):
    pass


def systemctl(*args: str) -> str:
    done = subprocess.run(["systemctl", "--user", *args], text=True,
                          capture_output=True, check=False, timeout=20)
    if done.returncode:
        raise Refuse("systemctl_failed")
    return done.stdout.strip()


def pid() -> int:
    value = systemctl("show", UNIT, "-p", "MainPID", "--value")
    if not value.isdecimal() or int(value) <= 0:
        raise Refuse("invalid_agent_pid")
    return int(value)


def preflight(request_id: str, inbox: Path = INBOX,
              config: Path = CONFIG, expected_root: Path = EXPECTED_ROOT) -> int:
    if not VALID_ID.fullmatch(request_id):
        raise Refuse("invalid_request_id")
    if systemctl("is-active", UNIT) != "active":
        raise Refuse("agent_inactive")
    current_pid = pid()
    root = expected_root.resolve(strict=True)
    if Path(os.readlink(f"/proc/{current_pid}/cwd")).resolve(strict=True) != root:
        raise Refuse("active_root_mismatch")
    if not config.is_file() or config.is_symlink():
        raise Refuse("config_unavailable")
    settings = json.loads(config.read_text(encoding="utf-8"))
    if (settings.get("project") != "codexbridge"
            or settings.get("branch") != "feature/file-instruction-ws-bridge"
            or Path(settings.get("root", "")).resolve(strict=True) != root
            or "unit-tests" not in settings.get("profiles", {})):
        raise Refuse("operator_config_mismatch")
    if inbox.is_symlink() or not inbox.is_dir() or inbox.stat().st_mode & 0o077:
        raise Refuse("inbox_not_private")
    if any((inbox / candidate).exists() for candidate in [
        request_id + ".json", request_id + ".running",
        request_id + "[DONE].json", "results/" + request_id + ".json",
    ]):
        raise Refuse("request_id_already_used")
    return current_pid


def observe(request_id: str, old_pid: int, inbox: Path,
            *, timeout: float = 100, poll: float = 0.025) -> dict:
    running = inbox / (request_id + ".running")
    receipt = inbox / "results" / (request_id + ".json")
    done = inbox / (request_id + "[DONE].json")
    deadline = time.monotonic() + timeout
    print("ARMED=" + request_id, flush=True)
    while not running.is_file():
        if receipt.exists() or done.exists():
            raise Refuse("task_completed_before_interruption")
        if time.monotonic() >= deadline:
            raise Refuse("task_not_observed_running")
        time.sleep(poll)
    if running.is_symlink():
        raise Refuse("unsafe_running_file")
    raw = running.read_bytes()
    instruction = json.loads(raw)
    if (instruction.get("requestId") != request_id
            or instruction.get("project") != "codexbridge"
            or instruction.get("branch") != "feature/file-instruction-ws-bridge"
            or instruction.get("profile") != "unit-tests"):
        raise Refuse("unexpected_running_instruction")
    if receipt.exists():
        raise Refuse("task_finished_before_restart")
    initial_digest = hashlib.sha256(raw).hexdigest()
    print("INTERRUPTION_TRIGGERED=true", flush=True)
    # Stop/restart only the one installed Agent. No SIGKILL to arbitrary PIDs.
    systemctl("restart", UNIT)
    while time.monotonic() < deadline + 30:
        if receipt.is_file() and done.is_file():
            result = json.loads(receipt.read_text(encoding="utf-8"))
            if (result.get("requestId") != request_id
                    or result.get("status") != "failed"
                    or result.get("reason") != "interrupted"
                    or result.get("instructionSha256") != initial_digest):
                raise Refuse("invalid_interrupted_receipt")
            if systemctl("is-active", UNIT) != "active":
                raise Refuse("agent_not_active")
            new_pid = pid()
            if new_pid == old_pid:
                raise Refuse("agent_pid_unchanged")
            # A repeated dispatch should only return this receipt, never
            # re-execute the original request ID. Gateway test is separate.
            if running.exists() or (inbox / (request_id + ".json")).exists():
                raise Refuse("instruction_not_finalized")
            print("LOCAL_OUTCOME=interrupted", flush=True)
            print("AGENT_RESTARTED=true", flush=True)
            print("RECEIPT_SHA256=" + hashlib.sha256(receipt.read_bytes()).hexdigest(), flush=True)
            print("GATEWAY_VERIFICATION_REQUIRED=true", flush=True)
            return result
        time.sleep(0.2)
    raise Refuse("interrupted_receipt_not_observed")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--request-id", required=True)
    parser.add_argument("--timeout", type=int, default=100)
    args = parser.parse_args(argv)
    try:
        old_pid = preflight(args.request_id)
        observe(args.request_id, old_pid, INBOX, timeout=args.timeout)
    except (Refuse, OSError, json.JSONDecodeError, subprocess.TimeoutExpired, ValueError) as exc:
        reason = str(exc) if isinstance(exc, Refuse) else type(exc).__name__
        print("ACCEPTANCE=FAILED", flush=True)
        print("REASON=" + reason, flush=True)
        return 1
    print("ACCEPTANCE=LOCAL_PASS", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
