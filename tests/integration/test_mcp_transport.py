"""Deterministic Streamable HTTP lifecycle checks for the MCP endpoint."""

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
