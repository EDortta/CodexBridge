"""Bounded, operator-configured file instruction executor (no LLM and no shell).

The inbox is trusted transport output, NOT authorization. Only operator-owned
configuration can bind a project, branch and preapproved command profiles.
"""
from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import tempfile
import time
from datetime import datetime, timezone

IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,100}\Z")
MAX_INSTRUCTION = 16_384
MAX_LOG = 16_384


def _utc():
    return datetime.now(timezone.utc).isoformat()


def _atomic_json(path: Path, value: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=".tmp-", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as out:
            json.dump(value, out, sort_keys=True, separators=(",", ":"))
            out.write("\n")
            out.flush()
            os.fsync(out.fileno())
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def _read_instruction(path: Path):
    if path.is_symlink() or not path.is_file() or path.stat().st_size > MAX_INSTRUCTION:
        raise ValueError("unsafe instruction file")
    with path.open("rb") as source:
        raw = source.read(MAX_INSTRUCTION + 1)
    if len(raw) > MAX_INSTRUCTION:
        raise ValueError("instruction too large")
    data = json.loads(raw)
    if not isinstance(data, dict) or set(data) != {
        "schemaVersion", "requestId", "project", "branch", "profile"
    }:
        raise ValueError("invalid instruction fields")
    if type(data["schemaVersion"]) is not int or data["schemaVersion"] != 1:
        raise ValueError("unsupported schema")
    for key in ("requestId", "project", "profile"):
        if not isinstance(data[key], str) or not IDENTIFIER.fullmatch(data[key]):
            raise ValueError("invalid " + key)
    if not isinstance(data["branch"], str) or not re.fullmatch(
        r"[A-Za-z0-9][A-Za-z0-9._/-]{0,127}", data["branch"]
    ) or ".." in data["branch"] or "//" in data["branch"]:
        raise ValueError("invalid branch")
    return data, hashlib.sha256(raw).hexdigest()


def _git_branch(root: Path):
    completed = subprocess.run(
        ["git", "-C", str(root), "symbolic-ref", "--quiet", "--short", "HEAD"],
        capture_output=True, text=True, timeout=8, check=False,
    )
    return completed.stdout.strip() if completed.returncode == 0 else None


def _execute(argv: list[str], cwd: Path, seconds: int):
    """No shell; isolated process group; bounded persisted output."""
    with tempfile.TemporaryFile() as out:
        process = subprocess.Popen(
            argv, cwd=cwd, stdin=subprocess.DEVNULL,
            stdout=out, stderr=subprocess.STDOUT,
            start_new_session=True,
            env={"PATH": os.defpath, "HOME": str(cwd), "LANG": "C", "LC_ALL": "C"},
        )
        timed_out = False
        try:
            return_code = process.wait(timeout=seconds)
        except subprocess.TimeoutExpired:
            timed_out = True
            os.killpg(process.pid, signal.SIGKILL)
            return_code = process.wait()
        size = out.tell()
        out.seek(0)
        snippet = out.read(MAX_LOG).decode("utf-8", errors="replace")
    return return_code, timed_out, snippet, size > MAX_LOG


def _record(inbox: Path, result: dict, filename: str):
    _atomic_json(inbox / "results" / (filename + ".json"), result)


def process_once(inbox: Path, config: dict) -> list[dict]:
    """Serialize all processes for one inbox; restart fails closed."""
    inbox.mkdir(parents=True, exist_ok=True)
    results: list[dict] = []
    lock = inbox / ".executor.lock"
    with lock.open("a+") as lockfile:
        fcntl.flock(lockfile, fcntl.LOCK_EX)
        (inbox / "results").mkdir(exist_ok=True)
        for path in sorted(inbox.iterdir()):
            if path.name.endswith(".running"):
                ident = path.name[:-8]
                existing = inbox / "results" / (ident + ".json")
                if existing.is_file():
                    os.replace(path, inbox / (ident + "[DONE].json"))
                    continue
                outcome = {
                    "requestId": ident, "status": "failed", "reason": "interrupted",
                    "finishedAt": _utc(), "exitCode": None
                }
                _record(inbox, outcome, ident)
                os.replace(path, inbox / (ident + "[DONE].json"))
                results.append(outcome)
        for path in sorted(inbox.glob("*.json")):
            if path.name.endswith("[DONE].json") or path.is_symlink():
                continue
            ident = path.stem
            if not IDENTIFIER.fullmatch(ident):
                continue
            # A completed request ID is immutable: never execute a replay.
            if (inbox / "results" / (ident + ".json")).exists():
                os.replace(path, inbox / (ident + "[DONE].json"))
                results.append({"requestId": ident, "status": "failed",
                                "reason": "duplicate_request", "exitCode": None})
                continue
            claimed = inbox / (ident + ".running")
            os.replace(path, claimed)
            started = _utc()
            outcome = {"requestId": ident, "startedAt": started, "status": "failed",
                       "exitCode": None}
            try:
                data, digest = _read_instruction(claimed)
                outcome["instructionSha256"] = digest
                if data["requestId"] != ident:
                    raise ValueError("requestId does not match filename")
                if data["project"] != config["project"] or data["branch"] != config["branch"]:
                    raise ValueError("project or branch mismatch")
                profiles = config["profiles"]
                if data["profile"] not in profiles:
                    raise ValueError("profile not authorized")
                profile = profiles[data["profile"]]
                argv = profile["argv"]
                seconds = profile["timeout_seconds"]
                if (not isinstance(argv, list) or not 1 <= len(argv) <= 20
                    or any(not isinstance(x, str) or not x or len(x) > 512 for x in argv)
                    or type(seconds) is not int or not 1 <= seconds <= 600):
                    raise ValueError("invalid operator profile")
                root = Path(config["root"]).resolve(strict=True)
                if not root.is_dir() or _git_branch(root) != config["branch"]:
                    raise ValueError("working tree branch mismatch")
                outcome["profile"] = data["profile"]
                code, timed_out, log, truncated = _execute(argv, root, seconds)
                outcome.update(exitCode=code, timedOut=timed_out,
                               output=log, outputTruncated=truncated,
                               status="success" if code == 0 and not timed_out else "failed")
            except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError,
                    subprocess.SubprocessError) as exc:
                outcome["reason"] = type(exc).__name__
            outcome["finishedAt"] = _utc()
            _record(inbox, outcome, ident)
            os.replace(claimed, inbox / (ident + "[DONE].json"))
            results.append(outcome)
    return results


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--inbox", type=Path, required=True)
    args = parser.parse_args(argv)
    if args.config.is_symlink():
        parser.error("operator config cannot be a symlink")
    config = json.loads(args.config.read_text(encoding="utf-8"))
    if not isinstance(config, dict) or set(config) != {"project", "branch", "root", "profiles"}:
        parser.error("invalid operator configuration")
    print(json.dumps(process_once(args.inbox, config), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
