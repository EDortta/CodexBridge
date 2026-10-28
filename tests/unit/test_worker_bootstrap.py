"""Provisioning must never print or overwrite a machine credential."""
import os
from pathlib import Path
import pytest
from scripts.worker_identity import write_secret
from test_worker_watch import worker_watch


def test_secret_created_owner_only(tmp_path):
    path = tmp_path / "worker-token"
    write_secret(path, "hello-secret")
    assert path.read_text() == "hello-secret\n"
    assert path.stat().st_mode & 0o777 == 0o600
    with pytest.raises(FileExistsError):
        write_secret(path, "another")
    assert path.read_text() == "hello-secret\n"


def test_owner_only_worker_token_file(monkeypatch, tmp_path):
    path = tmp_path / "token"
    path.write_text("token-from-file\n")
    path.chmod(0o600)
    monkeypatch.setenv("CODEXBRIDGE_WORKER_TOKEN_FILE", str(path))
    assert worker_watch.credential_env("CODEXBRIDGE_WORKER_TOKEN") == "token-from-file"
    path.chmod(0o644)
    with pytest.raises(ValueError, match="owner-only"):
        worker_watch.credential_env("CODEXBRIDGE_WORKER_TOKEN")


def test_missing_file_fails_closed(monkeypatch, tmp_path):
    monkeypatch.setenv("CODEXBRIDGE_WORKER_TOKEN_FILE", str(tmp_path / "missing"))
    with pytest.raises(ValueError):
        worker_watch.credential_env("CODEXBRIDGE_WORKER_TOKEN")
