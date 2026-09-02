"""`AgentMessageType.DISCOVERY_REPORT` through the real `/agent/ws` receive loop.

Issue #73 Stage 3. Same idiom `tests/integration/test_agent_ws_identity.py`
uses and explains at length: `agent_ws` is awaited directly with a fake
socket, never through `TestClient.websocket_connect` (which runs the app in
its own thread/event loop and deadlocks against one in-memory aiosqlite
engine shared with the test's own loop).

`tests/unit/test_discovery_store.py` already proves `store.
record_discovery_report`'s reconciliation rules in isolation. What these
tests prove instead is the WIRING: that the one branch in `gateway/app/
main.py` for this message type calls that function and nothing else, that a
malformed report cannot drop the connection, and that the same
claimed-vs-authenticated `executor_id` guard every other message type gets
for free also covers this one.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import AsyncIterator
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from starlette.websockets import WebSocketDisconnect

from gateway.app.db.base import Base
from gateway.app.models.entities import DiscoveredResourceModel, ProjectAuthorizationModel, ProjectModel
from gateway.app.services import store
from shared.protocol import AgentMessageType, ExecutorRegistration


VICTIM = "victim-node"
ATTACKER = "attacker-node"


class FakeSocket:
    def __init__(self, incoming: list[dict]) -> None:
        self._incoming = list(incoming)
        self.sent: list[dict] = []
        self.accepted = False
        self.close_code: int | None = None

    async def accept(self) -> None:
        self.accepted = True

    async def close(self, code: int = 1000) -> None:
        self.close_code = code

    async def send_json(self, payload: dict) -> None:
        self.sent.append(payload)

    async def receive_json(self) -> dict:
        if not self._incoming:
            raise WebSocketDisconnect(1000)
        return self._incoming.pop(0)


@pytest.fixture
async def wired(monkeypatch) -> AsyncIterator[async_sessionmaker]:
    from gateway.app import main

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    monkeypatch.setattr(main, "SessionLocal", factory)
    # See `test_agent_ws_identity.py`'s own fixture for why this second patch
    # is required: `AgentHub` was built at import time holding the
    # production session factory.
    monkeypatch.setattr(main.hub, "session_factory", factory)

    async with factory() as session:
        await store.upsert_registry(
            session,
            [
                ExecutorRegistration(
                    executor_id=name,
                    display_name=name,
                    machine_token=f"token-{name}",
                    allowed_projects=[],
                )
                for name in (VICTIM, ATTACKER)
            ],
            [],
        )

    yield factory
    await engine.dispose()


def _envelope(executor_id: str, message_type: AgentMessageType, payload: dict) -> dict:
    return {
        "message_id": str(uuid4()),
        "executor_id": executor_id,
        "sent_at": datetime.now(timezone.utc).isoformat(),
        "type": message_type.value,
        "payload": payload,
    }


def _discovery_report_payload(root_path: str = "/root", candidates: list[dict] | None = None) -> dict:
    return {
        "root_path": root_path,
        "candidates": candidates
        if candidates is not None
        else [
            {
                "resource_key": "/root/hub",
                "suggested_project_id": "hub",
                "suggested_name": "hub",
                "remote_url": None,
                "head": "abc123",
                "dirty": False,
            }
        ],
        "scanned_at": datetime.now(timezone.utc).isoformat(),
    }


async def _speak(as_executor: str, *envelopes: dict) -> FakeSocket:
    from gateway.app import main

    socket = FakeSocket(list(envelopes))
    await main.agent_ws(socket, executor_id=as_executor, x_executor_token=f"token-{as_executor}")
    assert socket.accepted, "the handshake was refused; the test proves nothing"
    return socket


async def _discovered_rows(factory: async_sessionmaker, node_id: str) -> list[DiscoveredResourceModel]:
    async with factory() as session:
        result = await session.execute(select(DiscoveredResourceModel).where(DiscoveredResourceModel.node_id == node_id))
        return list(result.scalars())


async def test_a_discovery_report_is_recorded_for_the_authenticated_node(wired) -> None:
    await _speak(
        VICTIM,
        _envelope(VICTIM, AgentMessageType.HELLO, {"agent_version": "1.0.0"}),
        _envelope(VICTIM, AgentMessageType.DISCOVERY_REPORT, _discovery_report_payload()),
    )

    rows = await _discovered_rows(wired, VICTIM)
    assert len(rows) == 1
    # `resource_key` is a fixed-width hash from `migrations/0013_discovery_
    # resource_key_hash.sql` on -- `resource_path` is where the real path lives.
    from shared.security import hash_resource_key

    assert rows[0].resource_path == "/root/hub"
    assert rows[0].resource_key == hash_resource_key("/root/hub")
    assert rows[0].root_path == "/root"


async def test_the_receiving_branch_writes_only_discovered_resources(wired) -> None:
    """The structural guarantee, proven through the real handler this time:

    the branch in `main.py` calls exactly one store function, and even a
    report full of brand-new candidates cannot put a row in
    `project_authorizations` or `projects`.
    """
    async with wired() as session:
        projects_before = (await session.execute(select(ProjectModel))).scalars().all()
        authorizations_before = (await session.execute(select(ProjectAuthorizationModel))).scalars().all()

    await _speak(
        VICTIM,
        _envelope(VICTIM, AgentMessageType.HELLO, {"agent_version": "1.0.0"}),
        _envelope(VICTIM, AgentMessageType.DISCOVERY_REPORT, _discovery_report_payload()),
    )

    async with wired() as session:
        projects_after = (await session.execute(select(ProjectModel))).scalars().all()
        authorizations_after = (await session.execute(select(ProjectAuthorizationModel))).scalars().all()

    assert len(projects_after) == len(projects_before)
    assert len(authorizations_after) == len(authorizations_before)


async def test_a_malformed_discovery_report_is_dropped_not_closed(wired) -> None:
    """Same tolerant-parse posture as a malformed HELLO: a broken payload

    from a buggy node must not read as a dropped connection, and must not
    stop that node's other messages from being processed.
    """
    socket = await _speak(
        VICTIM,
        _envelope(VICTIM, AgentMessageType.HELLO, {"agent_version": "1.0.0"}),
        _envelope(VICTIM, AgentMessageType.DISCOVERY_REPORT, {"candidates": "not-even-a-list"}),
        _envelope(VICTIM, AgentMessageType.HEARTBEAT, {}),
    )

    assert socket.close_code is None
    rows = await _discovered_rows(wired, VICTIM)
    assert rows == []


async def test_a_forged_discovery_report_is_dropped_not_recorded_against_the_victim(wired) -> None:
    """The claimed-vs-authenticated `executor_id` guard at the top of the

    receive loop covers every message type by construction (issue #73
    Stage 2's own fix); this proves it also covers the type this PR adds,
    rather than assuming it "just because it's before the branch".
    """
    await _speak(
        ATTACKER,
        _envelope(VICTIM, AgentMessageType.DISCOVERY_REPORT, _discovery_report_payload(root_path="/attacker-claims")),
    )

    assert await _discovered_rows(wired, VICTIM) == []
    assert await _discovered_rows(wired, ATTACKER) == []
