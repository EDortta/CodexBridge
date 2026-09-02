"""An envelope's `executor_id` is a claim; the handshake's is the fact.

`AgentEnvelope.executor_id` is a field the CLIENT writes into the message body.
The `executor_id` on `/agent/ws` is the one that presented a machine token.
Believing the first let any connected node write another node's row — forge the
capabilities it reports, or refresh its liveness so a dead node reads healthy —
which is exactly the fleet surface issue #73 Stage 2 exists to make
trustworthy. Issue #16 had already fixed this for `task.ack` alone; every
message type added afterwards inherited the same trust.

These tests drive real envelopes through the real receive loop, because that is
where the gap lived: `store.record_node_announcement` called directly is
well-behaved, and the suite passed over the hole.

`agent_ws` is awaited directly with a fake socket rather than through
`TestClient.websocket_connect`. The `TestClient` runs the app in its own
thread and event loop; sharing one in-memory aiosqlite engine across the two
deadlocks, and polling for the effect from the test's loop makes a negative
assertion that would also hold if nothing had been processed at all. Awaiting
the handler means the loop has provably finished before anything is asserted.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import AsyncIterator
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from starlette.websockets import WebSocketDisconnect

from gateway.app.db.base import Base
from gateway.app.services import store
from shared.protocol import AgentMessageType, ExecutorRegistration


VICTIM = "victim-node"
ATTACKER = "attacker-node"

FORGED = {
    "agent_version": "FORGED",
    "os": "FORGED-OS",
    "capabilities": ["modify", "deliver"],
    "max_concurrent_tasks": 999,
}


class FakeSocket:
    """Just enough `WebSocket` for `agent_ws`: it accepts, sends, and runs dry.

    `receive_json` raising `WebSocketDisconnect` once the queue empties is what
    ends the handler's `while True`, the same way a real client hanging up
    does.
    """

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
    # `AgentHub` was built at import time holding the PRODUCTION factory, so
    # patching `main.SessionLocal` alone leaves `hub.register` talking to
    # `./codex_bridge.db`: the handshake then dies with `unknown_executor`
    # before the receive loop starts, and every assertion below would pass
    # because nothing ran.
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


async def _speak(as_executor: str, *envelopes: dict) -> FakeSocket:
    """Authenticate as `as_executor` and let it say `envelopes`, in order."""
    from gateway.app import main

    socket = FakeSocket(list(envelopes))
    await main.agent_ws(socket, executor_id=as_executor, x_executor_token=f"token-{as_executor}")
    assert socket.accepted, "the handshake was refused; the test proves nothing"
    return socket


async def _node(factory: async_sessionmaker, node_id: str):
    async with factory() as session:
        row = await store.get_node(session, node_id)
    assert row is not None
    return row[0]


async def _last_seen(factory: async_sessionmaker, executor_id: str):
    async with factory() as session:
        executor = await session.get(store.ExecutorModel, executor_id)
        seen = executor.last_seen_at
    if seen is not None and seen.tzinfo is None:
        seen = seen.replace(tzinfo=timezone.utc)
    return seen


async def test_a_node_announcing_itself_is_recorded(wired) -> None:
    """The honest path, so every refusal below is not passing for want of wiring."""
    await _speak(ATTACKER, _envelope(ATTACKER, AgentMessageType.HELLO, {"agent_version": "1.2.3", "os": "Linux"}))

    node = await _node(wired, ATTACKER)
    assert node.agent_version == "1.2.3"
    assert node.os == "Linux"
    assert node.capabilities_observed_at is not None


async def test_a_node_cannot_announce_on_another_nodes_behalf(wired) -> None:
    """The exploit: authenticate as one node, claim to be another.

    Before the guard this overwrote the victim's `os`, `agent_version` and
    reported capabilities — a node the connection held no token for and that
    had never sent anything.
    """
    await _speak(ATTACKER, _envelope(VICTIM, AgentMessageType.HELLO, FORGED))

    victim = await _node(wired, VICTIM)
    assert victim.agent_version is None
    assert victim.os is None
    assert victim.capabilities_observed_at is None
    assert json.loads(victim.capabilities_json or "{}").get("capabilities") in (None, [])


async def test_the_forged_envelope_is_dropped_not_redirected(wired) -> None:
    """Rewriting the claimed id to the authenticated one would be worse.

    It would silently accept, as the sender's own, a message the sender never
    made about itself. The envelope is refused outright.
    """
    await _speak(ATTACKER, _envelope(VICTIM, AgentMessageType.HELLO, FORGED))

    attacker = await _node(wired, ATTACKER)
    assert attacker.agent_version is None
    assert attacker.os is None


async def test_a_forged_heartbeat_does_not_refresh_another_nodes_liveness(wired) -> None:
    """Liveness feeds `node_health`, so forging it forges the fleet's health.

    Same root cause one branch over — which is why the guard sits before the
    dispatch instead of inside either branch.
    """
    stale = datetime.now(timezone.utc) - timedelta(hours=6)
    async with wired() as session:
        victim = await session.get(store.ExecutorModel, VICTIM)
        victim.connected = True
        victim.last_seen_at = stale
        await session.commit()

    await _speak(ATTACKER, _envelope(VICTIM, AgentMessageType.HEARTBEAT, {}))

    assert await _last_seen(wired, VICTIM) < datetime.now(timezone.utc) - timedelta(hours=5)


async def test_the_connection_survives_a_forged_envelope(wired) -> None:
    """Dropping the message must not drop the socket.

    Hanging up here would turn a buggy agent into an outage, and would hand an
    attacker a way to disconnect a node by making it send one bad envelope.
    """
    await _speak(
        ATTACKER,
        _envelope(VICTIM, AgentMessageType.HELLO, FORGED),
        _envelope(ATTACKER, AgentMessageType.HELLO, {"agent_version": "after-the-forgery"}),
    )

    assert (await _node(wired, ATTACKER)).agent_version == "after-the-forgery"
