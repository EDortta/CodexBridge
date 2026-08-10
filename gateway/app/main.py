from __future__ import annotations

import html
import json
from datetime import datetime, timezone

from fastapi import Depends, FastAPI, Form, Header, HTTPException, Request, Response, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from gateway.app.core.config import settings
from gateway.app.core.logging import configure_logging
from gateway.app.core.oauth import (
    error_redirect,
    expires_in,
    generate_access_token,
    generate_authorization_code,
    issuer_metadata,
    pkce_challenge,
    protected_resource_metadata,
)
from gateway.app.core.rate_limit import MemoryRateLimiter
from gateway.app.core.registry import load_registry
from gateway.app.core.users import AuthenticatedPrincipal, lookup_user, verify_password
from gateway.app.db.base import Base
from gateway.app.db.session import SessionLocal, engine, get_session
from gateway.app.mcp.server import handle_mcp_call
from gateway.app.services import metrics, store
from gateway.app.services.agent_hub import AgentHub
from shared.protocol import AgentEnvelope, AgentMessageType, TaskState
from shared.security import sanitize_log_line, secure_compare


configure_logging()

# FastAPI's auto-generated OpenAPI document and its UIs are switched off on
# purpose. They are produced by introspecting this application, so they publish
# the internal MCP and OAuth surfaces and carry none of the rules the mobile
# contract depends on (versioning, deprecation, forbidden fields). Serving them
# alongside `docs/api/codex-bridge.openapi.yaml` put two public descriptions of
# one gateway on the wire, and the reachable one was not the canonical one — so
# any consumer doing the obvious thing (`GET /openapi.json`) found the wrong
# document. The canonical contract is the only description of this API.
# `tests/contract/test_openapi_document.py::test_generated_openapi_is_not_served`
# keeps them off.
app = FastAPI(
    title="CodexBridge Gateway",
    version="0.1.0",
    openapi_url=None,
    docs_url=None,
    redoc_url=None,
)
hub = AgentHub(SessionLocal)
rate_limiter = MemoryRateLimiter(settings.rate_limit_requests_per_window, settings.rate_limit_window_seconds)


def oauth_www_authenticate_header() -> str:
    resource_metadata = f'{settings.effective_oauth_issuer()}/.well-known/oauth-protected-resource'
    return f'Bearer realm="codex-bridge", resource_metadata="{resource_metadata}"'


def validate_oauth_client(client_id: str, redirect_uri: str) -> None:
    if client_id not in settings.oauth_client_ids():
        raise HTTPException(status_code=400, detail="unauthorized_client")
    if not redirect_uri.startswith(settings.oauth_redirect_uri_prefixes()):
        raise HTTPException(status_code=400, detail="invalid_redirect_uri")


def render_authorize_form(
    *,
    client_id: str,
    redirect_uri: str,
    state: str | None,
    scope: str,
    code_challenge: str,
    code_challenge_method: str,
    error: str | None = None,
) -> HTMLResponse:
    error_html = f'<p style="color:#b91c1c">{html.escape(error)}</p>' if error else ""
    body = f"""<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <title>CodexBridge OAuth</title>
    <style>
      body {{ font-family: sans-serif; max-width: 36rem; margin: 3rem auto; padding: 0 1rem; }}
      input {{ display:block; width:100%; padding:0.65rem; margin:0.5rem 0 1rem; }}
      button {{ padding:0.75rem 1rem; }}
      .hint {{ color:#555; font-size:0.95rem; }}
    </style>
  </head>
  <body>
    <h1>Authorize CodexBridge</h1>
    <p class="hint">Sign in with an approved CodexBridge user to let ChatGPT call this MCP server on your behalf.</p>
    {error_html}
    <form method="post" action="/oauth/authorize">
      <input type="hidden" name="response_type" value="code" />
      <input type="hidden" name="client_id" value="{html.escape(client_id)}" />
      <input type="hidden" name="redirect_uri" value="{html.escape(redirect_uri)}" />
      <input type="hidden" name="state" value="{html.escape(state or '')}" />
      <input type="hidden" name="scope" value="{html.escape(scope)}" />
      <input type="hidden" name="code_challenge" value="{html.escape(code_challenge)}" />
      <input type="hidden" name="code_challenge_method" value="{html.escape(code_challenge_method)}" />
      <label>Username or email</label>
      <input name="username" autocomplete="username" />
      <label>Password</label>
      <input name="password" type="password" autocomplete="current-password" />
      <button type="submit">Authorize</button>
    </form>
  </body>
</html>"""
    return HTMLResponse(body)


async def authenticate_mcp_request(
    session: AsyncSession,
    body: dict,
    authorization: str | None,
) -> AuthenticatedPrincipal | None:
    if settings.mcp_auth_mode == "bearer":
        if not authorization or not authorization.startswith("Bearer "):
            raise HTTPException(status_code=401, detail="missing_bearer_token")
        token = authorization.removeprefix("Bearer ").strip()
        if not any(secure_compare(token, accepted) for accepted in settings.accepted_mcp_tokens()):
            raise HTTPException(status_code=403, detail="invalid_bearer_token")
        return None

    discovery_allowed = settings.oauth_allow_unauthenticated_discovery and body.get("method") in {"initialize", "tools/list"}
    if not authorization or not authorization.startswith("Bearer "):
        if discovery_allowed:
            return None
        raise HTTPException(
            status_code=401,
            detail="oauth_bearer_required",
            headers={"WWW-Authenticate": oauth_www_authenticate_header()},
        )
    token = authorization.removeprefix("Bearer ").strip()
    item = await store.get_oauth_access_token(session, token)
    if item is None:
        raise HTTPException(
            status_code=401,
            detail="invalid_oauth_token",
            headers={"WWW-Authenticate": oauth_www_authenticate_header()},
        )
    user = lookup_user(settings.user_registry_file, item.user_id) or lookup_user(settings.user_registry_file, item.user_email)
    if user is None or not user.enabled:
        raise HTTPException(status_code=403, detail="unknown_or_disabled_user")
    scopes = json.loads(item.scopes_json or "[]")
    return AuthenticatedPrincipal(
        user_id=user.user_id,
        email=user.email,
        roles=user.roles,
        allowed_projects=user.allowed_projects,
        scopes=scopes,
        can_approve_sensitive=user.can_approve_sensitive,
        auth_scheme="oauth",
    )


@app.on_event("startup")
async def startup() -> None:
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    registry = load_registry(settings.registry_file)
    async with SessionLocal() as session:
        await store.upsert_registry(session, registry.executors, registry.projects)
        await store.recover_tasks_after_startup(session)


@app.get("/healthz")
async def healthz() -> dict:
    return {"ok": True, "time": datetime.now(timezone.utc).isoformat()}


@app.get("/metrics")
async def metrics_endpoint() -> Response:
    return Response(metrics.render_metrics(), media_type="text/plain; version=0.0.4")


@app.get("/.well-known/oauth-authorization-server")
@app.get("/.well-known/openid-configuration")
async def oauth_metadata() -> dict:
    return issuer_metadata()


@app.get("/.well-known/oauth-protected-resource")
async def oauth_protected_resource() -> dict:
    return protected_resource_metadata()


@app.get("/oauth/authorize", response_class=HTMLResponse)
async def oauth_authorize(
    response_type: str,
    client_id: str,
    redirect_uri: str,
    scope: str | None = None,
    state: str | None = None,
    code_challenge: str | None = None,
    code_challenge_method: str = "S256",
) -> HTMLResponse:
    validate_oauth_client(client_id, redirect_uri)
    if response_type != "code":
        raise HTTPException(status_code=400, detail="unsupported_response_type")
    if not code_challenge:
        raise HTTPException(status_code=400, detail="missing_code_challenge")
    if code_challenge_method != "S256":
        raise HTTPException(status_code=400, detail="unsupported_code_challenge_method")
    normalized_scope = scope or " ".join(sorted(settings.oauth_scopes()))
    return render_authorize_form(
        client_id=client_id,
        redirect_uri=redirect_uri,
        state=state,
        scope=normalized_scope,
        code_challenge=code_challenge,
        code_challenge_method=code_challenge_method,
    )


@app.post("/oauth/authorize", response_class=HTMLResponse)
async def oauth_authorize_submit(
    response_type: str = Form(...),
    client_id: str = Form(...),
    redirect_uri: str = Form(...),
    scope: str = Form(default=""),
    state: str = Form(default=""),
    code_challenge: str = Form(...),
    code_challenge_method: str = Form(default="S256"),
    username: str = Form(...),
    password: str = Form(...),
    session: AsyncSession = Depends(get_session),
) -> Response:
    validate_oauth_client(client_id, redirect_uri)
    if response_type != "code":
        raise HTTPException(status_code=400, detail="unsupported_response_type")
    if code_challenge_method != "S256":
        raise HTTPException(status_code=400, detail="unsupported_code_challenge_method")
    user = lookup_user(settings.user_registry_file, username)
    if user is None or not user.enabled or not verify_password(password, user.password_hash):
        return render_authorize_form(
            client_id=client_id,
            redirect_uri=redirect_uri,
            state=state or None,
            scope=scope,
            code_challenge=code_challenge,
            code_challenge_method=code_challenge_method,
            error="Invalid username or password.",
        )
    requested_scopes = {item for item in scope.split() if item}
    allowed_scopes = set(user.scopes) & settings.oauth_scopes()
    if not requested_scopes:
        requested_scopes = allowed_scopes
    if not requested_scopes or not requested_scopes.issubset(allowed_scopes):
        return render_authorize_form(
            client_id=client_id,
            redirect_uri=redirect_uri,
            state=state or None,
            scope=scope,
            code_challenge=code_challenge,
            code_challenge_method=code_challenge_method,
            error="Requested scopes are not allowed for this user.",
        )
    code = generate_authorization_code()
    await store.create_oauth_authorization_code(
        session,
        code=code,
        client_id=client_id,
        redirect_uri=redirect_uri,
        user_id=user.user_id,
        user_email=user.email,
        scopes=sorted(requested_scopes),
        code_challenge=code_challenge,
        code_challenge_method=code_challenge_method,
        expires_at=expires_in(settings.oauth_authorization_code_ttl_seconds),
    )
    redirect = f"{redirect_uri}?code={code}"
    if state:
        redirect = f"{redirect}&state={state}"
    return RedirectResponse(redirect, status_code=302)


@app.post("/oauth/token")
async def oauth_token(
    grant_type: str = Form(...),
    code: str = Form(...),
    redirect_uri: str = Form(...),
    client_id: str = Form(...),
    code_verifier: str = Form(...),
    session: AsyncSession = Depends(get_session),
) -> dict:
    validate_oauth_client(client_id, redirect_uri)
    if grant_type != "authorization_code":
        raise HTTPException(status_code=400, detail="unsupported_grant_type")
    item = await store.consume_oauth_authorization_code(session, code)
    if item is None:
        raise HTTPException(status_code=400, detail="invalid_grant")
    if item.client_id != client_id or item.redirect_uri != redirect_uri:
        raise HTTPException(status_code=400, detail="invalid_grant")
    if item.code_challenge_method != "S256" or pkce_challenge(code_verifier) != item.code_challenge:
        raise HTTPException(status_code=400, detail="invalid_grant")
    scopes = json.loads(item.scopes_json or "[]")
    access_token = generate_access_token()
    await store.create_oauth_access_token(
        session,
        token=access_token,
        client_id=client_id,
        user_id=item.user_id,
        user_email=item.user_email,
        scopes=scopes,
        expires_at=expires_in(settings.oauth_access_token_ttl_seconds),
    )
    return {
        "access_token": access_token,
        "token_type": "Bearer",
        "expires_in": settings.oauth_access_token_ttl_seconds,
        "scope": " ".join(scopes),
    }


@app.post("/mcp")
async def mcp_endpoint(
    request: Request,
    authorization: str | None = Header(default=None),
    session: AsyncSession = Depends(get_session),
) -> Response:
    client_ip = request.client.host if request.client else "unknown"
    allowed = await rate_limiter.allow(client_ip)
    if not allowed:
        metrics.RATE_LIMIT_REJECTIONS.inc()
        raise HTTPException(status_code=429, detail="rate_limit_exceeded")
    body = await request.json()
    principal = await authenticate_mcp_request(session, body, authorization)
    payload = await handle_mcp_call(body, session, hub, principal)
    return Response(content=json.dumps(payload), media_type="application/json")


@app.websocket("/agent/ws")
async def agent_ws(
    websocket: WebSocket,
    executor_id: str,
    token: str,
) -> None:
    async with SessionLocal() as session:
        executor = await session.get(store.ExecutorModel, executor_id)
        if executor is None:
            await websocket.close(code=4404)
            return
        metadata = json.loads(executor.metadata_json)
        accepted_machine_tokens = [metadata["machine_token"], *metadata.get("machine_tokens", [])]
        if not any(secure_compare(token, accepted) for accepted in accepted_machine_tokens):
            await websocket.close(code=4403)
            return

    await websocket.accept()
    await hub.register(executor_id, websocket)
    await websocket.send_json(
        AgentEnvelope(
            message_id="hello-ack",
            executor_id=executor_id,
            sent_at=datetime.now(timezone.utc),
            type=AgentMessageType.HELLO_ACK,
            payload={"accepted": True},
        ).model_dump(mode="json")
    )
    dispatch_payload = await hub.dispatch_next(executor_id)
    if dispatch_payload is not None:
        await hub.send(
            executor_id,
            AgentEnvelope(
                message_id=f"dispatch-{dispatch_payload['task_id']}",
                executor_id=executor_id,
                sent_at=datetime.now(timezone.utc),
                type=AgentMessageType.TASK_DISPATCH,
                payload=dispatch_payload,
            ),
        )
    try:
        while True:
            raw = await websocket.receive_json()
            envelope = AgentEnvelope.model_validate(raw)
            async with SessionLocal() as session:
                is_new = await store.store_message_receipt(session, envelope.message_id, envelope.executor_id, envelope.type.value)
                if not is_new:
                    continue
                if envelope.type == AgentMessageType.HEARTBEAT:
                    await store.mark_executor_connected(session, envelope.executor_id, True)
                elif envelope.type == AgentMessageType.TASK_LOG:
                    await store.append_log(
                        session,
                        envelope.payload["task_id"],
                        int(envelope.payload["offset"]),
                        envelope.payload["stream"],
                        sanitize_log_line(envelope.payload["line"]),
                    )
                elif envelope.type == AgentMessageType.TASK_RESULT:
                    final_state = TaskState(envelope.payload["final_state"])
                    await store.store_result(session, envelope.payload["task_id"], envelope.payload, final_state)
                    await hub.mark_task_finished(envelope.executor_id, envelope.payload["task_id"])
                    next_payload = await hub.dispatch_next(envelope.executor_id)
                    if next_payload is not None:
                        await hub.send(
                            executor_id,
                            AgentEnvelope(
                                message_id=f"dispatch-{next_payload['task_id']}",
                                executor_id=executor_id,
                                sent_at=datetime.now(timezone.utc),
                                type=AgentMessageType.TASK_DISPATCH,
                                payload=next_payload,
                            ),
                        )
                elif envelope.type == AgentMessageType.TASK_CANCELLED:
                    await store.update_task_state(session, envelope.payload["task_id"], TaskState.CANCELLED)
                    await hub.mark_task_finished(envelope.executor_id, envelope.payload["task_id"])
    except WebSocketDisconnect:
        await hub.unregister(executor_id)
