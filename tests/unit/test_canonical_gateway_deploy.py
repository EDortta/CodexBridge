"""Canonical gateway deploy: deterministic tests, no SSH or live service changes."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts import deploy_gateway as client
from scripts import gateway_deploy_worker as worker


def checksum(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


@pytest.fixture
def simulated(tmp_path, monkeypatch):
    base = tmp_path / "home" / "esteban" / "codexbridge-staging"
    stage = base / "gw-20261127T150000Z-1234abcd"
    stage.mkdir(parents=True)
    root = tmp_path / "opt" / "codex-bridge"
    (root / "gateway/app/services").mkdir(parents=True)
    backups = tmp_path / "backups"
    backups.mkdir()
    old = (b"variable = 1\n", b"variable = 2\n")
    new = (b"variable = 3\n", b"variable = 4\n")
    paths = ("gateway/app/services/agent_hub.py", "gateway/app/services/store.py")
    files = []
    for name, previous, desired in zip(paths, old, new):
        target = root / name
        target.write_bytes(previous)
        staged = stage / name
        staged.parent.mkdir(parents=True, exist_ok=True)
        staged.write_bytes(desired)
        files.append({
            "path": name,
            "previous_sha256": checksum(previous),
            "target_sha256": checksum(desired),
        })
    (stage / "manifest.json").write_text(json.dumps({
        "schema": 1, "target": "frida", "profile": "code-only",
        "commit": "abc", "files": files,
    }))
    monkeypatch.setattr(worker, "DEST", root)
    monkeypatch.setattr(worker, "BACKUPS", backups)
    # Worker validates against a fixed trusted frida staging root.
    # Mock Path.resolve only for the allowlist literal in this test:
    original = Path.resolve
    def relocated(self, *args, **kwargs):
        if str(self) == "/home/esteban/codexbridge-staging":
            return original(base, *args, **kwargs)
        return original(self, *args, **kwargs)
    monkeypatch.setattr(Path, "resolve", relocated)
    monkeypatch.setattr(worker.os, "chown", lambda *_args: None)
    monkeypatch.setattr(worker, "health", lambda: True)
    return stage, root, backups, files, old, new


def test_worker_deploy_and_idempotency(simulated, monkeypatch):
    stage, root, backups, files, old, new = simulated
    monkeypatch.setattr(worker, "restart", lambda: True)
    monkeypatch.setattr(worker, "ready", lambda *a: True)
    result = worker.apply(stage)
    assert result["status"] == "deployed"
    assert result["healthy"] is True
    assert (backups / stage.name / files[0]["path"]).read_bytes() == old[0]
    assert worker.apply(stage)["status"] == "already_current"


def test_worker_rolls_back_after_failed_health(simulated, monkeypatch):
    stage, root, backups, files, old, new = simulated
    monkeypatch.setattr(worker, "restart", lambda: True)
    calls = iter([False, True])
    monkeypatch.setattr(worker, "ready", lambda *a: next(calls))
    monkeypatch.setattr(worker, "journal_local", lambda *_a: None)
    receipt = worker.apply(stage)
    assert receipt["status"] == "failed"
    assert receipt["rollback"] == "success"
    assert [ (root / item["path"]).read_bytes() for item in files ] == list(old)


def test_worker_detects_rollback_failure(simulated, monkeypatch):
    stage, root, backups, files, old, new = simulated
    monkeypatch.setattr(worker, "restart", lambda: True)
    monkeypatch.setattr(worker, "ready", lambda *a: False)
    monkeypatch.setattr(worker, "journal_local", lambda *_a: None)
    receipt = worker.apply(stage)
    assert receipt["status"] == "failed"
    assert receipt["rollback"] == "failed"
    assert receipt["reason"] == "rollback_failed"


def test_unknown_baseline_never_restarts(simulated, monkeypatch):
    stage, root, backups, files, old, new = simulated
    (root / files[0]["path"]).write_bytes(b"unknown")
    touched = []
    monkeypatch.setattr(worker, "restart", lambda: touched.append(True))
    assert worker.apply(stage)["reason"] == "baseline_unknown"
    assert not touched


def test_manifest_tamper_never_restarts(simulated, monkeypatch):
    stage, root, backups, files, old, new = simulated
    (stage / files[1]["path"]).write_bytes(b"tampered")
    touched = []
    monkeypatch.setattr(worker, "restart", lambda: touched.append(True))
    assert worker.apply(stage)["reason"] == "invalid_manifest"
    assert not touched


def test_local_ids_and_resume_reference(tmp_path, monkeypatch):
    monkeypatch.setattr(client, "JOBS", tmp_path)
    record = {
        "id": "gw-20261127T150000Z-1234abcd", "state": "remote_started",
        "branch": "development", "commit": "a" * 40, "files": [],
    }
    client.save(record)
    assert client.load(record["id"]) == record
    with pytest.raises(ValueError):
        client.file_path("../../secrets")


def test_receipt_rejects_untrusted_values(tmp_path, monkeypatch):
    monkeypatch.setattr(client, "JOBS", tmp_path)
    job = {"id": "gw-20261127T150000Z-1234abcd"}
    local = tmp_path / job["id"]
    local.mkdir()
    receipt = local / "result.json"
    monkeypatch.setattr(client, "run", lambda *_a, **_kw: SimpleNamespace(returncode=0))
    receipt.write_text(json.dumps({
        "id": job["id"], "status": "deployed", "reason": "none",
        "rollback": "not_needed", "healthy": True,
    }))
    assert client.fetch_receipt(job)["status"] == "deployed"
    receipt.write_text(json.dumps({
        "id": job["id"], "status": "deployed",
        "reason": "/private/path", "rollback": "not_needed", "healthy": True,
    }))
    with pytest.raises(ValueError):
        client.fetch_receipt(job)


def test_disconnected_remote_is_not_relaunched(tmp_path, monkeypatch):
    monkeypatch.setattr(client, "JOBS", tmp_path)
    job = {
        "id": "gw-20261127T150000Z-1234abcd",
        "state": "remote_started", "branch": "development",
        "commit": "b" * 40, "files": [], "evidence": "pending",
    }
    client.save(job)
    monkeypatch.setattr(client, "fetch_receipt", lambda *_a: None)
    assert client.reconcile(job) == 3
    assert client.load(job["id"])["state"] == "remote_pending_or_unreachable"


def test_publish_failure_not_misreported_as_success(tmp_path, monkeypatch):
    monkeypatch.setattr(client, "JOBS", tmp_path)
    job = {
        "id": "gw-20261127T150000Z-1234abcd", "state": "remote_started",
        "branch": "development", "commit": "b" * 40, "files": [],
    }
    client.save(job)
    monkeypatch.setattr(client, "fetch_receipt", lambda *_a: {
        "id": job["id"], "status": "deployed", "rollback": "not_needed",
        "healthy": True, "reason": "none",
    })
    monkeypatch.setattr(client, "publish", lambda *_a: False)
    assert client.reconcile(job) == 1
    assert client.load(job["id"])["state"] == "success"
    assert client.load(job["id"])["evidence"] == "pending"
