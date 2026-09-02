"""The `/agent/ws` handshake stops carrying the token in the URL — issue #15.

Resolution rules are unit-tested in `tests/unit/test_agent_auth.py`. What is
worth an integration test is the wiring: that FastAPI actually binds the header,
that a handshake with no credential is refused before anything touches the
database, and that the deprecated query form, kept accepted for one release, no
longer authenticates anything.
"""

from __future__ import annotations

from typing import AsyncIterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from starlette.websockets import WebSocketDisconnect

from gateway.app.db.base import Base
from shared.protocol import EXECUTOR_TOKEN_HEADER


@pytest.fixture
async def client(monkeypatch) -> AsyncIterator[TestClient]:
    """A real app, but wired to its own isolated in-memory database.

    `gateway.app.main.app` normally gets its schema from the `startup` event
    (`Base.metadata.create_all` against the module-level production `engine`,
    which defaults to the file `./codex_bridge.db`). That event never fires
    here — `TestClient` only runs ASGI lifespan when entered as `with client:`,
    and nothing below does that — so, left alone, every test in this file
    depended on whatever schema happened to already be sitting in that stray
    file from a previous run, order- and CWD-sensitive (issue #28).

    `/agent/ws` also reads its sessions from the module-level `SessionLocal`
    directly rather than through `Depends(get_session)` (see
    `gateway.app.main.agent_ws`), so an `app.dependency_overrides` swap — the
    trick the rest of `tests/integration` uses — would never reach it either.
    Patching `main.SessionLocal` itself, the same seam
    `test_refusing_an_anonymous_handshake_touches_no_executor_record` already
    exploited below, is what actually redirects it.
    """
    from gateway.app import main

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    monkeypatch.setattr(main, "SessionLocal", factory)

    yield TestClient(main.app, raise_server_exceptions=False)
    await engine.dispose()


def test_a_handshake_with_no_credential_is_refused(client: TestClient) -> None:
    with pytest.raises(WebSocketDisconnect) as refused:
        with client.websocket_connect("/agent/ws?executor_id=devel3"):
            pass
    assert refused.value.code == 4401


def test_refusing_an_anonymous_handshake_touches_no_executor_record(
    client: TestClient, monkeypatch
) -> None:
    """4401 must be decided before the database, not after a lookup.

    Ordering it the other way turns an unauthenticated connect into a probe for
    which executor ids exist, distinguishable by 4404 versus 4403.
    """
    from gateway.app import main

    def _explode(*_args: object, **_kwargs: object):
        raise AssertionError("the database was consulted for an anonymous handshake")

    monkeypatch.setattr(main, "SessionLocal", _explode)

    with pytest.raises(WebSocketDisconnect) as refused:
        with client.websocket_connect("/agent/ws?executor_id=devel3"):
            pass
    assert refused.value.code == 4401


def test_the_header_is_bound_and_reaches_the_registry_check(client: TestClient) -> None:
    """An unknown executor authenticating by header gets 4404, not 4401.

    That distinction is the proof the header was read: had FastAPI not bound it,
    resolution would have found no credential and closed 4401 first.
    """
    with pytest.raises(WebSocketDisconnect) as refused:
        with client.websocket_connect(
            "/agent/ws?executor_id=nobody",
            headers={EXECUTOR_TOKEN_HEADER: "whatever"},
        ):
            pass
    assert refused.value.code == 4404


def test_the_query_parameter_no_longer_authenticates(client: TestClient) -> None:
    """The removal #15 deferred by one release.

    A credential presented only in the URL is now no credential at all: 4401,
    decided before the registry is consulted, exactly like an anonymous
    handshake. Any executor still on the old form must be upgraded to send the
    header — the agent has sent it since the same release
    (`agent/codex_bridge_agent/service.py`).
    """
    with pytest.raises(WebSocketDisconnect) as refused:
        with client.websocket_connect("/agent/ws?executor_id=nobody&token=legacy"):
            pass
    assert refused.value.code == 4401


def test_a_query_token_cannot_stand_in_for_a_blank_header(client: TestClient) -> None:
    """No fall-through: an empty header is absent, and the URL is not a backup.

    The old resolver fell back to the query parameter when the header was blank,
    so a proxy injecting an empty header kept the deprecated path alive. It does
    not any more.
    """
    with pytest.raises(WebSocketDisconnect) as refused:
        with client.websocket_connect(
            "/agent/ws?executor_id=nobody&token=legacy",
            headers={EXECUTOR_TOKEN_HEADER: ""},
        ):
            pass
    assert refused.value.code == 4401
