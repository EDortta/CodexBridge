#!/usr/bin/env python3
"""Safe live drill: kill the deploy *client*, not the Agent or deploy worker.

A transient user-systemd worker persists a probe receipt. This script
terminates only a child client after it launched that worker, then proves
the detached worker still finished and retained a verifiable result.
No Agent restart, Git modification, or --apply invocation.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import secrets
import subprocess
import sys
import time

ROOT = Path.home() / ".local/state/codexbridge/agent-deploy/recovery-probes"


class ProbeError(RuntimeError):
    pass


def atomically_write(path: Path, data: dict) -> None:
    tmp = path.with_name("." + path.name + ".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as out:
            json.dump(data, out, sort_keys=True)
            out.write("\n")
            out.flush()
            os.fsync(out.fileno())
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)


def validated_stage(stage: Path) -> Path:
    if stage.is_symlink() or not stage.is_dir():
        raise ProbeError("stage_invalid")
    stage = stage.resolve(strict=True)
    if stage.parent != ROOT.resolve(strict=True) or not stage.name.startswith("probe-"):
        raise ProbeError("unexpected_stage")
    if stage.stat().st_mode & 0o077:
        raise ProbeError("stage_not_private")
    return stage


def probe_worker(stage: Path) -> None:
    stage = validated_stage(stage)
    marker = stage / "worker-receipt.json"
    if marker.exists():
        raise ProbeError("receipt_already_exists")
    time.sleep(3)
    atomically_write(marker, {"schema": 1, "id": stage.name,
                              "result": "detached_completed"})


def probe_client(stage: Path) -> None:
    stage = validated_stage(stage)
    unit = "codexbridge-agent-recovery-" + stage.name.removeprefix("probe-")
    cmd = ["systemd-run", "--user", "--quiet", "--collect",
           "--unit=" + unit, sys.executable, str(Path(__file__).resolve()),
           "--probe-worker", str(stage)]
    started = subprocess.run(cmd, capture_output=True, check=False, timeout=18)
    if started.returncode:
        raise ProbeError("systemd_run_failed")
    atomically_write(stage / "client-started.json",
                     {"schema": 1, "id": stage.name, "start_ack": True})
    # Expected to be terminated by orchestrator before worker finishes.
    time.sleep(15)


def drill() -> None:
    ROOT.mkdir(parents=True, exist_ok=True, mode=0o700)
    if ROOT.is_symlink() or ROOT.stat().st_mode & 0o077:
        raise ProbeError("root_not_private")
    stage = ROOT / ("probe-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
                    + "-" + secrets.token_hex(4))
    stage.mkdir(mode=0o700)
    client = subprocess.Popen(
        [sys.executable, str(Path(__file__).resolve()), "--probe-client", str(stage)],
        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL, start_new_session=True,
    )
    ack = stage / "client-started.json"
    deadline = time.monotonic() + 20
    try:
        while not ack.is_file():
            if client.poll() is not None:
                raise ProbeError("client_failed_to_start_worker")
            if time.monotonic() >= deadline:
                raise ProbeError("client_start_timeout")
            time.sleep(0.05)
        started = json.loads(ack.read_text())
        if started != {"schema": 1, "id": stage.name, "start_ack": True}:
            raise ProbeError("client_start_ack_invalid")
        client.terminate()
        try:
            client.wait(timeout=4)
        except subprocess.TimeoutExpired:
            client.kill()
            client.wait(timeout=4)
        if client.poll() is None:
            raise ProbeError("client_still_running")
        print("CLIENT_TERMINATED=true", flush=True)
        receipt = stage / "worker-receipt.json"
        deadline = time.monotonic() + 15
        while not receipt.is_file():
            if time.monotonic() >= deadline:
                raise ProbeError("detached_worker_no_receipt")
            time.sleep(0.1)
        if json.loads(receipt.read_text()) != {
            "schema": 1, "id": stage.name, "result": "detached_completed"
        }:
            raise ProbeError("detached_receipt_invalid")
        fingerprint = hashlib.sha256(receipt.read_bytes()).hexdigest()
        print("DETACHED_WORKER=COMPLETED", flush=True)
        print("RECEIPT_SHA256=" + fingerprint, flush=True)
        print("AGENT_RESTARTED=false", flush=True)
        print("PROBE=PASS", flush=True)
    finally:
        if client.poll() is None:
            client.terminate()
            try:
                client.wait(timeout=4)
            except subprocess.TimeoutExpired:
                client.kill()
                client.wait(timeout=4)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--probe-client", metavar="STAGE", type=Path)
    modes.add_argument("--probe-worker", metavar="STAGE", type=Path)
    args = parser.parse_args(argv)
    try:
        if args.probe_worker:
            probe_worker(args.probe_worker)
        elif args.probe_client:
            probe_client(args.probe_client)
        else:
            drill()
        return 0
    except (ProbeError, OSError, ValueError, json.JSONDecodeError,
            subprocess.TimeoutExpired) as exc:
        category = str(exc) if isinstance(exc, ProbeError) else type(exc).__name__
        print("PROBE=FAILED")
        print("REASON=" + category)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
