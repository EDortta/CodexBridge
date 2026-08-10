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


def _trusted_networks() -> list:
    """Configured proxy addresses/CIDRs, parsed once per call site."""
    raw = settings.api_trusted_proxies
    if not raw:
        return []
    networks = []
    for item in raw.split(","):
        item = item.strip()
        if not item:
            continue
        try:
            networks.append(ipaddress.ip_network(item, strict=False))
        except ValueError:
            logging.getLogger(__name__).warning(
                "ignoring unparseable entry in api_trusted_proxies: %r",
                item,
                extra={"correlation_id": None, "task_id": None, "executor_id": None},
            )
    return networks


def _is_trusted(value: str, networks: list) -> bool:
    try:
        address = ipaddress.ip_address(value)
    except ValueError:
        return False
    return any(address in network for network in networks)


def client_key(request: Request) -> str:
    """Bucket identity for a request.

    Uses the authenticated actor when there is one. Otherwise the caller's
    address has to be recovered from `X-Forwarded-For`, and the hard part is
    deciding **which entry** is the client rather than a proxy.

    A fixed hop count cannot do it here, because this deployment has two ingress
    paths of different lengths:

    - direct: client → (8443 published to nginx's internal 443) → gateway. The
      port publish is NAT and appends nothing, so the header holds one entry;
    - via dom1: client → dom1 nginx → Incus edge proxy → frida nginx → gateway,
      which appends two more.

    One number is therefore wrong for one of the paths, whichever number is
    chosen. So the rule is not "how many" but "which are ours": walk the header
    from the right and take the first entry that is **not** a configured proxy.
    That is correct for a chain of any length.

    Two guards, both deliberately pessimistic:

    - the immediate peer must itself be a trusted proxy, or the header is
      ignored entirely. Otherwise anyone who reaches the gateway directly — it
      binds `0.0.0.0` — writes their own identity;
    - anything unresolvable (no trusted proxies configured, a non-address entry
      where the client should be, every entry trusted) falls back to one shared
      bucket. A caller who scrambles the header is throttled alongside every
      other scrambler instead of escaping the limit.
    """
    principal = getattr(request.state, "principal", None)
    actor = getattr(principal, "user_id", None)
    if actor:
        return f"actor:{actor}"

    peer = request.client.host if request.client else None
    forwarded = request.headers.get("X-Forwarded-For")

    networks = _trusted_networks()

    if not forwarded:
        # Behind a trusted proxy with no usable header, the peer address is the
        # proxy's — keying on it is the same "everyone in one bucket" collapse
        # this function exists to avoid, so it is refused rather than used.
        if peer and _is_trusted(peer, networks):
            return SHARED_BUCKET
        normalized = _normalized_address(peer) if peer else None
        return f"ip:{normalized}" if normalized else SHARED_BUCKET

    if not networks:
        _warn_unconfigured()
        return SHARED_BUCKET

    if not (peer and _is_trusted(peer, networks)):
        # The header arrived from something that is not one of our proxies, so
        # nothing in it is evidence about anything.
        return SHARED_BUCKET

    for entry in reversed([part.strip() for part in forwarded.split(",")]):
        if _is_trusted(entry, networks):
            continue
        normalized = _normalized_address(entry)
        return f"ip:{normalized}" if normalized else SHARED_BUCKET

    # Every entry was one of our own proxies: no client address to key on.
    return SHARED_BUCKET


def _normalized_address(value: str) -> str | None:
    """Canonical text form of an IP address, or None if it is not one.

    Normalized so two spellings of one host cannot become two buckets:
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
        "api_trusted_proxies is unset while X-Forwarded-For is present; every "
        "anonymous caller shares one rate-limit bucket. Set it to the addresses "
        "of the proxies in front of this process.",
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
