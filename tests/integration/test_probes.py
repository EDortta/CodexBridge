"""Health, readiness and version — issue #3.

The states worth testing are not "works / doesn't". They are the three the
endpoints exist to distinguish: **healthy**, **degraded** (serving, but something
non-required is missing) and **unavailable** (a required dependency is down).
Collapsing degraded into unavailable takes the API offline exactly when an
operator needs it to see why nothing is executing.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from gateway.app.api.request_context import REQUEST_ID_HEADER
from gateway.app.api.routes import probes


class _BrokenEngine:
    """Stands in for the AsyncEngine so `connect` can be made to fail.

    `AsyncEngine.connect` is a read-only attribute and cannot be monkeypatched,
    which is why the unavailable branch went untested behind a stub of its
    caller — the very branch that must never leak a connection string.
    """

    def __init__(self, on_connect) -> None:
        self._on_connect = on_connect

    def connect(self, *args, **kwargs):
        return self._on_connect(*args, **kwargs)


@pytest.fixture(autouse=True)
def _clear_readiness_cache():
    probes.reset_database_cache()
    yield
    probes.reset_database_cache()


@pytest.fixture
def client() -> TestClient:
    from gateway.app.main import app

    return TestClient(app, raise_server_exceptions=False)


# --------------------------------------------------------------------------
# Liveness
# --------------------------------------------------------------------------


def test_health_is_ok_and_carries_a_request_id(client: TestClient) -> None:
    response = client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["time"].endswith("Z")
    assert response.headers[REQUEST_ID_HEADER]


def test_health_needs_no_authentication(client: TestClient) -> None:
    """A probe that needs a credential cannot be used before authenticating."""
    response = client.get("/health")
    assert response.status_code == 200
    assert "WWW-Authenticate" not in response.headers


def test_health_touches_no_dependency(client: TestClient, monkeypatch) -> None:
    """Liveness must not depend on a dependency.

    A liveness probe that queries the database restarts a perfectly healthy
    process because the database blinked — turning a brief outage into a restart
    loop.

    Asserted by breaking the *engine*, not by stubbing the readiness helper:
    stubbing the helper only proves `health()` does not call that one function,
    and would stay green if it opened a connection directly.
    """
    opened: list[str] = []

    def forbid_connect(*args, **kwargs):
        opened.append("connect")
        raise RuntimeError("database is gone")

    monkeypatch.setattr(probes, "engine", _BrokenEngine(forbid_connect))
    probes.reset_database_cache()

    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert opened == [], "liveness opened a database connection"


# --------------------------------------------------------------------------
# Readiness: healthy, degraded, unavailable
# --------------------------------------------------------------------------


def _check(body: dict, name: str) -> dict:
    return next(check for check in body["checks"] if check["name"] == name)


def test_ready_does_not_disclose_executor_presence_by_default(client: TestClient) -> None:
    """The boolean charts when the operator's machines are online.

    `/ready` is unauthenticated and pollable, and `/metrics` is already
    restricted to localhost at the proxy — so the safe default here is not to
    answer the question at all.
    """
    body = client.get("/ready").json()
    assert body["status"] == "ready"
    assert [check["name"] for check in body["checks"]] == ["database"]
    assert "executor" not in response_text(client, "/ready").lower()


def response_text(client: TestClient, path: str) -> str:
    return client.get(path).text


def test_ready_reports_degraded_when_executor_state_is_exposed(client: TestClient, monkeypatch) -> None:
    """With the setting on, degraded is still 200: reads work, traffic flows.

    Returning 503 here would take the API offline exactly when an operator needs
    it to see why nothing is executing.
    """
    from gateway.app.core.config import settings

    monkeypatch.setattr(settings, "ready_expose_executor_state", True)
    response = client.get("/ready")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "degraded"
    assert _check(body, "database")["status"] == "ok"
    assert _check(body, "executors")["status"] == "degraded"
    assert _check(body, "executors")["required"] is False


def test_ready_is_ready_when_an_executor_is_connected(client: TestClient, monkeypatch) -> None:
    from gateway.app.core.config import settings
    from gateway.app.main import hub

    monkeypatch.setattr(settings, "ready_expose_executor_state", True)
    hub.connections["E1"] = object()  # type: ignore[assignment]
    try:
        body = client.get("/ready").json()
    finally:
        hub.connections.pop("E1", None)
    assert body["status"] == "ready"
    assert all(check["status"] == "ok" for check in body["checks"])


def test_ready_is_503_when_the_database_is_unavailable(client: TestClient, monkeypatch) -> None:
    async def unreachable() -> bool:
        return False

    monkeypatch.setattr(probes, "database_reachable", unreachable)
    response = client.get("/ready")

    assert response.status_code == 503
    body = response.json()
    assert body["code"] == "dependency_unavailable"
    assert body["retryable"] is True
    assert body["requestId"]
    assert response.headers["Retry-After"] == "5"
    assert _check(body, "database")["status"] == "unavailable"
    assert body["details"][0]["field"] == "database"


async def test_probe_database_swallows_the_driver_error(monkeypatch) -> None:
    """The branch that must never leak, driven for real.

    The first version of this test replaced `database_reachable` wholesale and
    asserted that four invented constants were absent — strings the code could
    never emit, so it could not fail. This drives `_probe_database` against an
    engine that raises with a credential-bearing message and asserts the function
    reports `False` without re-raising, which is what keeps the text out of the
    response.
    """
    message = "connection to server at 10.0.0.5 port 5432 failed: password 'hunter2' rejected"

    def explode(*args, **kwargs):
        raise RuntimeError(message)

    monkeypatch.setattr(probes, "engine", _BrokenEngine(explode))
    assert await probes._probe_database() is False


def test_unavailable_ready_body_contains_no_driver_text(client: TestClient, monkeypatch) -> None:
    """And the response built from that `False` carries none of it."""
    message = "connection to server at 10.0.0.5 port 5432 failed: password 'hunter2' rejected"

    def explode(*args, **kwargs):
        raise RuntimeError(message)

    monkeypatch.setattr(probes, "engine", _BrokenEngine(explode))
    probes.reset_database_cache()
    serialized = client.get("/ready").text
    probes.reset_database_cache()

    for fragment in ("10.0.0.5", "5432", "hunter2", "password", "connection to server"):
        assert fragment not in serialized


# --------------------------------------------------------------------------
# Version
# --------------------------------------------------------------------------


def test_api_version_reports_every_namespace_it_serves(client: TestClient) -> None:
    """It sits outside /api/v1 precisely so it can answer for all namespaces."""
    body = client.get("/api/version").json()
    assert body["apiVersions"] == ["v1"]
    assert body["contractVersion"] == probes.API_CONTRACT_VERSION
    assert body["application"]
    assert body["applicationVersion"]
    assert body["time"].endswith("Z")


def _collect_params(dependant, query: set, header: set) -> None:
    """Walk a dependant and everything it depends on.

    Reading only the endpoint function's own parameters made the gate fire
    backwards: an `Idempotency-Key` declared in a shared dependency — the
    natural shape, since the helpers live in their own modules — would be
    invisible, so the way to make the suite green would be to keep advertising
    `false` for a capability the server does honour.
    """
    query |= {param.alias.lower() for param in dependant.query_params}
    header |= {param.alias.lower() for param in dependant.header_params}
    for sub in dependant.dependencies:
        _collect_params(sub, query, header)


def _api_route_signals() -> dict[str, bool]:
    """What the served `/api` routes actually accept.

    Derived from FastAPI's resolved dependants rather than from a hand-kept
    list: a capability flag is a promise about request handling, so the evidence
    has to come from the handlers.
    """
    from gateway.app.main import app

    query_names: set[str] = set()
    header_names: set[str] = set()
    paths: set[str] = set()
    for route in app.routes:
        path = str(getattr(route, "path", ""))
        if not (path == "/api" or path.startswith("/api/")):
            continue
        paths.add(path)
        dependant = getattr(route, "dependant", None)
        if dependant is not None:
            _collect_params(dependant, query_names, header_names)

    return {
        "cursorPagination": "cursor" in query_names,
        "idempotencyKeys": "idempotency-key" in header_names,
        "optimisticConcurrency": "if-match" in header_names,
        # Route-shaped capabilities: nothing to declare on a signature, so the
        # evidence is whether a route exists to serve them at all.
        "eventStream": any("/events" in path or "/stream" in path for path in paths),
        "artifactDownloads": any("/artifacts" in path or "/builds" in path for path in paths),
    }


def test_capability_flags_match_what_the_served_routes_accept(client: TestClient) -> None:
    """A `true` flag a client acts on must not produce a 404 or be ignored.

    The first cut reported `cursorPagination`, `idempotencyKeys` and
    `optimisticConcurrency` as true because issue #12 built the machinery — while
    no endpoint used any of it, so a client that trusted them and sent
    `Idempotency-Key` got a 404. That is exactly the failure the flags exist to
    prevent.

    The first *fix* was worse in a quiet way: it only checked while no `/api/v1`
    route existed, so the guard went silent the moment it started to matter.
    This one is unconditional, reads the handlers including their dependencies,
    and covers every flag that describes a request-facing feature.
    """
    capabilities = client.get("/api/version").json()["capabilities"]
    assert all(isinstance(value, bool) for value in capabilities.values())

    signals = _api_route_signals()
    unbound = set(capabilities) - set(signals) - {"errorEnvelope"}
    assert not unbound, (
        f"capability flags nothing can verify: {sorted(unbound)}. Every flag needs "
        "an observable signal, or it is a promise with no artifact behind it."
    )

    for flag, served in signals.items():
        assert capabilities[flag] is served, (
            f"{flag} is advertised as {capabilities[flag]} but the served /api routes "
            f"say {served}; a client acting on it is misled"
        )


def test_error_envelope_capability_is_demonstrated_not_asserted(client: TestClient) -> None:
    """`errorEnvelope: true` is the one flag with no request signature.

    Asserting it against the constant it was read from can never fail, so it is
    demonstrated instead: make a contract path fail and check the shape.
    """
    assert client.get("/api/version").json()["capabilities"]["errorEnvelope"] is True
    body = client.get("/api/v1/definitely-not-a-route").json()
    assert {"code", "message", "requestId", "retryable"} <= body.keys()


def test_api_version_omits_build_revision_when_the_deployment_injected_none(client: TestClient) -> None:
    """Absence means "not reported", never "no build" — so no empty string."""
    body = client.get("/api/version").json()
    assert "buildRevision" not in body or body["buildRevision"]


def test_api_version_reports_build_revision_when_set(client: TestClient, monkeypatch) -> None:
    from gateway.app.core.config import settings

    monkeypatch.setattr(settings, "build_revision", "b76a391")
    assert client.get("/api/version").json()["buildRevision"] == "b76a391"


def test_probe_responses_carry_no_infrastructure_detail(client: TestClient) -> None:
    """The acceptance criterion "no sensitive infrastructure details", asserted."""
    from gateway.app.core.config import settings

    bodies = " ".join(client.get(path).text for path in ("/health", "/ready", "/api/version"))
    for forbidden in (settings.database_url, settings.registry_file, settings.user_registry_file):
        assert forbidden not in bodies


# --------------------------------------------------------------------------
# Rate limiting
# --------------------------------------------------------------------------


def test_api_version_is_rate_limited_with_the_contract_shape(monkeypatch) -> None:
    """The contract documents 429 + Retry-After; before this it documented only."""
    from gateway.app.main import app, rate_limiter

    monkeypatch.setattr(rate_limiter, "limit", 2)
    rate_limiter._events.clear()

    with TestClient(app, raise_server_exceptions=False) as limited:
        assert limited.get("/api/version").status_code == 200
        assert limited.get("/api/version").status_code == 200
        response = limited.get("/api/version")

    assert response.status_code == 429
    body = response.json()
    assert body["code"] == "rate_limited"
    assert body["retryable"] is True
    assert body["requestId"]
    assert response.headers["Retry-After"] == str(rate_limiter.window_seconds)
    rate_limiter._events.clear()


def test_health_and_ready_are_never_rate_limited(monkeypatch) -> None:
    """Monitoring polls these on a timer.

    Limiting them makes the first symptom of heavy client traffic a red health
    check, which points the operator at the wrong thing.
    """
    from gateway.app.main import app, rate_limiter

    monkeypatch.setattr(rate_limiter, "limit", 1)
    rate_limiter._events.clear()

    with TestClient(app, raise_server_exceptions=False) as probe_client:
        for _ in range(5):
            assert probe_client.get("/health").status_code == 200
            assert probe_client.get("/ready").status_code in (200, 503)
    rate_limiter._events.clear()


def _request_with(header: str | None = None, peer: str = "10.0.0.9"):
    from starlette.requests import Request

    headers = [(b"x-forwarded-for", header.encode())] if header is not None else []
    return Request({"type": "http", "headers": headers, "client": (peer, 1234)})


TRUSTED = "127.0.0.1,192.168.71.0/24"

# The two real ingress paths, as docs/architecture.md describes them.
DIRECT_CHAIN = "198.51.100.7"                                  # 8443 -> nginx 443 -> gateway
DOM1_CHAIN = "198.51.100.7, 192.168.71.10, 127.0.0.1"          # dom1 -> edge proxy -> nginx


def test_the_caller_is_found_on_both_ingress_paths(monkeypatch) -> None:
    """A fixed hop count cannot be right for both, so the rule is "which are ours".

    Direct, the port publish is NAT and appends nothing, so the header holds one
    entry. Via dom1 it holds three. Walking from the right past the configured
    proxies finds the client in either case.
    """
    from gateway.app.api.rate_limit import client_key
    from gateway.app.core.config import settings

    monkeypatch.setattr(settings, "api_trusted_proxies", TRUSTED)
    assert client_key(_request_with(DIRECT_CHAIN, peer="127.0.0.1")) == "ip:198.51.100.7"
    assert client_key(_request_with(DOM1_CHAIN, peer="127.0.0.1")) == "ip:198.51.100.7"


def test_two_clients_do_not_share_a_bucket(monkeypatch) -> None:
    """The round-1 defect: one abuser exhausting the window for everybody."""
    from gateway.app.api.rate_limit import client_key
    from gateway.app.core.config import settings

    monkeypatch.setattr(settings, "api_trusted_proxies", TRUSTED)
    a = client_key(_request_with("203.0.113.5, 192.168.71.10, 127.0.0.1", peer="127.0.0.1"))
    b = client_key(_request_with("198.51.100.9, 192.168.71.10, 127.0.0.1", peer="127.0.0.1"))
    assert a != b
    assert {a, b} == {"ip:203.0.113.5", "ip:198.51.100.9"}


def test_a_client_cannot_forge_an_extra_hop(monkeypatch) -> None:
    """Prepending junk must not move the caller off its own bucket.

    Whatever the client writes ends up to the LEFT of what the proxies append,
    so walking from the right reaches the proxy-recorded address first.
    """
    from gateway.app.api.rate_limit import client_key
    from gateway.app.core.config import settings

    monkeypatch.setattr(settings, "api_trusted_proxies", TRUSTED)
    keys = {
        client_key(_request_with(f"{spoof}, 198.51.100.7, 192.168.71.10, 127.0.0.1", peer="127.0.0.1"))
        for spoof in ("1.1.1.1", "2.2.2.2", "3.3.3.3")
    }
    assert keys == {"ip:198.51.100.7"}


def test_header_from_an_untrusted_peer_is_ignored(monkeypatch) -> None:
    """The gateway binds 0.0.0.0, so anything on the LAN can reach it directly.

    Honouring a forwarded header from a peer that is not one of our proxies
    would let that caller write its own identity.
    """
    from gateway.app.api.rate_limit import SHARED_BUCKET, client_key
    from gateway.app.core.config import settings

    monkeypatch.setattr(settings, "api_trusted_proxies", TRUSTED)
    assert client_key(_request_with(DOM1_CHAIN, peer="10.9.9.9")) == SHARED_BUCKET


def test_unconfigured_trusted_proxies_ignores_the_header(monkeypatch) -> None:
    """A wrong value is worse than none, so none must be safe rather than a guess."""
    from gateway.app.api.rate_limit import SHARED_BUCKET, client_key
    from gateway.app.core.config import settings

    monkeypatch.setattr(settings, "api_trusted_proxies", None)
    assert client_key(_request_with(DOM1_CHAIN, peer="127.0.0.1")) == SHARED_BUCKET


@pytest.mark.parametrize(
    "header",
    [
        "not-an-ip, 192.168.71.10, 127.0.0.1",   # client slot is not an address
        ", 192.168.71.10, 127.0.0.1",            # client slot is empty
        " , 192.168.71.10, 127.0.0.1",           # client slot is whitespace
        "192.168.71.10, 127.0.0.1",              # every entry is one of ours
        "",                                       # present and empty
        "   ",                                    # present and blank
    ],
)
def test_unresolvable_forwarded_for_falls_back_to_one_shared_bucket(header: str, monkeypatch) -> None:
    """A trailing comma once produced the literal bucket `"ip:"` — keyed on nothing."""
    from gateway.app.api.rate_limit import SHARED_BUCKET, client_key
    from gateway.app.core.config import settings

    monkeypatch.setattr(settings, "api_trusted_proxies", TRUSTED)
    key = client_key(_request_with(header, peer="127.0.0.1"))
    assert key == SHARED_BUCKET
    assert key != "ip:"


def test_no_forwarded_header_keys_on_the_peer(monkeypatch) -> None:
    """Direct access, no proxy in the path: the peer IS the client."""
    from gateway.app.api.rate_limit import client_key
    from gateway.app.core.config import settings

    monkeypatch.setattr(settings, "api_trusted_proxies", TRUSTED)
    assert client_key(_request_with(None, peer="10.0.0.9")) == "ip:10.0.0.9"


def test_no_header_from_a_trusted_proxy_is_not_keyed_on_the_proxy(monkeypatch) -> None:
    """Otherwise everyone arriving through that proxy shares its address."""
    from gateway.app.api.rate_limit import SHARED_BUCKET, client_key
    from gateway.app.core.config import settings

    monkeypatch.setattr(settings, "api_trusted_proxies", TRUSTED)
    assert client_key(_request_with(None, peer="127.0.0.1")) == SHARED_BUCKET


def test_addresses_are_normalized_so_spellings_do_not_split_buckets(monkeypatch) -> None:
    """A bucket that splits on spelling is a bucket an attacker can multiply."""
    from gateway.app.api.rate_limit import client_key
    from gateway.app.core.config import settings

    monkeypatch.setattr(settings, "api_trusted_proxies", TRUSTED)
    keys = {
        client_key(_request_with(f"{spelling}, 127.0.0.1", peer="127.0.0.1"))
        for spelling in ("2001:db8::1", "2001:DB8::1", "2001:0db8:0000:0000:0000:0000:0000:0001")
    }
    assert len(keys) == 1, f"one host produced {len(keys)} buckets: {keys}"


def test_ready_is_cached_so_a_flood_cannot_drain_the_connection_pool(monkeypatch) -> None:
    """`/ready` is unauthenticated and unlimited, and shares the API's pool.

    Uncached, enough concurrent callers exhausted it, real requests blocked for
    the pool timeout, and the resulting error was reported as
    `database: unavailable` — so a flood made the gateway ask the load balancer
    to pull it out of rotation, blaming the database.
    """
    from gateway.app.core.config import settings
    from gateway.app.main import app

    probes.reset_database_cache()
    monkeypatch.setattr(settings, "ready_cache_seconds", 60.0)

    probed = {"count": 0}

    async def counting_probe() -> bool:
        probed["count"] += 1
        return True

    monkeypatch.setattr(probes, "_probe_database", counting_probe)

    with TestClient(app, raise_server_exceptions=False) as flood:
        for _ in range(25):
            assert flood.get("/ready").status_code == 200

    assert probed["count"] == 1, f"25 requests issued {probed['count']} database probes"
    probes.reset_database_cache()


async def test_readiness_cache_expires(monkeypatch) -> None:
    """Cached, not frozen: a recovered database must be noticed."""
    probes.reset_database_cache()
    from gateway.app.core.config import settings

    monkeypatch.setattr(settings, "ready_cache_seconds", 5.0)
    # Two entries, not three: the call inside the TTL is served from the cache
    # and must not consume a probe — asserting that is half the point.
    states = iter([True, False])
    probed = {"count": 0}

    async def changing_probe() -> bool:
        probed["count"] += 1
        return next(states)

    monkeypatch.setattr(probes, "_probe_database", changing_probe)

    assert await probes.database_reachable(now=100.0) is True
    assert await probes.database_reachable(now=102.0) is True, "inside the TTL"
    assert probed["count"] == 1, "the cached call re-probed"
    assert await probes.database_reachable(now=110.0) is False, "TTL elapsed, re-probed"
    assert probed["count"] == 2
    probes.reset_database_cache()


async def test_a_failed_probe_is_cached_only_briefly(monkeypatch) -> None:
    """A blip must not pin the gateway out of rotation for the whole TTL.

    Caching `False` for `ready_cache_seconds` turns one momentary failure into a
    guaranteed stretch of 503 + Retry-After asking the load balancer to remove a
    gateway that is already healthy again.
    """
    probes.reset_database_cache()
    from gateway.app.core.config import settings

    monkeypatch.setattr(settings, "ready_cache_seconds", 60.0)
    states = iter([False, True])

    async def recovering_probe() -> bool:
        return next(states)

    monkeypatch.setattr(probes, "_probe_database", recovering_probe)

    assert await probes.database_reachable(now=100.0) is False
    assert await probes.database_reachable(now=100.5) is False, "still inside the failure window"
    assert await probes.database_reachable(now=100.0 + probes.FAILURE_CACHE_SECONDS + 0.1) is True, (
        "a recovered database must be picked up without waiting out the success TTL"
    )
    assert probes.FAILURE_CACHE_SECONDS < settings.ready_cache_seconds
    probes.reset_database_cache()


async def test_a_concurrent_burst_issues_one_probe(monkeypatch) -> None:
    """The cache alone does not help while the first probe is still running.

    50 simultaneous callers all missed the cold cache, all probed, and took 50
    pool connections — the exhaustion the cache was added to prevent. Worse, the
    resulting failure was then cached, so a healthy database was reported down.
    """
    import asyncio

    probes.reset_database_cache()
    from gateway.app.core.config import settings

    monkeypatch.setattr(settings, "ready_cache_seconds", 60.0)
    concurrent = {"now": 0, "peak": 0, "calls": 0}

    async def slow_probe() -> bool:
        concurrent["calls"] += 1
        concurrent["now"] += 1
        concurrent["peak"] = max(concurrent["peak"], concurrent["now"])
        await asyncio.sleep(0.05)
        concurrent["now"] -= 1
        return True

    monkeypatch.setattr(probes, "_probe_database", slow_probe)
    results = await asyncio.gather(*(probes.database_reachable() for _ in range(50)))

    assert all(results)
    assert concurrent["peak"] == 1, f"{concurrent['peak']} probes ran at once"
    assert concurrent["calls"] == 1, f"50 concurrent callers issued {concurrent['calls']} probes"
    probes.reset_database_cache()


def test_zero_cache_seconds_is_floored(monkeypatch) -> None:
    """A TTL of 0 would restore the uncached DoS, so it is not honoured."""
    from gateway.app.core.config import settings

    monkeypatch.setattr(settings, "ready_cache_seconds", 0.0)
    assert settings.effective_ready_cache_seconds() >= 0.5
    monkeypatch.setattr(settings, "ready_cache_seconds", -10.0)
    assert settings.effective_ready_cache_seconds() >= 0.5


def test_every_served_api_route_carries_the_rate_limiter() -> None:
    """`main.py` claimed every future /api route inherits the limiter. It does not.

    `dependencies=` on `include_router` binds to that router's routes only, so a
    route added with `@app.get("/api/v1/...")` further down the module would be
    unlimited. This asserts the claim instead of trusting the comment.
    """
    from gateway.app.api.rate_limit import RateLimitDependency
    from gateway.app.main import app

    unlimited = []
    for route in app.routes:
        path = str(getattr(route, "path", ""))
        if not (path == "/api" or path.startswith("/api/")):
            continue
        dependencies = getattr(route, "dependencies", []) or []
        calls = [getattr(dep, "dependency", None) for dep in dependencies]
        if not any(isinstance(call, RateLimitDependency) for call in calls):
            unlimited.append(path)
    assert not unlimited, f"/api routes served without the rate limiter: {unlimited}"
