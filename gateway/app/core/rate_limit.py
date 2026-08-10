from __future__ import annotations

import asyncio
import time
from collections import deque


class MemoryRateLimiter:
    """Sliding-window limiter with a bounded key space.

    The bound is not housekeeping. Buckets are keyed by client address, so an
    attacker holding a routed IPv6 /64 — a standard residential or VPS
    allocation — can mint a fresh key per request: the limit never fires, and
    every key stays forever because trimming a window empties its deque without
    removing the entry. Unauthenticated traffic then grows the process until the
    unit's MemoryMax kills it, and `Restart=always` flaps. The limiter itself
    becomes the resource being exhausted.

    So idle buckets are dropped, and the key space is capped: over the cap, the
    least recently seen buckets go first. Evicting a bucket forgives its
    history, which is the safe direction — the alternative is refusing service
    to everyone because one caller filled the table.

    Single-process. `deploy/systemd/codex-bridge-gateway.service` starts one
    uvicorn worker; adding `--workers N` would multiply every effective limit by
    N, because each worker keeps its own dict.
    """

    #: Buckets retained before eviction starts. 50k addresses is far more than
    #: this deployment ever sees and still bounds memory at a few MB.
    MAX_KEYS = 50_000

    #: Requests between sweeps. Sweeping on every call is O(keys) per request;
    #: sweeping never is how the table grows without bound.
    SWEEP_EVERY = 1_000

    def __init__(self, limit: int, window_seconds: int, max_keys: int | None = None):
        self.limit = limit
        self.window_seconds = window_seconds
        self.max_keys = max_keys or self.MAX_KEYS
        self._events: dict[str, deque[float]] = {}
        self._lock = asyncio.Lock()
        self._since_sweep = 0

    async def allow(self, key: str) -> bool:
        now = time.monotonic()
        async with self._lock:
            bucket = self._events.setdefault(key, deque())
            cutoff = now - self.window_seconds
            while bucket and bucket[0] < cutoff:
                bucket.popleft()

            self._since_sweep += 1
            if self._since_sweep >= self.SWEEP_EVERY or len(self._events) > self.max_keys:
                self._sweep(cutoff, protect=key)

            if len(bucket) >= self.limit:
                return False
            bucket.append(now)
            return True

    def _sweep(self, cutoff: float, *, protect: str) -> None:
        """Drop idle buckets, then evict the oldest until under the cap."""
        self._since_sweep = 0
        for key in [k for k, events in self._events.items() if not events and k != protect]:
            del self._events[key]

        overflow = len(self._events) - self.max_keys
        if overflow <= 0:
            return
        # Buckets AT the limit are evicted last. Ranking purely by "least
        # recently seen" evicts the honest caller that is currently being
        # throttled — it was seen earliest — so flooding the table with fresh
        # keys became a way to clear somebody else's history. A bucket that is
        # doing the limiter's work is the most expensive one to forget.
        ranked = sorted(
            (k for k in self._events if k != protect),
            key=lambda k: (
                len(self._events[k]) >= self.limit,
                self._events[k][-1] if self._events[k] else float("-inf"),
            ),
        )
        for key in ranked[:overflow]:
            del self._events[key]

    def tracked_keys(self) -> int:
        """Bucket count, for tests and diagnostics."""
        return len(self._events)
