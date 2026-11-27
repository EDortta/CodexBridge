"""Agent release preflight. No live service or worktree changes."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts import deploy_agent


def test_explicit_apply_denied_before_side_effects(monkeypatch, capsys):
    monkeypatch.setattr(deploy_agent, "check_current_agent",
                        lambda: pytest.fail("must not inspect service on denied apply"))
    assert deploy_agent.main(["--apply"]) == 2
    assert "transactional_agent_release_not_implemented" in capsys.readouterr().err


def test_read_only_preflight_matches_live_branch_and_root(tmp_path, monkeypatch):
    worktree = tmp_path / "agent"
    worktree.mkdir()
    (worktree / ".git").mkdir()
    for name in deploy_agent.EXPECTED_FILES:
        path = worktree / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("value = 1\n")
    cfg = tmp_path / "file-executor.json"
    cfg.write_text(json.dumps({"project": "codexbridge",
                               "branch": "feature/file-instruction-ws-bridge",
                               "root": str(worktree)}))
    proc = tmp_path / "proc"
    proc.mkdir()
    (proc / "cwd").symlink_to(worktree)
    (proc / "environ").write_bytes(
        b"CODEX_BRIDGE_AGENT_FILE_EXECUTOR_CONFIG_FILE=" +
        str(cfg).encode() + b"\0"
    )
    original = deploy_agent.Path
    # Replace only proc lookup without modifying host /proc.
    monkeypatch.setattr(deploy_agent.os, "readlink", lambda _p: str(worktree))
    monkeypatch.setattr(deploy_agent, "ROOT", worktree)
    old_read = original.read_bytes
    def patched_read(self):
        if str(self) == "/proc/1234/environ":
            return (proc / "environ").read_bytes()
        return old_read(self)
    monkeypatch.setattr(original, "read_bytes", patched_read)
    props = {"ActiveState": "active", "MainPID": "1234",
             "WorkingDirectory": str(worktree)}
    monkeypatch.setattr(deploy_agent, "systemd_property", lambda name: props[name])
    def fake_command(*cmd):
        if "status" in cmd:
            return ""
        if "branch" in cmd:
            return "feature/file-instruction-ws-bridge"
        if "rev-parse" in cmd:
            return "1" * 40
        raise AssertionError(cmd)
    monkeypatch.setattr(deploy_agent, "command", fake_command)
    result = deploy_agent.check_current_agent()
    assert result["status"] == "preflight_ok"
    assert result["candidate_is_live"]
    assert result["deployment_supported"] is False


def test_unhealthy_agent_denied(monkeypatch):
    monkeypatch.setattr(deploy_agent, "systemd_property", lambda k: "inactive")
    with pytest.raises(deploy_agent.PreflightError, match="agent_inactive"):
        deploy_agent.check_current_agent()
