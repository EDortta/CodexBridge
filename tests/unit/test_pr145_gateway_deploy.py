"""No live services, SSH or evidence repository are accessed by these tests."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts import apply_pr145_gateway as remote
from scripts import deploy_pr145_gateway_with_evidence as local


def test_receipt_rejects_unexpected_fields_and_values(tmp_path):
    receipt = tmp_path / "result.json"
    original = {
        "status": "deployed", "reason": "none", "rollback": "not_needed",
        "gateway_healthy": True, "backup_created": True,
    }
    receipt.write_text(json.dumps(original))
    assert local.read_receipt(receipt) == original
    receipt.write_text(json.dumps({**original, "reason": "token-or-private-path"}))
    with pytest.raises(ValueError, match="invalid_receipt"):
        local.read_receipt(receipt)


@pytest.fixture
def environment(tmp_path, monkeypatch):
    home = tmp_path / "userhome"
    allowed = home / "codexbridge-staging"
    stage = allowed / "pr145-unit"
    stage.mkdir(parents=True)
    target = tmp_path / "gateway"
    target.mkdir()
    backup = tmp_path / "backup"
    backup.mkdir()
    old_contents = (b"old hub", b"old store")
    new_contents = (b"new hub", b"new store")
    old = tuple(hashlib.sha256(x).hexdigest() for x in old_contents)
    new = tuple(hashlib.sha256(x).hexdigest() for x in new_contents)
    monkeypatch.setattr(remote, "TARGET", target)
    monkeypatch.setattr(remote, "BACKUP_ROOT", backup)
    monkeypatch.setattr(remote, "OLD", old)
    monkeypatch.setattr(remote, "NEW", new)
    monkeypatch.setattr(remote.os, "geteuid", lambda: 0)
    monkeypatch.setenv("SUDO_USER", "tester")
    monkeypatch.setattr(remote.pwd, "getpwnam",
                        lambda _name: SimpleNamespace(pw_dir=str(home)))
    monkeypatch.setattr(remote.os, "chown", lambda *_args: None)
    for name, old_bytes, new_bytes in zip(remote.FILES, old_contents, new_contents):
        (target / name).write_bytes(old_bytes)
        # Files must be syntactically valid Python for the patch preflight.
        (stage / name).write_bytes(b"value = " + repr(new_bytes).encode() + b"\n")
    new = tuple(hashlib.sha256((stage / name).read_bytes()).hexdigest()
                for name in remote.FILES)
    monkeypatch.setattr(remote, "NEW", new)
    (stage / "manifest.json").write_text(json.dumps({
        "schema": 1, "profile": "pr145-gateway",
        "old_sha256": list(old), "new_sha256": list(new),
    }))
    monkeypatch.setattr(remote, "healthy", lambda: True)
    return stage, target, backup, old, new


def test_patch_happy_path_and_idempotency(environment, monkeypatch):
    stage, target, backup, old, new = environment
    monkeypatch.setattr(remote, "restart", lambda: True)
    monkeypatch.setattr(remote, "wait_healthy", lambda *_args: True)
    first = remote.apply(stage)
    assert first["status"] == "deployed"
    assert first["backup_created"] is True
    assert first["gateway_healthy"] is True
    assert tuple(remote.digest(target / name) for name in remote.FILES) == new
    assert (backup / stage.name / "agent_hub.py").exists()
    second = remote.apply(stage)
    assert second["status"] == "already_current"


def test_patch_rolls_back_when_new_gateway_never_becomes_healthy(
    environment, monkeypatch
):
    stage, target, backup, old, new = environment
    monkeypatch.setattr(remote, "restart", lambda: True)
    calls = iter([False, True])
    monkeypatch.setattr(remote, "wait_healthy", lambda *_args: next(calls))
    monkeypatch.setattr(remote, "diagnosis", lambda *_args: None)
    result = remote.apply(stage)
    assert result["status"] == "failed"
    assert result["rollback"] == "success"
    assert result["gateway_healthy"] is True
    assert tuple(remote.digest(target / name) for name in remote.FILES) == old


def test_patch_reports_failed_rollback(environment, monkeypatch):
    stage, target, backup, old, new = environment
    monkeypatch.setattr(remote, "restart", lambda: True)
    monkeypatch.setattr(remote, "wait_healthy", lambda *_args: False)
    monkeypatch.setattr(remote, "diagnosis", lambda *_args: None)
    result = remote.apply(stage)
    assert result["status"] == "failed"
    assert result["rollback"] == "failed"
    assert tuple(remote.digest(target / name) for name in remote.FILES) == old


def test_unknown_existing_baseline_rejected_without_restart(environment, monkeypatch):
    stage, target, backup, old, new = environment
    (target / "store.py").write_text("unknown")
    calls = []
    monkeypatch.setattr(remote, "restart", lambda: calls.append(True))
    result = remote.apply(stage)
    assert result["reason"] == "unknown_installed_baseline"
    assert result["backup_created"] is False
    assert calls == []


def test_bad_staging_hash_rejected_before_touching_gateway(environment):
    stage, target, backup, old, new = environment
    (stage / "store.py").write_text("changed")
    result = remote.apply(stage)
    assert result["reason"] == "stage_hash_mismatch"
    assert result["backup_created"] is False
    assert tuple(remote.digest(target / name) for name in remote.FILES) == old
