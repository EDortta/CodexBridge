"""`AgentService._handle_materialize` -- the `ISSUE_MATERIALIZE` handler on

the executor. issue #78, Commit 2c. Mirrors `tests/unit/test_agent_service.py`'s
own posture for `_handle_dispatch`: a `DummyWebSocket` collecting sent
envelopes, no real network.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from agent.codex_bridge_agent.config import AgentSettings
from agent.codex_bridge_agent.service import AgentService
from shared.protocol import AgentEnvelope, AgentMessageType, ProjectRegistration


class DummyWebSocket:
    def __init__(self) -> None:
        self.messages: list[str] = []

    async def send(self, payload: str) -> None:
        self.messages.append(payload)


def _envelope(payload: dict) -> AgentEnvelope:
    return AgentEnvelope(
        message_id="materialize-1", executor_id="devel3", sent_at=datetime.now(timezone.utc),
        type=AgentMessageType.ISSUE_MATERIALIZE, payload=payload,
    )


def _payload(**overrides) -> dict:
    fields = dict(
        epic_id="epic-1",
        project_id="codexbridge",
        slug="bridge-epic-[ready]",
        files={
            "README.md": "readme body",
            "epic.md": "epic body",
            "issues/issue-a/first-slice-[ready].md": "issue a body",
        },
        existing_path=None,
        epic_revision=3,
        issue_revisions={"issue-a": 1},
        delivery=None,
    )
    fields.update(overrides)
    return fields


@pytest.mark.asyncio
async def test_materialize_writes_files_and_reports_success(tmp_path: Path) -> None:
    """Positive control for the three failure-mode tests below."""
    service = AgentService(AgentSettings())
    service.projects = {"codexbridge": ProjectRegistration(project_id="codexbridge", name="CB", path=str(tmp_path))}
    websocket = DummyWebSocket()

    await service._handle_materialize(websocket, _envelope(_payload()))

    result = AgentEnvelope.model_validate_json(websocket.messages[-1])
    assert result.type == AgentMessageType.ISSUE_MATERIALIZE_RESULT
    assert result.payload["ok"] is True
    assert result.payload["epic_id"] == "epic-1"
    assert result.payload["epic_path"] == "docs/issues/001-bridge-epic-[ready]"
    # Echoed back verbatim from the request -- opaque to the executor.
    assert result.payload["epic_revision"] == 3
    assert result.payload["issue_revisions"] == {"issue-a": 1}

    written = tmp_path / result.payload["epic_path"]
    assert (written / "README.md").read_text() == "readme body"
    assert (written / "epic.md").read_text() == "epic body"
    issue_key = "issues/issue-a/first-slice-[ready].md"
    written_issue_path = tmp_path / result.payload["written_paths"][issue_key]
    assert written_issue_path.read_text() == "issue a body"


@pytest.mark.asyncio
async def test_materialize_for_an_unknown_project_reports_a_typed_error(tmp_path: Path) -> None:
    service = AgentService(AgentSettings())
    assert service.settings.auto_project_root is None
    websocket = DummyWebSocket()

    await service._handle_materialize(websocket, _envelope(_payload(project_id="not-registered")))

    result = AgentEnvelope.model_validate_json(websocket.messages[-1])
    assert result.payload["ok"] is False
    assert result.payload["error"] == "unknown_project"
    assert result.payload["epic_id"] == "epic-1"


@pytest.mark.asyncio
async def test_materialize_with_a_malformed_payload_reports_a_typed_error(tmp_path: Path) -> None:
    service = AgentService(AgentSettings())
    service.projects = {"codexbridge": ProjectRegistration(project_id="codexbridge", name="CB", path=str(tmp_path))}
    websocket = DummyWebSocket()

    # Missing required fields (`files`, `epic_revision`, ...) -- pydantic
    # validation must fail closed with a typed result, not raise out of the
    # message loop.
    await service._handle_materialize(websocket, _envelope({"epic_id": "epic-1"}))

    result = AgentEnvelope.model_validate_json(websocket.messages[-1])
    assert result.payload["ok"] is False
    assert result.payload["error"] == "invalid_materialize_request"


@pytest.mark.asyncio
async def test_materialize_republish_with_a_missing_existing_path_reports_a_typed_error(tmp_path: Path) -> None:
    service = AgentService(AgentSettings())
    service.projects = {"codexbridge": ProjectRegistration(project_id="codexbridge", name="CB", path=str(tmp_path))}
    websocket = DummyWebSocket()

    await service._handle_materialize(
        websocket, _envelope(_payload(existing_path="docs/issues/999-does-not-exist"))
    )

    result = AgentEnvelope.model_validate_json(websocket.messages[-1])
    assert result.payload["ok"] is False
    assert result.payload["error"] == "existing_path_not_found"
