"""Real deterministic dispatch through AgentService and the existing WS envelope."""
import json
import subprocess
import sys
from datetime import datetime, timezone

import pytest

from agent.codex_bridge_agent.config import AgentSettings
from agent.codex_bridge_agent.service import AgentService
from shared.protocol import AgentEnvelope, AgentMessageType, ProjectRegistration


class CapturedWebSocket:
    def __init__(self):
        self.sent = []

    async def send(self, message):
        self.sent.append(AgentEnvelope.model_validate_json(message))


def workspace(tmp_path):
    root = tmp_path / "worktree"
    root.mkdir()
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    subprocess.run(["git", "-C", str(root), "checkout", "-q", "-b", "feature/file"], check=True)
    config = tmp_path / "private-config.json"
    config.write_text(json.dumps({
        "project": "demo", "root": str(root), "branch": "feature/file",
        "profiles": {"verify": {
            "argv": [sys.executable, "-c", "print('WS_FILE_RECEIPT')"],
            "timeout_seconds": 5,
        }},
    }), encoding="utf-8")
    inbox = tmp_path / "inbox"
    inbox.mkdir(mode=0o700)
    settings = AgentSettings(
        file_executor_config_file=str(config), file_executor_inbox=str(inbox),
    )
    service = AgentService(settings)
    service.projects = {"demo": ProjectRegistration(
        project_id="demo", name="demo", path=str(root)
    )}
    return service, inbox


def envelope(*, ident="verify-001", mode="test", project="demo", profile="verify"):
    instruction = json.dumps({
        "schemaVersion": 1, "requestId": ident, "project": project,
        "branch": "feature/file", "profile": profile,
    })
    return AgentEnvelope(
        message_id="wire-msg-1", executor_id="devel3",
        sent_at=datetime.now(timezone.utc), type=AgentMessageType.TASK_DISPATCH,
        payload={
            "task_id": "task-" + ident, "project_id": project,
            "engine": "file", "mode": mode,
            "instruction": instruction, "timeout_seconds": 30,
        }
    )


@pytest.mark.asyncio
async def test_ws_dispatch_executes_and_replays_without_second_run(tmp_path):
    service, inbox = workspace(tmp_path)
    ws = CapturedWebSocket()
    message = envelope()
    await service._handle_dispatch(ws, message)
    assert [x.type for x in ws.sent] == [
        AgentMessageType.TASK_ACK, AgentMessageType.TASK_RESULT
    ]
    assert ws.sent[-1].payload["final_state"] == "completed"
    assert (inbox / "verify-001[DONE].json").is_file()
    receipt = json.loads((inbox / "results/verify-001.json").read_text())
    assert receipt["status"] == "success"
    assert "WS_FILE_RECEIPT" in receipt["output"]
    old = (inbox / "results/verify-001.json").read_bytes()
    await service._handle_dispatch(ws, message)
    assert ws.sent[-1].payload["final_state"] == "completed"
    assert (inbox / "results/verify-001.json").read_bytes() == old


@pytest.mark.asyncio
async def test_ws_file_mode_denies_modify_and_unknown_profile(tmp_path):
    service, inbox = workspace(tmp_path)
    ws = CapturedWebSocket()
    await service._handle_dispatch(ws, envelope(mode="implement"))
    assert ws.sent[-1].payload["final_state"] == "failed"
    assert not list(inbox.glob("*.json"))
    await service._handle_dispatch(ws, envelope(profile="arbitrary"))
    assert ws.sent[-1].payload["final_state"] == "failed"
    assert not list(inbox.glob("*.json"))


@pytest.mark.asyncio
async def test_ws_file_mode_denies_unconfigured_agent(tmp_path):
    service, inbox = workspace(tmp_path)
    service.settings.file_executor_config_file = None
    ws = CapturedWebSocket()
    await service._handle_dispatch(ws, envelope())
    assert ws.sent[-1].payload["final_state"] == "failed"
    assert not list(inbox.glob("*.json"))
