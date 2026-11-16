"""Deterministic Streamable HTTP lifecycle checks for the MCP endpoint."""

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from gateway.app.core.users import AuthenticatedPrincipal


def _principal() -> AuthenticatedPrincipal:
    return AuthenticatedPrincipal(
        user_id="evidence",
        email="evidence@example.test",
        roles=["admin"],
        scopes=["codexbridge.read"],
        allowed_projects=[],
        can_approve_sensitive=True,
    )


def test_mcp_lifecycle_accepts_notifications_and_read_tool(monkeypatch) -> None:
    import gateway.app.main as main_module

    async def authenticate(*_args, **_kwargs):
        return _principal()

    monkeypatch.setattr(main_module, "authenticate_mcp_request", authenticate)
    with TestClient(main_module.app, raise_server_exceptions=False) as client:
        headers = {
            "Accept": "application/json, text/event-stream",
            "Content-Type": "application/json",
            "Authorization": "Bearer test-token",
        }
        initialized = client.post(
            "/mcp",
            headers=headers,
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2025-06-18",
                    "capabilities": {},
                    "clientInfo": {"name": "test", "version": "1"},
                },
            },
        )
        assert initialized.status_code == 200
        assert initialized.json()["result"]["protocolVersion"] == "2025-06-18"

        notification = client.post(
            "/mcp",
            headers=headers,
            json={"jsonrpc": "2.0", "method": "notifications/initialized"},
        )
        assert notification.status_code == 202
        assert notification.content == b""

        listed = client.post(
            "/mcp",
            headers={**headers, "MCP-Protocol-Version": "2025-06-18"},
            json={"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
        )
        assert listed.status_code == 200
        tools = listed.json()["result"]["tools"]
        assert tools
        assert {"name", "inputSchema"} <= tools[0].keys()

        called = client.post(
            "/mcp",
            headers={**headers, "MCP-Protocol-Version": "2025-06-18"},
            json={
                "jsonrpc": "2.0",
                "id": 3,
                "method": "tools/call",
                "params": {"name": "list_executors", "arguments": {}},
            },
        )
        assert called.status_code == 200
        assert isinstance(called.json()["result"]["structuredContent"]["executors"], list)


def test_mcp_invalid_json_is_jsonrpc_parse_error() -> None:
    import gateway.app.main as main_module

    with TestClient(main_module.app, raise_server_exceptions=False) as client:
        response = client.post(
            "/mcp",
            content=b"",
            headers={"Content-Type": "application/json"},
        )

    assert response.status_code == 400
    assert response.json() == {
        "jsonrpc": "2.0",
        "id": None,
        "error": {"code": -32700, "message": "Parse error"},
    }


def test_mcp_non_object_json_is_jsonrpc_invalid_request() -> None:
    import gateway.app.main as main_module

    with TestClient(main_module.app, raise_server_exceptions=False) as client:
        response = client.post("/mcp", json=[])

    assert response.status_code == 400
    assert response.json() == {
        "jsonrpc": "2.0",
        "id": None,
        "error": {"code": -32600, "message": "Invalid Request"},
    }


@pytest.mark.parametrize(
    "detail",
    [
        "workspace_binding_required:codexbridge:devel3",
        "workspace_binding_inactive:codexbridge:devel3:stale",
        "project_authorization_revoked:codexbridge:devel3",
        "capability_not_authorized_for_mode:codexbridge:devel3:implement",
    ],
)
def test_mcp_authorization_refusals_are_structured_jsonrpc_errors(monkeypatch, detail: str) -> None:
    """A deterministic policy refusal is not an HTTP 500 or a bare detail."""
    import gateway.app.main as main_module

    async def authenticate(*_args, **_kwargs):
        return _principal()

    async def refuse(*_args, **_kwargs):
        raise ValueError(detail)

    monkeypatch.setattr(main_module, "authenticate_mcp_request", authenticate)
    monkeypatch.setattr(main_module, "handle_mcp_call", refuse)
    with TestClient(main_module.app, raise_server_exceptions=False) as client:
        response = client.post(
            "/mcp",
            headers={"Content-Type": "application/json", "Authorization": "Bearer test-token"},
            json={
                "jsonrpc": "2.0",
                "id": "policy-check",
                "method": "tools/call",
                "params": {"name": "start_development_task", "arguments": {}},
            },
        )

    assert response.status_code == 200
    body = response.json()
    assert body["jsonrpc"] == "2.0"
    assert body["id"] == "policy-check"
    assert body["error"]["code"] == -32000
    assert body["error"]["data"]["code"] == detail.split(":", 1)[0]
    assert body["error"]["data"]["detail"] == detail


def test_mcp_configuration_http_exception_is_structured_without_http_500(monkeypatch) -> None:
    import gateway.app.main as main_module

    async def authenticate(*_args, **_kwargs):
        return _principal()

    async def refuse(*_args, **_kwargs):
        raise HTTPException(status_code=409, detail="project_not_onboarded_on_node:codexbridge:devel3")

    monkeypatch.setattr(main_module, "authenticate_mcp_request", authenticate)
    monkeypatch.setattr(main_module, "handle_mcp_call", refuse)
    with TestClient(main_module.app, raise_server_exceptions=False) as client:
        response = client.post(
            "/mcp",
            headers={"Content-Type": "application/json", "Authorization": "Bearer test-token"},
            json={"jsonrpc": "2.0", "id": 4, "method": "tools/call", "params": {}},
        )

    assert response.status_code == 200
    assert response.json()["error"]["data"] == {
        "code": "project_not_onboarded_on_node",
        "detail": "project_not_onboarded_on_node:codexbridge:devel3",
        "context": "codexbridge:devel3",
        "http_status": 409,
    }
