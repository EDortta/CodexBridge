"""Liveness, readiness and version — what a client asks before anything else.

These three answer questions the mobile client cannot ask from inside an
authenticated, versioned namespace: *is the server up*, *can it actually serve*,
and *do we speak the same API*. All three are unauthenticated, and none of them
reports a hostname, a port, a database URL or a filesystem path.

The distinction that matters here is **live vs ready vs degraded**:

- `/health` says the process is running. It touches nothing else, so it stays
  true even when every dependency is down. A liveness probe that queries the
  database restarts a healthy process because the database blinked.
- `/ready` says the process can serve requests. It checks the dependencies a
  request actually needs, and returns 503 when one of them is missing — which is
  what tells a load balancer to stop sending traffic.
- **Degraded is not unready.** No executor connected means new tasks cannot run,
  but every read still works. Returning 503 for that would take the API offline
  precisely when an operator needs it to see why nothing is executing.
"""

from __future__ import annotations

import asyncio
import time

from fastapi import APIRouter, Response
from sqlalchemy import text

from gateway.app.api import timestamps
from gateway.app.api.errors import DEPENDENCY_UNAVAILABLE, error_body
from gateway.app.core.config import settings
from gateway.app.db.session import engine


# Two routers, because they carry different protection.
#
# `router` — /health and /ready — is unlimited: the deployment's own monitoring
# polls it on a timer, and rate-limiting it makes the first symptom of heavy
# client traffic a red health check, which inverts the signal.
#
# `version_router` — /api/version — is rate-limited. It is unauthenticated and
# under the public namespace, so it is reachable by anyone; being cheap is not
# the same as being free.
router = APIRouter()
version_router = APIRouter()


# The version of `docs/api/codex-bridge.openapi.yaml` this build implements.
# `tests/contract/test_openapi_document.py` asserts it equals the document's
# `info.version`, so the two cannot drift — a client that pins a contract version
# has no other way to tell what the server actually speaks.
API_CONTRACT_VERSION = "1.4.0"

# Namespaces this build serves. `/api/version` reports all of them, which is the
# obligation that keeps it outside the versioned namespace instead of making it a
# versioning hole.
SUPPORTED_API_VERSIONS = ["v1"]

# What the mobile client may rely on in this build. A flag is `true` only when a
# served endpoint honours it — not when a helper module implements it.
#
# The first cut reported cursorPagination, idempotencyKeys and
# optimisticConcurrency as `true` because issue #12 had built the machinery. No
# endpoint used any of it, so a client that trusted the flags and sent
# `Idempotency-Key` or `cursor` got a 404 — exactly the failure the flags exist
# to prevent, and the direct opposite of what the same delivery says in the
# contract's `x-pending-components` ("a client must not build against these").
# `tests/integration/test_probes.py` binds these to the served route table.
CAPABILITIES = {
    "errorEnvelope": True,       # every /api response, including these probes
    "cursorPagination": True,    # GET /api/v1/sessions
    "idempotencyKeys": True,     # POST /api/v1/sessions/{id}/stop
    "optimisticConcurrency": True,  # If-Match on the same write
    "passwordSignIn": True,      # POST /api/v1/auth/sign-in
    "tokenRefresh": True,        # POST /api/v1/auth/refresh
    "tokenRevocation": True,     # POST /api/v1/auth/revoke
    "effectivePermissions": True,  # GET /api/v1/auth/me
    "deviceAuthorization": False,  # RFC 8628; sign-in is what #4 delivered
    "eventStream": False,        # issue #13
    "artifactDownloads": False,  # issue #11
}


def _now() -> str:
    return timestamps.now_z()


# Last readiness probe result, reused for `settings.ready_cache_seconds`.
# `/ready` is unauthenticated and unlimited, and each uncached call took a
# connection from the same pool that serves the API — 15 concurrent callers
# exhausted it, real requests blocked for the 30s pool timeout, and the resulting
# TimeoutError was reported as `database: unavailable`, so a flood made the
# gateway ask the load balancer to pull it out of rotation and blame the
# database. Caching bounds the cost at one query per interval however hard the
# endpoint is hit.
_cached_database_state: tuple[float, bool] | None = None

# Single-flight. Without it the cache only helps *after* the first probe returns:
# a concurrent burst all misses, all probes, and 50 simultaneous callers took 50
# pool connections — the very exhaustion the cache was added to prevent. With a
# 30s pool timeout the stampede window was 30s wide, not the cache TTL.
_probe_lock = asyncio.Lock()

# A failure is cached briefly, not for the full TTL. Caching `False` for the
# whole interval turns a momentary blip into a guaranteed stretch of 503s asking
# the load balancer to remove a healthy gateway from rotation.
FAILURE_CACHE_SECONDS = 1.0


async def _probe_database() -> bool:
    """Run the query. Separated from the cache so a test can exercise this path.

    The exception is swallowed here rather than propagated: its text carries the
    database host, port and sometimes credentials, and `/ready` is
    unauthenticated. `test_probe_database_swallows_the_driver_error` drives this
    function against a genuinely broken engine — substituting the caller would
    leave the branch that must never leak untested, which is what the first cut
    did while claiming the opposite.
    """
    try:
        async with engine.connect() as connection:
            await connection.execute(text("select 1"))
    except Exception:
        return False
    return True


def _cache_hit(now: float) -> bool | None:
    if _cached_database_state is None:
        return None
    stamped, reachable = _cached_database_state
    ttl = settings.effective_ready_cache_seconds()
    if not reachable:
        # A failure is held for the shorter of the two, never longer than a
        # success. Pinning a blip for longer than the good news asks the load
        # balancer to keep a recovered gateway out of rotation — and with a
        # small configured TTL the fixed constant inverted exactly that way.
        ttl = min(FAILURE_CACHE_SECONDS, ttl)
    return reachable if now - stamped < ttl else None


async def database_reachable(now: float | None = None) -> bool:
    """Cached, single-flight readiness of the database.

    `now` is for tests, which need a controllable clock. In production it is
    None and every timestamp is read at the moment it is used — which matters
    twice here, because a probe can take as long as the pool timeout:

    - the re-check **inside** the lock must use the current time, not the
      caller's arrival time. Re-using the arrival time made a caller that
      waited 30s accept nothing and probe again, so the single-flight the lock
      exists for did not hold;
    - the cache entry must be stamped **after** the probe. Stamping with the
      arrival time wrote an entry already past its TTL whenever the probe was
      slower than the TTL — the cache suppressed nothing in exactly the slow
      database condition it was added for.
    """
    global _cached_database_state
    fixed_clock = now is not None

    cached = _cache_hit(now if fixed_clock else time.monotonic())
    if cached is not None:
        return cached

    async with _probe_lock:
        cached = _cache_hit(now if fixed_clock else time.monotonic())
        if cached is not None:
            return cached
        reachable = await _probe_database()
        _cached_database_state = (now if fixed_clock else time.monotonic(), reachable)
        return reachable


def reset_database_cache() -> None:
    """Drop the cached result. For tests and for a deliberate re-probe."""
    global _cached_database_state
    _cached_database_state = None


@router.get("/health", tags=["probes"])
async def health() -> dict:
    """Liveness. Deliberately touches nothing — see the module docstring."""
    return {"status": "ok", "time": _now()}


@router.get("/ready", tags=["probes"])
async def ready(response: Response) -> dict:
    """Readiness, with the reason when it is not ready.

    Reports per-dependency checks rather than a bare boolean: "not ready" without
    naming which dependency is missing sends an operator to read logs to learn
    something the probe already knew.
    """
    checks: list[dict] = [
        {
            "name": "database",
            "status": "ok" if await database_reachable() else "unavailable",
            "required": True,
        }
    ]

    if settings.ready_expose_executor_state:
        # Off by default. The boolean is a presence signal about the operator's
        # own machines: pollable anonymously, it charts when they are online.
        from gateway.app.main import hub  # imported late: main imports this router

        checks.append(
            {
                "name": "executors",
                "status": "ok" if hub.connections else "degraded",
                "required": False,
            }
        )

    blocking = [check for check in checks if check["required"] and check["status"] != "ok"]
    if blocking:
        response.status_code = 503
        response.headers["Retry-After"] = "5"
        body = error_body(
            code=DEPENDENCY_UNAVAILABLE,
            message="A required dependency is unavailable.",
            details=[{"field": check["name"], "code": "unavailable", "message": "Dependency is not reachable."} for check in blocking],
        )
        body["checks"] = checks
        return body

    degraded = any(check["status"] != "ok" for check in checks)
    return {
        "status": "degraded" if degraded else "ready",
        "time": _now(),
        "checks": checks,
    }


@version_router.get("/api/version", tags=["probes"])
async def api_version() -> dict:
    """What this server speaks, so a client can refuse before it starts.

    Lives outside `/api/v1` because its job is to tell a client which namespaces
    exist *before* the client commits to one — a question it cannot ask from
    inside a namespace. It therefore reports every namespace served, not the one
    it is nested in.
    """
    body = {
        "application": settings.app_name,
        "applicationVersion": settings.app_version,
        "apiVersions": SUPPORTED_API_VERSIONS,
        "contractVersion": API_CONTRACT_VERSION,
        "capabilities": CAPABILITIES,
        "time": _now(),
    }
    if settings.build_revision:
        body["buildRevision"] = settings.build_revision
    return body
