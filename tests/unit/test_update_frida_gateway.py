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



def test_websocket_gateway_and_agent_hub_contract_are_deployed_together() -> None:
    """Prevent the exact frida 1012 shutdown TypeError seen on 2026-11-17."""
    import ast
    assert "gateway/app/main.py" in updater.FILES
    assert "gateway/app/services/agent_hub.py" in updater.FILES

    root = Path(__file__).resolve().parents[2]
    hub_file = root / "gateway/app/services/agent_hub.py"
    main_file = root / "gateway/app/main.py"
    tree = ast.parse(hub_file.read_text(encoding="utf-8"))
    hub = next(x for x in tree.body if isinstance(x, ast.ClassDef) and x.name == "AgentHub")
    unregister = next(x for x in hub.body if isinstance(x, ast.AsyncFunctionDef) and x.name == "unregister")
    positional = [arg.arg for arg in unregister.args.args]
    assert positional[:3] == ["self", "executor_id", "websocket"]

    main = ast.parse(main_file.read_text(encoding="utf-8"))
    calls = [
        x for x in ast.walk(main)
        if isinstance(x, ast.Call) and isinstance(x.func, ast.Attribute)
        and x.func.attr == "unregister"
        and isinstance(x.func.value, ast.Name)
        and x.func.value.id == "hub"
    ]
    assert calls
    assert all(len(x.args) == 2 for x in calls)
