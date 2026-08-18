from __future__ import annotations

import html
import json
import logging
from datetime import datetime, timezone

from fastapi import Depends, FastAPI, Form, Header, HTTPException, Request, Response, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from gateway.app.api.idempotency import purge_expired
from gateway.app.api.rate_limit import RateLimitDependency, client_key
from gateway.app.api.routes import auth as auth_routes
from gateway.app.api.routes import probes, sessions
from gateway.app.api.setup import install_api_conventions
from gateway.app.core.agent_auth import TokenSource, resolve_executor_token
from gateway.app.core.config import settings
from gateway.app.version import APP_VERSION
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
from gateway.app.core.users import (
    AuthenticatedPrincipal,
    authenticate_async,
    lookup_user,
    unusable_registry_reason,
)
from gateway.app.db.base import Base
from gateway.app.db.schema_guard import check_schema
from gateway.app.db.session import SessionLocal, engine, get_session
from gateway.app.mcp.server import handle_mcp_call
from gateway.app.services import metrics, store
from gateway.app.services.audit import record_event
from gateway.app.services.agent_hub import AgentHub
from shared.protocol import EXECUTOR_TOKEN_HEADER, AgentEnvelope, AgentMessageType, TaskState
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
    version=APP_VERSION,
    openapi_url=None,
    docs_url=None,
    redoc_url=None,
)

# Cross-cutting behaviour for the contract surface (issue #12). One call on
# purpose: the middleware and the handlers must be wired together, and the
# only symptom of wiring one without the other is on the 500 path.
#
# Must stay the LAST add_middleware in this module: `add_middleware` inserts at
# index 0, so anything registered afterwards wraps it, and a failure inside that
# outer layer would answer a contract path with plain text and no request id.
install_api_conventions(app)

hub = AgentHub(SessionLocal)
rate_limiter = MemoryRateLimiter(settings.rate_limit_requests_per_window, settings.rate_limit_window_seconds)

# `/health` and `/ready` are unauthenticated and unlimited on purpose: the
# deployment's own monitoring polls them on a timer, and rate-limiting them makes
# the first symptom of heavy client traffic a red health check.
app.include_router(probes.router)

# `/api/version` is unauthenticated too, but it sits in the public namespace and
# is reachable by anyone, so it carries the limiter.
#
# `dependencies=` binds to THIS router's routes only — a route added later with
# `@app.get("/api/v1/...")` would be unlimited, so this is not "every /api route
# from here on gets it". What makes that true is a test:
# `test_every_served_api_route_carries_the_rate_limiter` fails on any served
# `/api` route without the dependency. Add new API routes to a router carrying it.
app.include_router(probes.version_router, dependencies=[Depends(RateLimitDependency(rate_limiter))])

# Agent sessions (issue #9). Same limiter, and authorization per route through
# gateway/app/api/auth.py against the catalogue in gateway/app/api/permissions.py.
app.include_router(sessions.router, dependencies=[Depends(RateLimitDependency(rate_limiter))])

# The mobile credential lifecycle (issue #4): sign-in, refresh, revocation, and
# the effective permissions a client reads before it offers a control.
#
# The limiter matters more here than anywhere else on this surface: `sign-in` is
# unauthenticated, so its bucket is the caller's address, and it is the one
# endpoint where guessing repeatedly is the whole attack.
app.include_router(auth_routes.router, dependencies=[Depends(RateLimitDependency(rate_limiter))])


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
    user = lookup_user(settings.user_registry_file, item.user_id)
    if user is None or not user.enabled:
        # Says which of the two it is. A gateway whose registry file is missing
        # refused every already-issued token as an unknown-or-disabled *account*,
        # which sends the operator to `users.json` to look for a user that is not
        # the problem. Nothing is leaked by the distinction: the caller already
        # presented a token this gateway issued.
        if unusable_registry_reason(settings.user_registry_file) is not None:
            raise HTTPException(status_code=403, detail="user_registry_unavailable")
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


def report_user_registry_state() -> None:
    """Log, once at startup, when no account can sign in.

    Logged rather than raised. Fail-fast is the rule for missing required config
    (`security-standards.md` §1) and the user registry is not required by every
    deployment: with the default `mcp_auth_mode="bearer"`, `/mcp` authenticates
    against static tokens and never reads `users.json`, so refusing to boot
    would take down a correctly configured gateway to complain about a file it
    does not use. What is not acceptable is the silence — the gateway that
    *does* need it starts clean and refuses every credential with the same
    opaque message an attacker gets.

    `GET /api/version` still reports `passwordSignIn: true`, and that is not a
    lie this hides: the flag describes what this build serves, which is the
    question a client asks it, and no capability flag on that endpoint has ever
    described the deployment's configuration. The operator's signal is here.
    """
    complaint = unusable_registry_reason(settings.user_registry_file)
    if complaint is None:
        return
    logging.getLogger(__name__).error(
        "user registry unusable: %s",
        complaint,
        extra={"correlation_id": None, "task_id": None, "executor_id": None},
    )


@app.on_event("startup")
async def startup() -> None:
    report_user_registry_state()
    async with engine.begin() as connection:
        # `create_all` builds a fresh database but never alters an existing one,
        # so an upgraded deployment starts fine and then fails on the first read
        # that touches a new column. check_schema turns that into a startup
        # failure naming the missing object and the command that adds it.
        await connection.run_sync(Base.metadata.create_all)
        await connection.run_sync(check_schema)
    registry = load_registry(settings.registry_file)
    async with SessionLocal() as session:
        await store.upsert_registry(session, registry.executors, registry.projects)
        await store.recover_tasks_after_startup(session)
        # Idempotency records are client-keyed and would otherwise accumulate
        # forever, each holding a full response body. Startup is the sweep this
        # deployment has: there is no scheduler, and adding one is a bigger
        # change than this issue owns.
        #
        # Housekeeping must not decide whether the gateway serves. A failure here
        # leaves rows to be collected next time; refusing to start over it would
        # give a cleanup the same weight as the schema check.
        try:
            purged = await purge_expired(session)
        except Exception:
            logging.getLogger(__name__).warning(
                "idempotency_purge_failed",
                exc_info=True,
                extra={"correlation_id": None, "task_id": None, "executor_id": None},
            )
        else:
            if purged:
                logging.getLogger(__name__).info(
                    "purged %s expired idempotency record(s)",
                    purged,
                    extra={"correlation_id": None, "task_id": None, "executor_id": None},
                )

        # Same sweep, same reasoning, different table. `audit_events` had no
        # retention at all, and issue #4 gave it an unauthenticated writer:
        # every rejected sign-in commits a row. Same fail-open handling — a
        # cleanup never decides whether the gateway serves.
        try:
            aged = await store.purge_expired_audit_events(
                session, retention_days=settings.audit_event_retention_days
            )
        except Exception:
            logging.getLogger(__name__).warning(
                "audit_purge_failed",
                exc_info=True,
                extra={"correlation_id": None, "task_id": None, "executor_id": None},
            )
        else:
            if aged:
                logging.getLogger(__name__).info(
                    "purged %s audit event(s) past the %s-day retention window",
                    aged,
                    settings.audit_event_retention_days,
                    extra={"correlation_id": None, "task_id": None, "executor_id": None},
                )


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


@app.post(
    "/oauth/authorize",
    response_class=HTMLResponse,
    # The attempt ceiling this endpoint never had. It takes a password, it is
    # unauthenticated, and since the constant-cost guard moved into
    # `users.authenticate` every attempt — including one with an invented
    # username — costs a full PBKDF2 derivation. Closing the enumeration oracle
    # made the cheapest hostile request here ~190x more expensive to serve, so
    # the endpoint with no ceiling became the cheapest way to spend the
    # gateway's CPU. Same limiter and same bucket as the `/api` surface: the
    # caller is unauthenticated, so the bucket is the address.
    #
    # The GET is deliberately not limited: it renders a static form and touches
    # no credential, and throttling the page a human is looking at is not the
    # same decision as throttling the attempt.
    dependencies=[Depends(RateLimitDependency(rate_limiter))],
)
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
    # The same operation the mobile sign-in uses, not a hand-rolled
    # lookup-then-verify. The short-circuit that used to be here answered an
    # unknown username in ~1.6 ms and a real one in ~299 ms against the same
    # `users.json` — a 185x oracle enumerating every account in the registry, on
    # the one auth route that carries no rate limiter. Issue #4 added the
    # constant-cost guard at the mobile call site only, which is precisely the
    # failure `design-standards.md` §3 names: the guard belongs in the operation.
    #
    # `_async` because that derivation has no `await` in it: called directly it
    # would hold the event loop for its whole duration, and ten concurrent
    # attempts here took `GET /health` from 0.8 ms to 3.3 s.
    outcome = await authenticate_async(settings.user_registry_file, username, password)
    user = outcome.user
    if not outcome.ok:
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
    # Same bucket rule as the contract surface. Keying on the raw peer address
    # put every ChatGPT caller in one bucket, because behind nginx that address
    # is always 127.0.0.1 — one caller exhausting the window returned 429 to
    # every other user. Two call sites of one rule; only the new one had been
    # converted, and docs/security.md meanwhile described /mcp as per-IP.
    allowed = await rate_limiter.allow(client_key(request))
    if not allowed:
        metrics.RATE_LIMIT_REJECTIONS.inc()
        raise HTTPException(status_code=429, detail="rate_limit_exceeded")
    body = await request.json()
    principal = await authenticate_mcp_request(session, body, authorization)
    payload = await handle_mcp_call(body, session, hub, principal)
    return Response(content=json.dumps(payload), media_type="application/json")


# What a rejected task.ack means for state, per control. See handle_task_ack
# for why each of these is correct rather than a guess.
_CONTROL_REJECTION_FALLBACK: dict[str, tuple[TaskState, str | None]] = {
    "pause": (TaskState.RUNNING, None),
    "resume": (TaskState.PAUSED, None),
    "restart": (TaskState.FAILED, "The executor could not restart this session: no running process was found."),
}


async def handle_task_ack(session: AsyncSession, envelope: AgentEnvelope) -> None:
    """Handles one `task.ack` from the `/agent/ws` message loop.

    A standalone function rather than inlined in the loop so it is directly
    testable against a real session and a constructed envelope, without
    driving a real websocket through it (council 2026-08-18: the ownership
    check, the state validation and the rejection rollback below all need
    coverage that does not depend on a live socket's timing).
    """
    task_id = envelope.payload.get("task_id")
    accepted = bool(envelope.payload.get("accepted"))
    control = envelope.payload.get("control")
    raw_state = envelope.payload.get("state")

    if task_id is None:
        # The same class of bug the state-validation fix above closes: a
        # direct-subscript read on a caller-controlled payload raises
        # uncaught, killing the /agent/ws loop before it ever reaches
        # `hub.unregister` below (council 2026-08-18, "the adversarial
        # user", round 2 — the sibling this function's own state guard did
        # not cover). There is no task_id to record an audit event against,
        # so this one is logged rather than written to `audit_events`.
        logging.getLogger(__name__).warning(
            "task.ack with no task_id from executor %s", envelope.executor_id
        )
        return

    task = await store.get_task(session, task_id)
    if task is None or task.executor_id != envelope.executor_id:
        # An executor may only ack tasks assigned to it. Without this check,
        # any connected executor could name any task_id in a task.ack and
        # move that session's state — a forged control acknowledgment for a
        # session it never touched (council 2026-08-18, "the adversarial
        # user").
        await record_event(
            session,
            "task",
            task_id,
            "task.ack_refused",
            {
                "executor_id": envelope.executor_id,
                "control": control,
                "reason": "unknown_task" if task is None else "not_owner",
            },
        )
        await session.commit()
        return

    resolved_state: TaskState | None = None
    if accepted:
        try:
            resolved_state = TaskState(raw_state) if raw_state is not None else None
        except ValueError:
            resolved_state = None
        if resolved_state is None:
            # A malformed ack (accepted with no state, or a state string that
            # is not one of ours) used to raise an uncaught ValueError here,
            # which killed the message loop without reaching `hub.unregister`
            # — the executor stayed "connected" in the database with no
            # socket behind it (council 2026-08-18, "the adversarial user").
            # Log and move on instead.
            await record_event(
                session,
                "task",
                task_id,
                "task.ack_refused",
                {
                    "executor_id": envelope.executor_id,
                    "control": control,
                    "reason": "invalid_state",
                    "state": raw_state,
                },
            )
            await session.commit()
            return
        await store.update_task_state(session, task_id, resolved_state)
    elif control in _CONTROL_REJECTION_FALLBACK:
        # A rejected ack used to leave the task parked in
        # PAUSING/RESUMING/RESTARTING forever — nothing else in the codebase
        # ever revisits those states outside a full gateway restart (council
        # 2026-08-18, "the second caller"). `CodexRunner.pause`/`resume` only
        # refuse before touching the process, so reverting to the state the
        # control assumed is exact; `CodexRunner.restart` only refuses when it
        # has no process to restart at all, so there is nothing to revert to
        # and the session is reported failed instead.
        fallback_state, fallback_error = _CONTROL_REJECTION_FALLBACK[control]
        await store.update_task_state(session, task_id, fallback_state, error=fallback_error)

    await record_event(
        session,
        "task",
        task_id,
        "task.control_acknowledged",
        {
            "executor_id": envelope.executor_id,
            "control": control,
            "accepted": accepted,
            "state": raw_state,
        },
    )
    await session.commit()


@app.websocket("/agent/ws")
async def agent_ws(
    websocket: WebSocket,
    executor_id: str,
    token: str | None = None,
    x_executor_token: str | None = Header(default=None),
) -> None:
    presented, source = resolve_executor_token(header_token=x_executor_token, query_token=token)
    if presented is None:
        await websocket.close(code=4401)
        return
    if source == TokenSource.QUERY:
        # No token value here, and none in any branch below: the point of the
        # change is that this handshake stops writing the credential to logs.
        logging.getLogger(__name__).warning(
            "executor %s authenticated with the deprecated token query parameter, which is "
            "recorded verbatim by every access log on the path; send the %s header instead (#15)",
            executor_id,
            EXECUTOR_TOKEN_HEADER,
        )

    async with SessionLocal() as session:
        executor = await session.get(store.ExecutorModel, executor_id)
        if executor is None:
            await websocket.close(code=4404)
            return
        metadata = json.loads(executor.metadata_json)
        accepted_machine_tokens = [metadata["machine_token"], *metadata.get("machine_tokens", [])]
        if not any(secure_compare(presented, accepted) for accepted in accepted_machine_tokens):
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
                elif envelope.type == AgentMessageType.TASK_ACK:
                    await handle_task_ack(session, envelope)
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
                    await record_event(
                        session,
                        "task",
                        envelope.payload["task_id"],
                        "task.cancel_acknowledged",
                        {"executor_id": envelope.executor_id},
                    )
                    await session.commit()
                    await hub.mark_task_finished(envelope.executor_id, envelope.payload["task_id"])
    except WebSocketDisconnect:
        await hub.unregister(executor_id)
