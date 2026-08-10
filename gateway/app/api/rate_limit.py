"""Rate limiting for the contract surface.

Implemented as a FastAPI **dependency**, not as middleware, and the reason is
mechanical: `app.exception_handler` handlers are invoked by Starlette's
`ExceptionMiddleware`, which sits *inside* every user middleware. An `ApiError`
raised from a middleware is never seen by them, so a middleware-based limiter
would answer 429 with a bare framework response instead of the `Error` envelope
the contract promises — and without a `requestId`.

`/health` and `/ready` are deliberately **not** limited. They are probed on a
timer by the deployment's own monitoring; rate-limiting them means the first
symptom of heavy client traffic is the operator's health check going red, which
inverts the signal. `/ready` is protected from abuse by caching instead — see
`gateway/app/api/routes/probes.py`.
"""

from __future__ import annotations

import ipaddress
import logging

from fastapi import Request

from gateway.app.api.errors import RATE_LIMITED, ApiError
from gateway.app.core.config import settings
from gateway.app.core.rate_limit import MemoryRateLimiter


RETRY_AFTER_HEADER = "Retry-After"

SHARED_BUCKET = "ip:shared-untrusted"


def client_key(request: Request) -> str:
    """Bucket identity for a request.

    Uses the authenticated actor when there is one. Otherwise it has to find the
    caller's address in `X-Forwarded-For`, and *which element* is correct depends
    on how many entries the proxies append. Getting it wrong breaks the limiter
    in one of two ways, and this deployment has hit both:

    - too **low** (trusting the first element): the client authors it, so any
      caller picks a fresh bucket by sending a header, and nothing is limited;
    - too **high** (trusting the last element): every element the client did not
      author is a proxy address, so every caller collapses into one bucket and a
      single abuser locks out everybody. That was the first cut.

    So the position is configuration: `api_trusted_proxy_hops` is the number of
    entries appended **after** the one naming the client, and the caller is that
    many positions from the end.

    Do not derive it by counting proxies. The first proxy in a chain *records*
    the client rather than adding a hop beyond it, and whether a given vhost is
    in the path at all depends on what is installed. The reliable way is to read
    one real `X-Forwarded-For` as this process receives it and count:

        hops = (number of entries in the received header) - 1

    Unconfigured is not a guess. With `api_trusted_proxy_hops` unset and a
    forwarded header present, every anonymous caller shares one bucket and a
    warning is logged once — throttled but never keyed on a proxy address or on
    client-controlled bytes. Anything that does not parse as an IP address falls
    back the same way. That is deliberately the pessimistic direction: a caller
    who scrambles the header is throttled alongside every other scrambler
    instead of escaping the limit.
    """
    principal = getattr(request.state, "principal", None)
    actor = getattr(principal, "user_id", None)
    if actor:
        return f"actor:{actor}"

    hops = settings.api_trusted_proxy_hops
    forwarded = request.headers.get("X-Forwarded-For")

    if forwarded:
        if hops is None:
            _warn_unconfigured()
            return SHARED_BUCKET
        parts = [part.strip() for part in forwarded.split(",")]
        index = len(parts) - 1 - max(0, int(hops))
        if 0 <= index < len(parts):
            normalized = _normalized_address(parts[index])
            if normalized:
                return f"ip:{normalized}"
        return SHARED_BUCKET

    if hops:
        # Configured to sit behind proxies, yet no header arrived: either the
        # proxy is misconfigured or this request bypassed it. Neither is a
        # reason to trust the peer address as a per-client identity.
        return SHARED_BUCKET

    peer = request.client.host if request.client else None
    normalized = _normalized_address(peer) if peer else None
    return f"ip:{normalized}" if normalized else SHARED_BUCKET


def _normalized_address(value: str) -> str | None:
    """Canonical text form of an IP address, or None if it is not one.

    Normalized so that two spellings of one host cannot become two buckets:
    `2001:DB8::1`, `2001:0db8:0000:0000:0000:0000:0000:0001` and `2001:db8::1`
    are the same client, and a bucket that splits on spelling is a bucket an
    attacker can multiply.
    """
    try:
        return str(ipaddress.ip_address(value))
    except ValueError:
        return None


_warned_unconfigured = False


def _warn_unconfigured() -> None:
    """Say once that the limiter is degraded, rather than failing silently."""
    global _warned_unconfigured
    if _warned_unconfigured:
        return
    _warned_unconfigured = True
    logging.getLogger(__name__).warning(
        "api_trusted_proxy_hops is unset while X-Forwarded-For is present; every "
        "anonymous caller shares one rate-limit bucket. Set it to "
        "(number of entries in the received X-Forwarded-For) - 1.",
        extra={"correlation_id": None, "task_id": None, "executor_id": None},
    )


class RateLimitDependency:
    """Refuse a request that exceeds the window, in the contract's own shape."""

    def __init__(self, limiter: MemoryRateLimiter) -> None:
        self.limiter = limiter

    async def __call__(self, request: Request) -> None:
        if await self.limiter.allow(client_key(request)):
            return
        raise ApiError(
            status_code=429,
            code=RATE_LIMITED,
            message="Too many requests. Retry after the interval in Retry-After.",
            headers={RETRY_AFTER_HEADER: str(self.limiter.window_seconds)},
        )
