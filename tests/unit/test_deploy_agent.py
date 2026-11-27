"""Canonical Agent deployment regression tests — no live systemd or Git changes."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from scripts import deploy_agent as client
from scripts import agent_release_worker as worker


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def test_check_is_read_only(monkeypatch, capsys):
    monkeypatch.setattr(client, "preflight", lambda: {
        "source_commit": "a" * 40,
        "baseline_commit": "b" * 40,
    })
    monkeypatch.setattr(client, "start", lambda *_a: pytest.fail("unexpected deploy"))
    assert client.main(["--check"]) == 0
    assert "PREFLIGHT=OK" in capsys.readouterr().out


def test_bad_id_is_rejected():
    with pytest.raises(ValueError):
        client.path_for("../../secrets")


def test_closed_terminal_reconciliation_never_restarts(tmp_path, monkeypatch):
    monkeypatch.setattr(client, "JOBS", tmp_path)
    ident = "ag-20261127T180000Z-1234abcd"
    job = {"id": ident, "state": "running", "source_commit": "a" * 40,
           "baseline_commit": "b" * 40, "hashes": [], "evidence": "pending"}
    client.save(job)
    monkeypatch.setattr(client, "fetch", lambda *_a: None)
    monkeypatch.setattr(client, "start", lambda *_a: pytest.fail("must not restart"))
    assert client.main(["--resume", ident]) == 3
    assert client.load(ident)["state"] == "pending"


def test_publication_failure_not_called_success(tmp_path, monkeypatch):
    monkeypatch.setattr(client, "JOBS", tmp_path)
    ident = "ag-20261127T180000Z-1234abcd"
    job = {"id": ident, "state": "running", "source_commit": "a" * 40,
           "baseline_commit": "b" * 40, "hashes": [], "evidence": "pending"}
    client.save(job)
    monkeypatch.setattr(client, "fetch", lambda *_a: {
        "id": ident, "status": "deployed", "reason": "none",
        "rollback": "not_needed", "service_active": True, "ws_verified": False,
    })
    monkeypatch.setattr(client, "publish", lambda *_a: False)
    assert client.reconcile(job) == 1
    assert client.load(ident)["state"] == "success"
    assert client.load(ident)["evidence"] == "pending"


@pytest.fixture
def release(tmp_path, monkeypatch):
    root = tmp_path / "active"
    root.mkdir()
    (root / ".git").mkdir()
    stage = tmp_path / "stage"
    stage.mkdir()
    old_contents = (b"v = 1\n", b"v = 2\n")
    new_contents = (b"v = 3\n", b"v = 4\n")
    originals = {}
    targets = {}
    for name, old, new in zip(worker.FILES, old_contents, new_contents):
        dest = root / name
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(old)
        staged = stage / name
        staged.parent.mkdir(parents=True, exist_ok=True)
        staged.write_bytes(new)
        originals[name] = sha(old)
        targets[name] = sha(new)
    (stage / "manifest.json").write_text(json.dumps({
        "schema": 1, "profile": "agent-pr145", "files": list(worker.FILES),
        "active_root": str(root), "baseline_commit": "a" * 40,
        "source_commit": "b" * 40, "baseline_sha256": originals,
        "desired_sha256": targets,
    }))
    cfg = tmp_path / "file-executor.json"
    cfg.write_text(json.dumps({
        "project": "codexbridge",
        "branch": "feature/file-instruction-ws-bridge",
        "root": str(root),
    }))
    monkeypatch.setattr(worker, "ACTIVE_ROOT", root)
    monkeypatch.setattr(worker, "OPERATOR_CONFIG", cfg)
    monkeypatch.setattr(worker, "service_pid", lambda: 1234)
    monkeypatch.setattr(worker.os, "readlink", lambda _x: str(root))
    state = {"head": "a" * 40, "dirty": False}
    def fake_git(_root, *arguments):
        operation = arguments[0]
        if operation == "branch": return "feature/file-instruction-ws-bridge"
        if operation == "rev-parse": return state["head"]
        if operation == "status": return ""
        if operation == "add": return ""
        if operation == "commit":
            state["head"] = "c" * 40
            return ""
        if operation == "revert":
            for name, old in zip(worker.FILES, old_contents):
                (root / name).write_bytes(old)
            state["head"] = "d" * 40
            return ""
        if operation == "reset": return ""
        raise AssertionError(arguments)
    monkeypatch.setattr(worker, "git", fake_git)
    monkeypatch.setattr(worker, "restart", lambda: True)
    monkeypatch.setattr(worker, "ready", lambda *_a: True)
    return stage, root, originals, targets, state


def test_worker_deploy_creates_release_commit(release):
    stage, root, originals, targets, state = release
    result = worker.apply(stage)
    assert result["status"] == "deployed"
    assert result["rollback"] == "not_needed"
    assert result["service_active"] is True
    assert result["ws_verified"] is False
    assert state["head"] == "c" * 40
    assert all(worker.digest(root / name) == targets[name] for name in worker.FILES)


def test_worker_rollback_after_unhealthy_restart(release, monkeypatch):
    stage, root, originals, targets, state = release
    outcomes = iter([False, True])
    monkeypatch.setattr(worker, "ready", lambda *_a: next(outcomes))
    result = worker.apply(stage)
    assert result["status"] == "failed"
    assert result["rollback"] == "success"
    assert state["head"] == "d" * 40
    assert all(worker.digest(root / name) == originals[name] for name in worker.FILES)


def test_worker_failed_rollback_reports_failure(release, monkeypatch):
    stage, root, originals, targets, state = release
    monkeypatch.setattr(worker, "ready", lambda *_a: False)
    result = worker.apply(stage)
    assert result["status"] == "failed"
    assert result["rollback"] == "failed"
    assert result["reason"] == "rollback_failed"


def test_worker_mismatched_worktree_is_rejected_before_changes(release):
    stage, root, originals, targets, state = release
    (root / worker.FILES[0]).write_text("unexpected change\n")
    result = worker.apply(stage)
    assert result["status"] == "failed"
    assert result["reason"] == "installed_mismatch"
    assert state["head"] == "a" * 40


def test_worker_wrong_config_branch_rejected(release):
    stage, root, originals, targets, state = release
    worker.OPERATOR_CONFIG.write_text(json.dumps({
        "branch": "development", "root": str(root)
    }))
    result = worker.apply(stage)
    assert result["reason"] == "config_mismatch"
    assert state["head"] == "a" * 40
