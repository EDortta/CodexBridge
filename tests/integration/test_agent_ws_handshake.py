"""The `/agent/ws` handshake stops carrying the token in the URL — issue #15.

Resolution rules are unit-tested in `tests/unit/test_agent_auth.py`. What is
worth an integration test is the wiring: that FastAPI actually binds the header,
that a handshake with no credential is refused before anything touches the
database, and that the surviving query path announces itself without printing
the credential it was called with.
"""

from __future__ import annotations

import logging

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from shared.protocol import EXECUTOR_TOKEN_HEADER


@pytest.fixture
def client() -> TestClient:
    from gateway.app.main import app

    return TestClient(app, raise_server_exceptions=False)


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


def test_the_query_parameter_still_works_and_warns(client: TestClient, caplog) -> None:
    with caplog.at_level(logging.WARNING, logger="gateway.app.main"):
        with pytest.raises(WebSocketDisconnect):
            with client.websocket_connect("/agent/ws?executor_id=nobody&token=legacy"):
                pass

    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert any("deprecated token query parameter" in r.getMessage() for r in warnings)


def test_the_deprecation_warning_does_not_print_the_token(client: TestClient, caplog) -> None:
    """A warning about a leaked credential must not leak it again.

    This is the whole point of #15: the value stops appearing in anything the
    gateway writes.
    """
    with caplog.at_level(logging.WARNING, logger="gateway.app.main"):
        with pytest.raises(WebSocketDisconnect):
            with client.websocket_connect("/agent/ws?executor_id=nobody&token=s3cr3t-value"):
                pass

    for record in caplog.records:
        assert "s3cr3t-value" not in record.getMessage()
        assert "s3cr3t-value" not in str(record.args)


def test_the_header_path_logs_no_deprecation_warning(client: TestClient, caplog) -> None:
    with caplog.at_level(logging.WARNING, logger="gateway.app.main"):
        with pytest.raises(WebSocketDisconnect):
            with client.websocket_connect(
                "/agent/ws?executor_id=nobody",
                headers={EXECUTOR_TOKEN_HEADER: "whatever"},
            ):
                pass

    assert not any("deprecated" in r.getMessage() for r in caplog.records)
