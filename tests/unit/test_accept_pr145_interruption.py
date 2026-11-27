"""Non-disruptive tests of the PR145 live interruption observer."""
import hashlib
import json
from pathlib import Path
import pytest

from scripts import accept_pr145_interruption as acceptance


def test_rejects_invalid_request_id(tmp_path):
    with pytest.raises(acceptance.Refuse, match="invalid_request_id"):
        acceptance.preflight("../wrong", tmp_path, tmp_path / "none", tmp_path)


def test_refuses_used_request_id(tmp_path, monkeypatch):
    root = tmp_path / "source"
    root.mkdir()
    inbox = tmp_path / "inbox"
    inbox.mkdir(mode=0o700)
    config = tmp_path / "config.json"
    config.write_text(json.dumps({
        "project": "codexbridge", "branch": "feature/file-instruction-ws-bridge",
        "root": str(root), "profiles": {"unit-tests": {"argv": ["pytest"], "timeout_seconds": 180}},
    }))
    (inbox / "request-1.running").write_text("{}")
    monkeypatch.setattr(acceptance, "systemctl", lambda *_a: "active")
    monkeypatch.setattr(acceptance, "pid", lambda: 123)
    monkeypatch.setattr(acceptance.os, "readlink", lambda *_a: str(root))
    with pytest.raises(acceptance.Refuse, match="request_id_already_used"):
        acceptance.preflight("request-1", inbox, config, root)


def test_observer_refuses_already_completed_task_without_restart(tmp_path, monkeypatch):
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    (inbox / "results").mkdir()
    request_id = "pr145-accept-001"
    (inbox / "results" / (request_id + ".json")).write_text("{}")
    monkeypatch.setattr(acceptance, "systemctl", lambda *_a: pytest.fail("restart forbidden"))
    with pytest.raises(acceptance.Refuse, match="task_completed_before_interruption"):
        acceptance.observe(request_id, 123, inbox, timeout=0.2, poll=0.01)


def test_live_interruption_receipt_must_match_original_instruction(tmp_path, monkeypatch):
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    (inbox / "results").mkdir()
    request_id = "pr145-accept-001"
    instruction = {
        "requestId": request_id, "project": "codexbridge",
        "branch": "feature/file-instruction-ws-bridge", "profile": "unit-tests",
    }
    encoded = json.dumps(instruction).encode()
    running = inbox / (request_id + ".running")
    running.write_bytes(encoded)
    state = {"restart": 0}
    def fake_systemctl(*arguments):
        if arguments[0] == "restart":
            state["restart"] += 1
            running.rename(inbox / (request_id + "[DONE].json"))
            receipt = {
                "requestId": request_id, "status": "failed",
                "reason": "interrupted",
                "instructionSha256": hashlib.sha256(encoded).hexdigest(),
            }
            (inbox / "results" / (request_id + ".json")).write_text(json.dumps(receipt))
            return ""
        if arguments[0] == "is-active":
            return "active"
        raise AssertionError(arguments)
    monkeypatch.setattr(acceptance, "systemctl", fake_systemctl)
    monkeypatch.setattr(acceptance, "pid", lambda: 456)
    result = acceptance.observe(request_id, 123, inbox, timeout=1)
    assert state["restart"] == 1
    assert result["reason"] == "interrupted"


def test_rejects_unexpected_profile_before_restart(tmp_path, monkeypatch):
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    request_id = "pr145-accept-002"
    (inbox / (request_id + ".running")).write_text(json.dumps({
        "requestId": request_id, "project": "codexbridge",
        "branch": "feature/file-instruction-ws-bridge", "profile": "other",
    }))
    monkeypatch.setattr(acceptance, "systemctl", lambda *_a: pytest.fail("restart forbidden"))
    with pytest.raises(acceptance.Refuse, match="unexpected_running_instruction"):
        acceptance.observe(request_id, 123, inbox, timeout=1)


def test_live_markers_visible_and_detached_evidence_path(tmp_path, monkeypatch, capsys):
    import sys
    from scripts import run_file_ws_evidence as evidence
    monkeypatch.setattr(evidence, "_git", lambda *args: "" if "branch" in args else "a" * 40)
    code = (
        "import time; print('ARMED=pr145-visible',flush=True); "
        "print('PRIVATE=do-not-display',flush=True); time.sleep(0.02)"
    )
    rc, report, folder = evidence.run_evidenced(
        [sys.executable, "-u", "-c", code], feature="pr145-live-interruption",
        timeout=5, state_root=tmp_path, publisher=None, live_markers=True,
    )
    assert rc == 0
    shown = capsys.readouterr().out
    assert "ARMED=pr145-visible" in shown
    assert "PRIVATE=do-not-display" not in shown
    assert "PRIVATE=do-not-display" in (folder / "execution.log").read_text()
    assert "detached" in json.loads((folder / "manifest.json").read_text()).get("branch", "") or report["branch"] == ""
    publication = json.loads((folder / "publication.json").read_text())
    assert "/detached/" in publication["relative_path"]
