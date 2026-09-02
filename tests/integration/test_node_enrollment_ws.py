"""Enrolled/revoked nodes at the `/agent/ws` handshake — issue #76 (minimal
cut). The WebSocket-facing half of the store-level tests in
`tests/unit/test_node_enrollment.py`.

`agent_ws` is awaited directly with a fake socket, on the test's own loop,
rather than through `TestClient.websocket_connect` — the same reason
`tests/integration/test_agent_ws_identity.py` does: that helper runs the app
on a second thread and event loop, and sharing one in-memory aiosqlite engine
between the two deadlocks. See that file's own docstring for the fuller
account, and `docs/napkin-lessons.md`'s 2026-09-01 entry for why a negative
test here needs `assert socket.accepted` (or an explicit close-code check)
sitting next to it: without one, a negative assertion is also true when the
handshake never ran at all.
"""

from __future__ import annotations

from typing import AsyncIterator

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from starlette.websockets import WebSocketDisconnect

from gateway.app.db.base import Base
from gateway.app.services import store


class FakeSocket:
    """Just enough `WebSocket` for `agent_ws`: it accepts, sends, and runs dry.

    Mirrors `tests/integration/test_agent_ws_identity.py::FakeSocket`
    exactly; not shared via a fixture module because neither file needs a
    second one, and this repo's existing pattern is one small local copy per
    test module rather than a shared helper for a class this short.

    With no incoming messages queued, `receive_json` raises immediately —
    fine for a test that only needs the handshake outcome (accepted? which
    close code?), but useless for testing `AgentHub.force_close` against a
    genuinely *live* registration: by the time `agent_ws` returns, its
    receive loop has already ended and already unregistered the connection.
    `test_revoke_closes_the_live_socket` below gets a *registered* connection
    a different way — through `AgentHub.register` directly — rather than
    keeping an `agent_ws` call alive concurrently to get one; see that test's
    own docstring for why.
    """

    def __init__(self, incoming: list[dict] | None = None) -> None:
        self._incoming = list(incoming or [])
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
    # Same trap `test_agent_ws_identity.py` documents: `AgentHub` is built at
    # import time holding the PRODUCTION session factory, so patching
    # `main.SessionLocal` alone leaves `hub.register`/`hub.force_close`
    # talking to `./codex_bridge.db`.
    monkeypatch.setattr(main.hub, "session_factory", factory)

    yield factory
    await engine.dispose()


async def _enroll(factory: async_sessionmaker, *, token: str, display_name: str, machine_token: str):
    async with factory() as session:
        await store.create_node_invite(
            session, token=token, created_by="esteban", display_name_hint=display_name, ttl_seconds=900
        )
    async with factory() as session:
        result = await store.enroll_node(
            session, invite_token=token, display_name=display_name, machine_token=machine_token
        )
    assert result is not None, "setup: the invite must redeem cleanly for this test to mean anything"
    node, executor = result
    return node, executor


async def test_a_freshly_enrolled_node_connects_with_the_token_enroll_returned(wired) -> None:
    from gateway.app import main
    from shared.protocol import AgentMessageType

    node, executor = await _enroll(wired, token="invite-1", display_name="devel3", machine_token="raw-machine-token")

    socket = FakeSocket()
    await main.agent_ws(socket, executor_id=node.id, x_executor_token="raw-machine-token")

    # Not `hub.is_connected(node.id)` afterward: with no queued messages, the
    # receive loop ends and unregisters itself within this same call, before
    # it ever returns (see `FakeSocket`'s own docstring). What proves the
    # handshake actually succeeded is that it was accepted, never closed, and
    # sent the `hello_ack` `agent_ws` only sends past the token check.
    assert socket.accepted, "the handshake was refused; the test proves nothing"
    assert socket.close_code is None
    assert any(message["type"] == AgentMessageType.HELLO_ACK.value for message in socket.sent)


async def test_a_freshly_enrolled_node_is_refused_with_the_wrong_token(wired) -> None:
    from gateway.app import main

    node, _ = await _enroll(wired, token="invite-2", display_name="devel3", machine_token="raw-machine-token")

    socket = FakeSocket()
    await main.agent_ws(socket, executor_id=node.id, x_executor_token="not-the-real-token")

    assert not socket.accepted
    assert socket.close_code == 4403


async def test_revoke_closes_the_live_socket(wired) -> None:
    """`force_close` against a connection that is genuinely still registered.

    Registers directly through `AgentHub.register` rather than driving a
    second, concurrently-running `agent_ws` coroutine (e.g. via
    `asyncio.create_task`) to get there: this module's whole reason for
    calling `agent_ws` directly instead of through `TestClient.websocket_
    connect` is to avoid two execution contexts touching one in-memory
    aiosqlite engine at once (see the module docstring) — a background task
    sharing the loop with the test body is the same hazard in a different
    shape, and it was flaky under full-suite load for exactly that reason
    before this test settled on the sequential form below. `force_close`
    itself does not care how a connection reached `hub.connections`; this is
    the unit under test, not the handshake that normally produces one (the
    other tests in this file already cover that).
    """
    from gateway.app import main

    node, _ = await _enroll(wired, token="invite-3", display_name="devel3", machine_token="raw-machine-token")
    socket = FakeSocket()
    await main.hub.register(node.id, socket)
    assert main.hub.is_connected(node.id), "setup: the node must actually be connected first"

    async with wired() as session:
        await store.revoke_node(session, node.id)
    closed = await main.hub.force_close(node.id)

    assert closed is True
    assert socket.close_code == 4403
    assert not main.hub.is_connected(node.id)


async def test_force_close_on_a_node_with_no_live_connection_reports_nothing_closed(wired) -> None:
    from gateway.app import main

    node, _ = await _enroll(wired, token="invite-4", display_name="devel3", machine_token="t")
    # Never connected -- `force_close` must not raise, and must say honestly
    # that there was nothing to close.
    closed = await main.hub.force_close(node.id)
    assert closed is False


async def test_a_revoked_node_is_refused_on_its_next_handshake(wired) -> None:
    from gateway.app import main

    node, _ = await _enroll(wired, token="invite-5", display_name="devel3", machine_token="raw-machine-token")
    first = FakeSocket()
    await main.agent_ws(first, executor_id=node.id, x_executor_token="raw-machine-token")
    assert first.accepted, "setup: the node must connect once before it can be shown revoked"

    async with wired() as session:
        await store.revoke_node(session, node.id)
    await main.hub.force_close(node.id)

    reconnect = FakeSocket()
    await main.agent_ws(reconnect, executor_id=node.id, x_executor_token="raw-machine-token")

    assert not reconnect.accepted, "a revoked node's reconnect must never reach websocket.accept()"
    assert reconnect.close_code == 4403
    assert not main.hub.is_connected(node.id)
