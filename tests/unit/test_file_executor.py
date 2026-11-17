"""Contract tests for deterministic file-based execution; use real subprocesses."""
import json
from pathlib import Path
import subprocess
import sys

from agent.codex_bridge_agent.file_executor import process_once


def setup(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    subprocess.run(["git", "-C", str(root), "checkout", "-q", "-b", "feature/test"], check=True)
    config = {
        "project": "demo", "branch": "feature/test", "root": str(root),
        "profiles": {
            "pass": {"argv": [sys.executable, "-c", "print('verified')"], "timeout_seconds": 5},
            "fail": {"argv": [sys.executable, "-c", "raise SystemExit(7)"], "timeout_seconds": 5},
            "slow": {"argv": [sys.executable, "-c", "import time;time.sleep(10)"], "timeout_seconds": 1},
        },
    }
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    return inbox, config


def add(inbox, request="task1", branch="feature/test", profile="pass"):
    (inbox / (request + ".json")).write_text(json.dumps({
        "schemaVersion": 1, "requestId": request, "project": "demo",
        "branch": branch, "profile": profile,
    }), encoding="utf-8")


def test_success_and_done(tmp_path):
    inbox, config = setup(tmp_path)
    add(inbox)
    result, = process_once(inbox, config)
    assert result["status"] == "success"
    assert result["exitCode"] == 0
    assert result["output"].strip() == "verified"
    assert (inbox / "task1[DONE].json").is_file()
    assert process_once(inbox, config) == []


def test_failure_and_timeout(tmp_path):
    inbox, config = setup(tmp_path)
    add(inbox, request="failure", profile="fail")
    add(inbox, request="timeout", profile="slow")
    results = process_once(inbox, config)
    assert {r["requestId"]: r["exitCode"] for r in results}["failure"] == 7
    assert next(r for r in results if r["requestId"] == "timeout")["timedOut"] is True
    assert all(r["status"] == "failed" for r in results)


def test_reject_wrong_branch_and_unlisted_profile(tmp_path):
    inbox, config = setup(tmp_path)
    add(inbox, request="wrong", branch="feature/other")
    add(inbox, request="notallowed", profile="shell")
    assert all(r["status"] == "failed" for r in process_once(inbox, config))


def test_recovery_fails_closed_without_replay(tmp_path):
    inbox, config = setup(tmp_path)
    (inbox / "interrupted.running").write_text("{}", encoding="utf-8")
    result, = process_once(inbox, config)
    assert result["reason"] == "interrupted"
    assert (inbox / "interrupted[DONE].json").is_file()


def test_invalid_fields_rejected(tmp_path):
    inbox, config = setup(tmp_path)
    (inbox / "bad.json").write_text(json.dumps({
        "schemaVersion": 1, "requestId": "bad", "project": "demo",
        "branch": "feature/test", "profile": "pass", "shell": "touch /tmp/pwn",
    }), encoding="utf-8")
    result, = process_once(inbox, config)
    assert result["status"] == "failed"
    assert result["reason"] == "ValueError"


def test_duplicate_result_never_executes_twice(tmp_path):
    inbox, config = setup(tmp_path)
    add(inbox)
    process_once(inbox, config)
    original = (inbox / "results/task1.json").read_text()
    add(inbox)
    result, = process_once(inbox, config)
    assert result["status"] == "failed"
    assert result["reason"] == "duplicate_request"
    assert (inbox / "results/task1.json").read_text() == original
