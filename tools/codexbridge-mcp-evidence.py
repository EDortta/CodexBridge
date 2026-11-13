#!/usr/bin/env python3
"""Run a sanitized, authenticated end-to-end MCP evidence probe."""

from __future__ import annotations

import argparse
import base64
import hashlib
import html
import json
import secrets
import sys
import urllib.error
import urllib.parse
import urllib.request
from http.cookiejar import CookieJar
from pathlib import Path


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def read_ini(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        if not raw.strip() or raw.lstrip().startswith(("#", ";")) or "=" not in raw:
            continue
        key, value = raw.split("=", 1)
        values[key.strip()] = value
    required = {"CODEXBRIDGE_USER", "CODEXBRIDGE_EMAIL", "CODEXBRIDGE_PASSWORD"}
    missing = sorted(required - values.keys())
    if missing:
        raise ValueError("missing credential fields: " + ", ".join(missing))
    return values


def request(
    opener: urllib.request.OpenerDirector,
    url: str,
    *,
    method: str = "GET",
    body: bytes | None = None,
    headers: dict[str, str] | None = None,
) -> tuple[int, dict[str, str], bytes]:
    req = urllib.request.Request(url, data=body, method=method, headers=headers or {})
    try:
        with opener.open(req, timeout=30) as response:
            return response.status, dict(response.headers.items()), response.read()
    except urllib.error.HTTPError as exc:
        return exc.code, dict(exc.headers.items()), exc.read()


def json_body(body: bytes) -> dict:
    try:
        parsed = json.loads(body)
    except (UnicodeDecodeError, json.JSONDecodeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def header(headers: dict[str, str], name: str) -> str | None:
    wanted = name.lower()
    return next((value for key, value in headers.items() if key.lower() == wanted), None)


def write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--endpoint", required=True)
    parser.add_argument("--credentials", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()

    args.output.mkdir(parents=True, exist_ok=True)
    credentials = read_ini(args.credentials)
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(CookieJar()), NoRedirect())
    endpoint = args.endpoint.rstrip("/") + "/mcp"
    result: dict[str, str] = {
        "MCP_ENDPOINT": endpoint,
        "OAUTH_STATUS": "",
        "INITIALIZE_STATUS": "",
        "NOTIFICATIONS_INITIALIZED_STATUS": "",
        "TOOLS_LIST_STATUS": "",
        "TOOLS_COUNT": "0",
        "TOOLS_NAMES": "",
        "READ_TOOL_RESULT": "",
        "GATEWAY_REQUEST_IDS": "",
        "ERRORS": "",
    }
    errors: list[str] = []
    request_ids: list[str] = []

    def record_request_id(headers: dict[str, str]) -> None:
        value = header(headers, "X-Request-Id")
        if value and value not in request_ids:
            request_ids.append(value)

    def mcp_call(name: str, payload: dict, request_id: str, token: str) -> tuple[int, dict[str, str], dict]:
        body = json.dumps(payload, separators=(",", ":")).encode()
        status, headers, raw = request(
            opener,
            endpoint,
            method="POST",
            body=body,
            headers={
                "Accept": "application/json, text/event-stream",
                "Content-Type": "application/json",
                "Authorization": f"Bearer {token}",
                "X-Request-Id": request_id,
            },
        )
        record_request_id(headers)
        write_json(args.output / f"{name}.json", json_body(raw))
        return status, headers, json_body(raw)

    metadata_statuses: list[str] = []
    for name, path in (
        ("oauth_authorization_server", "/.well-known/oauth-authorization-server"),
        ("oauth_protected_resource", "/.well-known/oauth-protected-resource/mcp"),
    ):
        status, headers, raw = request(opener, args.endpoint.rstrip("/") + path)
        metadata_statuses.append(f"{path}={status}")
        parsed = json_body(raw)
        write_json(args.output / f"{name}.json", parsed if parsed else {"http_status": status})
        if status != 200:
            errors.append(f"{path} returned HTTP {status}")
    result["OAUTH_STATUS"] = ";".join(metadata_statuses)

    verifier = base64.urlsafe_b64encode(secrets.token_bytes(32)).decode().rstrip("=")
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
    query = urllib.parse.urlencode(
        {
            "response_type": "code",
            "client_id": "chatgpt-codexbridge",
            "redirect_uri": "https://chatgpt.com/codexbridge-evidence",
            "scope": "codexbridge.read",
            "state": "mcp-evidence",
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            "resource": endpoint,
        }
    )
    authorize_url = args.endpoint.rstrip("/") + "/oauth/authorize?" + query
    authorize_get_status, _, _ = request(opener, authorize_url)
    authorize_form = urllib.parse.urlencode(
        {
            "response_type": "code",
            "client_id": "chatgpt-codexbridge",
            "redirect_uri": "https://chatgpt.com/codexbridge-evidence",
            "scope": "codexbridge.read",
            "state": "mcp-evidence",
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            "username": credentials["CODEXBRIDGE_USER"],
            "password": credentials["CODEXBRIDGE_PASSWORD"],
        }
    ).encode()
    authorize_status, authorize_headers, authorize_body = request(
        opener,
        args.endpoint.rstrip("/") + "/oauth/authorize",
        method="POST",
        body=authorize_form,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    location = header(authorize_headers, "Location") or ""
    code = urllib.parse.parse_qs(urllib.parse.urlparse(location).query).get("code", [None])[0]
    if authorize_get_status != 200:
        errors.append(f"OAuth authorize form returned HTTP {authorize_get_status}")
    if authorize_status != 302 or not code:
        errors.append(f"OAuth authorization failed with HTTP {authorize_status}")
    token = ""
    token_status = "not_attempted"
    if code:
        token_form = urllib.parse.urlencode(
            {
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": "https://chatgpt.com/codexbridge-evidence",
                "client_id": "chatgpt-codexbridge",
                "code_verifier": verifier,
            }
        ).encode()
        token_status, _, token_raw = request(
            opener,
            args.endpoint.rstrip("/") + "/oauth/token",
            method="POST",
            body=token_form,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        token_body = json_body(token_raw)
        token = str(token_body.get("access_token", ""))
        if token_status != 200 or not token:
            errors.append(f"OAuth token exchange returned HTTP {token_status}")
    result["OAUTH_STATUS"] += f";authorize={authorize_status};token={token_status}"

    if token:
        init_status, init_headers, init_body = mcp_call(
            "mcp_initialize",
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2025-06-18",
                    "capabilities": {},
                    "clientInfo": {"name": "codexbridge-evidence", "version": "1"},
                },
            },
            "mcp-evidence-initialize",
            token,
        )
        session_id = header(init_headers, "MCP-Session-Id")
        result["INITIALIZE_STATUS"] = f"HTTP {init_status};jsonrpc_result={bool(init_body.get('result'))};session_id={'present' if session_id else 'absent'}"
        if init_status != 200 or not init_body.get("result"):
            errors.append(f"MCP initialize returned HTTP {init_status} without result")

        notification_headers = {"Content-Type": "application/json"}
        if session_id:
            notification_headers["MCP-Session-Id"] = session_id
        notification_status, notification_response_headers, notification_body = request(
            opener,
            endpoint,
            method="POST",
            body=json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}).encode(),
            headers={
                **notification_headers,
                "Accept": "application/json, text/event-stream",
                "Authorization": f"Bearer {token}",
                "X-Request-Id": "mcp-evidence-initialized",
            },
        )
        record_request_id(notification_response_headers)
        write_json(args.output / "mcp_initialized.json", json_body(notification_body))
        result["NOTIFICATIONS_INITIALIZED_STATUS"] = f"HTTP {notification_status}"
        if notification_status >= 400:
            errors.append(f"notifications/initialized returned HTTP {notification_status}")

        list_status, _, list_body = mcp_call(
            "mcp_tools_list",
            {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
            "mcp-evidence-tools-list",
            token,
        )
        tools = list_body.get("result", {}).get("tools", [])
        names = [item.get("name") for item in tools if isinstance(item, dict) and item.get("name")]
        result["TOOLS_LIST_STATUS"] = f"HTTP {list_status};jsonrpc_result={bool(list_body.get('result'))}"
        result["TOOLS_COUNT"] = str(len(names))
        result["TOOLS_NAMES"] = ",".join(names)
        if list_status != 200 or not isinstance(tools, list):
            errors.append(f"tools/list returned HTTP {list_status} without a tools array")

        read_status, _, read_body = mcp_call(
            "mcp_tools_call_list_executors",
            {
                "jsonrpc": "2.0",
                "id": 3,
                "method": "tools/call",
                "params": {"name": "list_executors", "arguments": {}},
            },
            "mcp-evidence-tools-call",
            token,
        )
        structured = read_body.get("result", {}).get("structuredContent")
        result["READ_TOOL_RESULT"] = f"HTTP {read_status};tool=list_executors;structured_content={'present' if structured is not None else 'absent'}"
        if read_status != 200 or not read_body.get("result"):
            errors.append(f"tools/call list_executors returned HTTP {read_status} without result")
    else:
        result["INITIALIZE_STATUS"] = "not_attempted"
        result["TOOLS_LIST_STATUS"] = "not_attempted"
        errors.append("MCP probe not attempted because OAuth token was not obtained")

    result["GATEWAY_REQUEST_IDS"] = ",".join(request_ids) or "none"
    result["ERRORS"] = "; ".join(errors) if errors else "none"
    (args.output / "report.env").write_text(
        "".join(f"{key}={value}\n" for key, value in result.items()), encoding="utf-8"
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
