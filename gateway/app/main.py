from __future__ import annotations

import html
import json
import logging
from datetime import datetime, timezone

from fastapi import Depends, FastAPI, Form, Header, HTTPException, Request, Response, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from gateway.app.api.idempotency import purge_expired
from gateway.app.api.rate_limit import RateLimitDependency, client_key
from gateway.app.api.routes import auth as auth_routes
from gateway.app.api.routes import decisions, missions, nodes as nodes_routes, probes, projects, sessions
from gateway.app.api.routes import artifacts as artifacts_routes
from gateway.app.api.routes import authorizations as authorizations_routes
from gateway.app.api.routes import control_ui as control_ui_routes
from gateway.app.api.routes import conversations as conversations_routes
from gateway.app.api.routes import enrollment as enrollment_routes
from gateway.app.api.routes import discovery as discovery_routes
from gateway.app.api.routes import epics as epics_routes
from gateway.app.api.routes import events as events_routes
from gateway.app.api.routes import issues as issues_routes
from gateway.app.api.routes import notifications as notifications_routes
from gateway.app.api.setup import install_api_conventions
from gateway.app.core.agent_auth import resolve_executor_token
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
from gateway.app.models.entities import TaskModel
from gateway.app.services import metrics, store
from gateway.app.services.audit import record_event
from gateway.app.services.agent_hub import AgentHub
from gateway.app.services.notify import notify_task_finished
from shared.protocol import EXECUTOR_TOKEN_HEADER, AgentEnvelope, AgentMessageType, NodeAnnouncement, TaskState
from shared.security import hash_token, sanitize_log_line, secure_compare
from shared.protocol import (
    EXECUTOR_TOKEN_HEADER,
    AgentEnvelope,
    AgentMessageType,
    DiscoveryReport,
    NodeAnnouncement,
    TaskState,
)
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

hub = AgentHub(
    SessionLocal,
    cancel_replay_max_age_seconds=settings.cancel_replay_max_age_seconds,
    control_replay_max_age_seconds=settings.control_replay_max_age_seconds,
)
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

# Projects and the project operational dashboard (issue #5). Same limiter and
# authorization pattern as sessions.
app.include_router(projects.router, dependencies=[Depends(RateLimitDependency(rate_limiter))])

# Operational decisions (issue #6): the mobile Decision Center's view onto the
# same approval flow the MCP transport's approve_codex_task tool already drives.
app.include_router(decisions.router, dependencies=[Depends(RateLimitDependency(rate_limiter))])

# Missions (issue #7): the mission-control view of the same TaskModel rows,
# with objective/stage/risk/blocked framing and a timeline. Same limiter and
# the same per-route authorization as sessions.router.
app.include_router(missions.router, dependencies=[Depends(RateLimitDependency(rate_limiter))])

# The mobile credential lifecycle (issue #4): sign-in, refresh, revocation, and
# the effective permissions a client reads before it offers a control.
#
# The limiter matters more here than anywhere else on this surface: `sign-in` is
# unauthenticated, so its bucket is the caller's address, and it is the one
# endpoint where guessing repeatedly is the whole attack.
app.include_router(auth_routes.router, dependencies=[Depends(RateLimitDependency(rate_limiter))])

# Provider-neutral planning entities for CodexBridgeMobile (issue #8): epics,
# issues, and the one relationship between them. Same limiter, same
# authorization plumbing as sessions and auth above.
app.include_router(epics_routes.router, dependencies=[Depends(RateLimitDependency(rate_limiter))])
app.include_router(issues_routes.router, dependencies=[Depends(RateLimitDependency(rate_limiter))])

# Contextual conversations and messaging (issue #10): threads linked to
# projects, sessions/decisions/missions and issues. Same limiter, same
# authorization plumbing as epics and issues above.
app.include_router(conversations_routes.router, dependencies=[Depends(RateLimitDependency(rate_limiter))])

# The artifact catalogue, Android build metadata and the download flow (issue
# #11). The limiter matters on `/artifacts/{id}/download` in particular: it is
# the one route on this surface that authenticates with a token minted for it
# rather than with a session bearer, and it streams bytes off disk.
app.include_router(artifacts_routes.router, dependencies=[Depends(RateLimitDependency(rate_limiter))])

# The mobile event stream and its polling fallback (issue #13). Same limiter as
# every other /api router — and note what the limiter does *not* bound here: it
# counts requests per window, while one accepted request to `/events/stream`
# becomes a connection held open for minutes. `routes/events.py:StreamSlots` is
# what bounds that; the limiter still guards the rate of opening attempts.
app.include_router(events_routes.router, dependencies=[Depends(RateLimitDependency(rate_limiter))])

# Notification-subscription preferences (issue #13): recorded intent for a push
# transport this build does not have. See `routes/notifications.py`.
app.include_router(notifications_routes.router, dependencies=[Depends(RateLimitDependency(rate_limiter))])

# Bridge Node fleet visibility (issue #73, Stage 2). Same limiter; guarded by
# the fleet-wide `permissions.NODES_READ` action rather than the
# project-scoped `visible_projects` pattern the routers above use.
app.include_router(nodes_routes.router, dependencies=[Depends(RateLimitDependency(rate_limiter))])

# Node enrollment (issue #76, minimal cut): invite/enroll/revoke. Same
# limiter and the same shared `rate_limiter` instance `POST /oauth/authorize`
# uses -- `POST /api/v1/nodes/enroll` is, like that endpoint, unauthenticated
# and mints a credential, so it gets the identical per-IP bucket rather than a
# router-specific one.
app.include_router(enrollment_routes.router, dependencies=[Depends(RateLimitDependency(rate_limiter))])
# Discovered-resource adoption (issue #73, Stage 3 adoption half). Same
# limiter, same administrative/fleet-wide posture as nodes.router above --
# guarded by `NODES_DISCOVERIES_READ`/`NODES_DISCOVERIES_DECIDE`.
app.include_router(discovery_routes.router, dependencies=[Depends(RateLimitDependency(rate_limiter))])

# The explicit operator grant/revoke of `project_authorizations` (issue #73,
# Stage 4). Same limiter, same administrative/fleet-wide posture as
# discovery_routes above -- guarded by `NODES_AUTHORIZATIONS_MANAGE`, whose
# own second gate (granting `modify`/`deliver` needs `can_approve_sensitive`
# or admin) lives inside `permissions.is_allowed`, not here.
app.include_router(authorizations_routes.router, dependencies=[Depends(RateLimitDependency(rate_limiter))])

# CodexBridge Control's first server-rendered screens (issue #73 Stage 5,
# `gateway/app/api/routes/control_ui.py`). Rate-limited like every other
# route that touches a password: `control_ui.py`'s own auth re-derives the
# HTTP Basic credential's PBKDF2 hash on *every* request, including plain
# navigation and pagination, for the same "close the enumeration oracle"
# reason `POST /oauth/authorize` carries this dependency. `/control` is
# deliberately NOT under `/api/v1` -- it is not part of the mobile contract
# (`tests/contract/test_openapi_document.py`), the same way `/oauth/*` and
# `/mcp` sit outside it.
app.include_router(control_ui_routes.router, dependencies=[Depends(RateLimitDependency(rate_limiter))])


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
    # Whether the runner has any record of the task at all, as opposed to
    # knowing it but refusing for a real reason (already paused, nothing to
    # restart). Older agents that predate this field are treated as "known"
    # — the fallback behaviour every version before this one already had
    # (issue #17 council, "the sweep skeptic" / "the second caller").
    known = bool(envelope.payload.get("known", True))

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

    # Set only by the "reconnect with no record" branch below, the one path
    # through this function that can land a task in a terminal state
    # (CANCELLED) — task.ack otherwise only ever carries pause/resume/restart
    # control acks. Notified after the shared commit at the end of this
    # function, same ordering as the TASK_RESULT branch (issue #70).
    finished_task: TaskModel | None = None

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
    elif control in _CONTROL_REJECTION_FALLBACK and known:
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
    elif control in _CONTROL_REJECTION_FALLBACK and not known:
        # The runner has no record of this task at all — a reconnect replay
        # (`AgentHub.register`) reaching a fresh runner that lost its
        # in-memory state, e.g. after the executor host restarted (issue
        # #17). None of `_CONTROL_REJECTION_FALLBACK`'s states are honest
        # here: "revert to RUNNING/PAUSED" assumes the process is still
        # alive somewhere, and on this runner it never was. Resolve it the
        # way an unknown `task.cancel` now does — CANCELLED, and the
        # concurrency slot released — instead of leaving `running_tasks`
        # pinned by an id nothing will ever acknowledge again
        # (`gateway/app/services/agent_hub.py`, `mark_task_finished` is the
        # only remover).
        finished_task = await store.update_task_state(
            session,
            task_id,
            TaskState.CANCELLED,
            error="Executor reconnected with no record of this task; treated as lost.",
        )
        await hub.mark_task_finished(envelope.executor_id, task_id)
        # Without this, `list_tasks_requiring_cancel_replay` (store.py) has no
        # `task.cancel_acknowledged` row to exclude this id by, so the very
        # next reconnect treats this already-resolved ghost as a fresh
        # cancellation to replay — resending `task.cancel` for a task already
        # reported cancelled and re-pinning the slot right where the queue
        # would restart (issue #17 council round 2, "the claim auditor").
        await record_event(
            session,
            "task",
            task_id,
            "task.cancel_acknowledged",
            {"executor_id": envelope.executor_id},
        )

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
    if finished_task is not None:
        await notify_task_finished(session, finished_task, settings)


async def handle_task_cancelled(session: AsyncSession, envelope: AgentEnvelope) -> None:
    """Handles one `task.cancelled` ack from the `/agent/ws` message loop.

    Standalone for the same reason `handle_task_ack` is (see its docstring):
    directly testable against a real session and a constructed envelope,
    without driving a real websocket through it. Extracted rather than left
    inline so issue #17's fix — the agent now sends this unconditionally,
    including for a task the runner never heard of — has something to prove
    itself against on the gateway side: that receiving it actually releases
    `hub.running_tasks`, not just that the agent sent it.
    """
    task_id = envelope.payload["task_id"]
    task = await store.update_task_state(session, task_id, TaskState.CANCELLED)
    await record_event(
        session,
        "task",
        task_id,
        "task.cancel_acknowledged",
        {"executor_id": envelope.executor_id},
    )
    await session.commit()
    # After the commit: the task's own state is already final, so a
    # notification failure here cannot roll anything back (issue #70).
    await notify_task_finished(session, task, settings)
    await hub.mark_task_finished(envelope.executor_id, task_id)


async def handle_issue_materialize_result(session: AsyncSession, envelope: AgentEnvelope) -> None:
    """Handles one `issue.materialize_result` from the `/agent/ws` message loop.

    Issue #78, Commit 2. Unlike `TASK_RESULT`, there is no `TaskModel` row
    behind this message and no executor concurrency slot to release
    (`publish_epic_to_repo`, `gateway/app/mcp/server.py`, sent this directly
    via `hub.send`) -- only `store.apply_epic_materialization` to run on
    success, or an audit event on a typed failure. Standalone for the same
    reason `handle_task_cancelled` is: directly testable against a
    constructed envelope, without driving a real websocket through it.
    """
    payload = envelope.payload
    epic_id = payload.get("epic_id")
    if epic_id is None:
        logging.getLogger(__name__).warning(
            "issue.materialize_result with no epic_id from executor %s", envelope.executor_id
        )
        return

    if not payload.get("ok", False):
        await record_event(
            session, "epic", epic_id, "epic.materialize_failed",
            {"executor_id": envelope.executor_id, "error": payload.get("error")},
        )
        await session.commit()
        return

    epic = await store.apply_epic_materialization(
        session,
        epic_id=epic_id,
        epic_path=payload["epic_path"],
        epic_revision=int(payload["epic_revision"]),
        written_paths=payload.get("written_paths", {}),
        issue_revisions=payload.get("issue_revisions", {}),
    )
    if epic is None:
        logging.getLogger(__name__).warning(
            "issue.materialize_result for unknown epic %s from executor %s", epic_id, envelope.executor_id
        )
        return
    await record_event(
        session, "epic", epic_id, "epic.materialized",
        {
            "executor_id": envelope.executor_id,
            "epic_path": payload["epic_path"],
            "file_count": len(payload.get("written_paths", {})),
        },
    )
    await session.commit()


async def handle_forge_operation_result(session: AsyncSession, envelope: AgentEnvelope) -> None:
    """Handles one `forge.operation_result` from the `/agent/ws` message loop.

    Issue #80/#79, WK-20260902-forge-wiring-and-gate (PR B3). Standalone for
    the same reason `handle_task_ack`/`handle_task_cancelled` are: directly
    testable against a real session and a constructed envelope, without
    driving a real websocket through it. There is no ownership check to
    mirror `handle_task_ack`'s ("an executor may only ack tasks assigned to
    it") because `store.resolve_forge_operation` does not branch on
    `executor_id` at all -- a forge operation, unlike a task, never changes
    which executor holds it, so there is nothing here for a forged
    `operation_id` to redirect. A missing or unknown `operation_id` raises
    `ValueError` from `store.resolve_forge_operation` and is logged rather
    than crashing the message loop, the same posture
    `handle_task_ack` takes toward a malformed payload.
    """
    operation_id = envelope.payload.get("operation_id")
    if operation_id is None:
        logging.getLogger(__name__).warning(
            "forge.operation_result with no operation_id from executor %s", envelope.executor_id
        )
        return
    try:
        await store.resolve_forge_operation(session, operation_id, envelope.payload)
    except ValueError:
        logging.getLogger(__name__).warning(
            "forge.operation_result for unknown operation %s from executor %s",
            operation_id,
            envelope.executor_id,
        )
        await session.rollback()
        return
    await record_event(
        session,
        "forge_operation",
        operation_id,
        "forge_operation.result_received",
        {"executor_id": envelope.executor_id, "outcome": envelope.payload.get("outcome")},
    )
    await session.commit()


@app.websocket("/agent/ws")
async def agent_ws(
    websocket: WebSocket,
    executor_id: str,
    x_executor_token: str | None = Header(default=None, alias=EXECUTOR_TOKEN_HEADER),
) -> None:
    # The token is read from the header only. The deprecated `?token=...` form
    # #15 kept accepting for one release is gone: a credential in the URL is a
    # credential in every access log on the path, and the transition window it
    # existed for has closed.
    presented = resolve_executor_token(header_token=x_executor_token)
    if presented is None:
        await websocket.close(code=4401)
        return

    async with SessionLocal() as session:
        executor = await session.get(store.ExecutorModel, executor_id)
        if executor is None:
            await websocket.close(code=4404)
            return
        # Issue #76: the credential this handshake checks is
        # `executor.machine_token_hash`, never `metadata_json`. An executor
        # seeded by `registry.json` still carries its clear-text token inside
        # `metadata_json["machine_token"]`, but that is no longer what gets
        # compared here -- `store.upsert_registry` backfills the hash column
        # from it once, at startup, and this handshake reads only the hash
        # from then on. A `machine_token_hash` that is still empty (a
        # database that has not run `0013_node_enrollment.sql`, or an
        # executor row nothing has ever backfilled) can never match a
        # presented token, and is refused the same as a wrong one.
        if not executor.machine_token_hash or not secure_compare(
            hash_token(presented), executor.machine_token_hash
        ):
            await websocket.close(code=4403)
            return
        # Issue #76 decision #4: revoking closes a live socket via
        # `AgentHub.force_close` (called from the revoke endpoint) AND refuses
        # the next reconnect -- this is the refusal half. Checked on
        # `admission_state`, not on `executor.enabled`: `enabled` already
        # means something softer today (may this executor be given new work),
        # is left alone by an ordinary disable, and gating the handshake on it
        # would change behaviour for every executor an operator has ever
        # disabled without revoking. A revoked node has no `node_id` only if
        # its row predates issue #73 entirely, which cannot happen for a node
        # enrolled through this cut.
        node = await session.get(store.NodeModel, executor.node_id) if executor.node_id else None
        if node is not None and node.admission_state == "revoked":
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
            if envelope.executor_id != executor_id:
                # `envelope.executor_id` is a field the CLIENT writes into the
                # message body. `executor_id` is the one that presented a
                # machine token at the handshake. Believing the first let any
                # connected node write another node's row -- forging its
                # reported capabilities, or refreshing its liveness so a dead
                # node reads healthy -- which is precisely the fleet surface
                # #73 Stage 2 exists to make trustworthy.
                #
                # The guard lives here, once, rather than in each branch: #16
                # already fixed this for `task.ack` alone (`handle_task_ack`),
                # and the branches added since inherited the same trust. One
                # check before the dispatch means the next message type cannot
                # reintroduce it.
                logging.getLogger(__name__).warning(
                    "executor %s sent an envelope claiming executor_id %s; dropping it",
                    sanitize_log_line(executor_id),
                    sanitize_log_line(envelope.executor_id),
                )
                continue
            async with SessionLocal() as session:
                is_new = await store.store_message_receipt(session, envelope.message_id, envelope.executor_id, envelope.type.value)
                if not is_new:
                    continue
                if envelope.type == AgentMessageType.HELLO:
                    # Issue #73 Stage 2. Backward compatibility matters here: an
                    # agent from before this change sends `{"version": "0.1.0"}`,
                    # which validates as a `NodeAnnouncement` only by accident
                    # (Pydantic ignores the unknown key and every field has a
                    # default) -- so the old shape is handled explicitly rather
                    # than left to that accident: `version` is read as
                    # `agent_version` when the payload carries no `agent_version`
                    # of its own. A HELLO that still fails validation after that
                    # rewrite is logged and the loop CONTINUES: a gateway that
                    # hangs up on the previous agent release turns a deploy into
                    # an outage, so this branch must never close the socket or
                    # raise out of the receive loop.
                    payload = dict(envelope.payload)
                    if "version" in payload and "agent_version" not in payload:
                        payload["agent_version"] = payload.pop("version")
                    try:
                        announcement = NodeAnnouncement.model_validate(payload)
                    except ValidationError:
                        logging.getLogger(__name__).warning(
                            "executor %s sent a HELLO payload that failed NodeAnnouncement "
                            "validation; ignoring it and keeping the connection open",
                            envelope.executor_id,
                        )
                    else:
                        # The authenticated id, never the claimed one -- the
                        # guard at the top of the loop has already refused any
                        # envelope where they differ.
                        hello_executor = await session.get(store.ExecutorModel, executor_id)
                        if hello_executor is not None:
                            await store.record_node_announcement(session, hello_executor, announcement)
                elif envelope.type == AgentMessageType.DISCOVERY_REPORT:
                    # Issue #73 Stage 3. This branch calls exactly ONE store
                    # function, and that function writes to exactly ONE
                    # table (`discovered_resources`). That is not a style
                    # choice -- it is what makes "the node proposes, the
                    # panel adopts" true by construction rather than by
                    # convention: there is no code path from a connected
                    # node's own message to `project_authorizations`,
                    # `projects`, or `workspace_bindings`. Adoption is a
                    # separate, operator-scoped surface (a later PR), never
                    # a side effect of a node reporting what it saw.
                    #
                    # Same tolerant-parse posture as HELLO above: a
                    # malformed report is logged and dropped, never a reason
                    # to close the socket -- a bug in one node's discovery
                    # scan must not look like a dropped connection to the
                    # operator, and must not stop that node's tasks, logs or
                    # heartbeats, which all share this same loop.
                    try:
                        report = DiscoveryReport.model_validate(envelope.payload)
                    except ValidationError:
                        logging.getLogger(__name__).warning(
                            "executor %s sent a DISCOVERY_REPORT payload that failed validation; ignoring it",
                            sanitize_log_line(envelope.executor_id),
                        )
                    else:
                        discovery_executor = await session.get(store.ExecutorModel, executor_id)
                        if discovery_executor is not None:
                            await store.record_discovery_report(session, discovery_executor, report)
                elif envelope.type == AgentMessageType.HEARTBEAT:
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
                    task = await store.store_result(session, envelope.payload["task_id"], envelope.payload, final_state)
                    # `mark_task_finished` dispatches the next queued task
                    # itself now (`AgentHub.mark_task_finished`) — this used
                    # to be the one branch that remembered to do it by hand,
                    # which is exactly the shape design-standards.md §3 warns
                    # about: the other callers that free a slot did not.
                    await hub.mark_task_finished(envelope.executor_id, envelope.payload["task_id"])
                    # After both of the above: the task's own state is
                    # already committed, so a notification failure here
                    # cannot roll anything back (issue #70).
                    await notify_task_finished(session, task, settings)
                elif envelope.type == AgentMessageType.TASK_CANCELLED:
                    await handle_task_cancelled(session, envelope)
                elif envelope.type == AgentMessageType.ISSUE_MATERIALIZE_RESULT:
                    await handle_issue_materialize_result(session, envelope)
                elif envelope.type == AgentMessageType.FORGE_OPERATION_RESULT:
                    await handle_forge_operation_result(session, envelope)
    except WebSocketDisconnect:
        await hub.unregister(executor_id)
