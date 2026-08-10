"""The limiter's key space must be bounded, or it becomes the resource exhausted.

Buckets are keyed by client address. A caller holding a routed IPv6 /64 — a
standard residential or VPS allocation — mints a fresh key per request: the
limit never fires, and every key stays forever, because trimming a window
empties its deque without removing the entry. Unauthenticated traffic then grows
the process until the unit's MemoryMax kills it, with Restart=always flapping.
"""

from __future__ import annotations

import pytest

from gateway.app.core.rate_limit import MemoryRateLimiter


async def test_a_fresh_key_per_request_does_not_grow_without_bound() -> None:
    limiter = MemoryRateLimiter(limit=5, window_seconds=60, max_keys=200)
    for index in range(5_000):
        assert await limiter.allow(f"ip:2001:db8::{index:x}") is True
    assert limiter.tracked_keys() <= limiter.max_keys, (
        f"{limiter.tracked_keys()} buckets retained for 5000 distinct callers"
    )


async def test_idle_buckets_are_dropped() -> None:
    """A window that emptied leaves an entry behind unless something removes it."""
    limiter = MemoryRateLimiter(limit=5, window_seconds=0, max_keys=10_000)
    for index in range(MemoryRateLimiter.SWEEP_EVERY + 10):
        await limiter.allow(f"ip:10.0.0.{index % 250}")
    assert limiter.tracked_keys() < 260


async def test_an_honest_caller_is_still_limited_while_the_table_churns() -> None:
    """Eviction must not become a way to escape the limit."""
    limiter = MemoryRateLimiter(limit=3, window_seconds=60, max_keys=50)
    for _ in range(3):
        assert await limiter.allow("ip:203.0.113.5") is True
    for index in range(500):
        await limiter.allow(f"ip:2001:db8::{index:x}")
    assert await limiter.allow("ip:203.0.113.5") is False, (
        "the caller being limited was evicted by the caller filling the table"
    )


async def test_the_limit_still_fires_for_a_single_key() -> None:
    limiter = MemoryRateLimiter(limit=2, window_seconds=60)
    assert await limiter.allow("ip:1.2.3.4") is True
    assert await limiter.allow("ip:1.2.3.4") is True
    assert await limiter.allow("ip:1.2.3.4") is False
