"""Updater contracts: idempotence, fail-closed version checking, and safe packaging."""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

PATH = Path(__file__).resolve().parents[2] / "scripts/update_frida_gateway.py"
spec = importlib.util.spec_from_file_location("update_frida_gateway", PATH)
assert spec and spec.loader
updater = importlib.util.module_from_spec(spec)
spec.loader.exec_module(updater)


def test_no_restart_when_all_files_already_current() -> None:
    items = [
        {"path": "gateway/app/main.py", "expected_sha256": "a" * 64,
         "target_sha256": "b" * 64},
        {"path": "gateway/app/core/oauth.py", "expected_sha256": "c" * 64,
         "target_sha256": "d" * 64},
    ]
    assert updater.classify_installed(items, {
        "gateway/app/main.py": "b" * 64,
        "gateway/app/core/oauth.py": "d" * 64,
    }) == []


def test_partial_update_only_changes_outdated_files() -> None:
    items = [
        {"path": "gateway/app/main.py", "expected_sha256": "a" * 64,
         "target_sha256": "b" * 64},
        {"path": "gateway/app/core/oauth.py", "expected_sha256": "c" * 64,
         "target_sha256": "d" * 64},
    ]
    assert updater.classify_installed(items, {
        "gateway/app/main.py": "a" * 64,
        "gateway/app/core/oauth.py": "d" * 64,
    }) == ["gateway/app/main.py"]


def test_unknown_remote_baseline_blocks_every_update() -> None:
    items = [{"path": "gateway/app/main.py", "expected_sha256": "a" * 64,
              "target_sha256": "b" * 64}]
    with pytest.raises(ValueError, match="unknown_installed_baseline"):
        updater.classify_installed(items, {"gateway/app/main.py": "x" * 64})


def test_package_has_exact_allowlisted_paths_and_hashes(tmp_path: Path, monkeypatch) -> None:
    def fake_git_file(revision: str, name: str) -> bytes:
        if revision == updater.HISTORICAL_MAIN:
            return b"historical main"
        if revision == "origin/development":
            return b"development " + name.encode()
        return b"candidate " + name.encode()

    monkeypatch.setattr(updater, "git_file", fake_git_file)
    monkeypatch.setattr(updater, "HISTORICAL_MAIN_SHA", updater.sha(b"historical main"))
    manifest = updater.create_package(tmp_path, source_commit="a" * 40)
    assert [file["path"] for file in manifest["files"]] == list(updater.FILES)
    assert manifest["archive_sha256"] == updater.sha(
        (tmp_path / "package.tar.gz").read_bytes()
    )
    assert manifest["files"][0]["expected_sha256"] == updater.sha(b"historical main")



def test_previously_deployed_release_is_a_valid_upgrade_baseline() -> None:
    items = [{
        "path": "gateway/app/core/config.py",
        "expected_sha256": "a" * 64,
        "allowed_previous_sha256": ["b" * 64],
        "target_sha256": "c" * 64,
    }]
    assert updater.classify_installed(items, {
        "gateway/app/core/config.py": "b" * 64,
    }) == ["gateway/app/core/config.py"]
    assert updater.classify_installed(items, {
        "gateway/app/core/config.py": "c" * 64,
    }) == []


def test_browser_refresh_policy_keeps_short_access_tokens() -> None:
    from gateway.app.core.config import Settings
    fields = Settings.model_fields
    assert fields["oauth_browser_refresh_ttl_seconds"].default == 365 * 24 * 3600
    assert fields["oauth_access_token_ttl_seconds"].default == 3600
    assert fields["oauth_refresh_token_ttl_seconds"].default == 30 * 24 * 3600
