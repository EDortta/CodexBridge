"""Read-only manifest query regression tests: no secrets, paths or execution."""
import asyncio
import json
from pathlib import Path
from uuid import uuid4

import pytest

from agent.codex_bridge_agent.evidence_reader import list_evidence
from agent.codex_bridge_agent.config import AgentSettings
from agent.codex_bridge_agent.service import AgentService
from shared.protocol import AgentEnvelope, AgentMessageType, ProjectRegistration
from gateway.app.services.agent_hub import AgentHub


def sample_run(tmp_path: Path, *, feature="file-instruction-ws-bridge"):
    run = tmp_path / "codexbridge" / feature / "20261118T170000Z-1234abcd"
    run.mkdir(parents=True)
    (run / "manifest.json").write_text(json.dumps({
        "schema": 1, "project": "CodexBridge", "feature": feature,
        "branch": "feature/file-instruction-ws-bridge", "commit": "a" * 40,
        "status": "failed", "exit_code": 7,
        "checks": {"failed_test_ids": ["tests/unit/test_error.py::test_bad"],
                   "counts": {"failed": 1}, "local_log_sha256": "b" * 64},
        "secret_token": "SECRET_SHOULD_NEVER_LEAK",
    }))
    (run / "publication.json").write_text(json.dumps({
        "status": "published",
        "relative_path": "CodexBridge/file-instruction-ws-bridge/feature-file-instruction-ws-bridge/2026-11-18/17000000/manifest.json",
    }))
    (run / "execution.log").write_text("PRIVATE_OUTPUT_SHOULD_NEVER_LEAK")
    return run


def test_reader_returns_sanitized_failed_manifest(tmp_path):
    sample_run(tmp_path)
    result = list_evidence(state_root=tmp_path, project_id="codexbridge",
                           feature="file-instruction-ws-bridge", limit=5)
    assert result["status"] == "ok"
    item = result["items"][0]
    assert item["status"] == "failed"
    assert item["checks"]["failed_test_ids"] == ["tests/unit/test_error.py::test_bad"]
    assert item["publication_status"] == "published"
    assert item["verified_remote"] is False
    assert item["publication_url"].startswith("https://github.com/EDortta/development-evidences/")
    assert "SECRET_SHOULD_NEVER_LEAK" not in json.dumps(result)
    assert "PRIVATE_OUTPUT_SHOULD_NEVER_LEAK" not in json.dumps(result)
    assert str(tmp_path) not in json.dumps(result)


def test_reader_denies_unlisted_project_and_path_injection(tmp_path):
    sample_run(tmp_path)
    assert list_evidence(state_root=tmp_path, project_id="other",
                         feature="file-instruction-ws-bridge")["status"] == "denied"
    assert list_evidence(state_root=tmp_path, project_id="codexbridge",
                         feature="../secrets")["status"] == "denied"


@pytest.mark.asyncio
async def test_agent_evidence_query_roundtrip_without_execution(tmp_path):
    sample_run(tmp_path)
    settings = AgentSettings(evidence_state_root=str(tmp_path))
    service = AgentService(settings)
    service.projects = {"codexbridge": ProjectRegistration(
        project_id="codexbridge", name="CodexBridge", path=str(tmp_path)
    )}

    class Socket:
        def __init__(self):
            self.messages = []
        async def send(self, data):
            self.messages.append(AgentEnvelope.model_validate_json(data))

    socket = Socket()
    request_id = str(uuid4())
    query = AgentEnvelope(
        message_id="query-1", executor_id="devel3",
        sent_at=__import__("datetime").datetime.now(__import__("datetime").timezone.utc),
        type=AgentMessageType.EVIDENCE_QUERY,
        payload={"request_id": request_id, "project_id": "codexbridge",
                 "feature": "file-instruction-ws-bridge", "limit": 3},
    )
    await service._handle_evidence_query(socket, query)
    assert socket.messages[0].type == AgentMessageType.EVIDENCE_RESULT
    assert socket.messages[0].payload["request_id"] == request_id
    assert socket.messages[0].payload["data"]["items"][0]["exit_code"] == 7


@pytest.mark.asyncio
async def test_hub_rejects_wrong_executor_and_unknown_correlation():
    hub = AgentHub(session_factory=None)
    future = asyncio.get_running_loop().create_future()
    hub._evidence_waiters["request-1"] = ("devel3", future)
    assert not hub.accept_evidence_result("other", {
        "request_id": "request-1", "data": {"status": "ok", "items": []}
    })
    assert not future.done()
    assert hub.accept_evidence_result("devel3", {
        "request_id": "request-1", "data": {"status": "ok", "items": []}
    })
    assert (await future)["status"] == "ok"
    assert not hub.accept_evidence_result("devel3", {
        "request_id": "request-1", "data": {"status": "forged", "items": []}
    })
