"""The browser OAuth form — the *other* caller of the password check.

Issue #4 introduced a constant-cost password verification and wired it into the
mobile sign-in. `POST /oauth/authorize` kept its own hand-rolled
`lookup_user(...) or not verify_password(...)` short-circuit against the same
`users.json`, so the enumeration oracle the new endpoint closed stayed wide open
on the neighbouring one — and that one carries no rate limiter, because only
`/api` routes do.

That is `design-standards.md` §3 / `AGENTS.md` §3 exactly: the guard was placed
at one caller, and the next caller silently lacked it.

Closing that oracle moved a cost rather than removing it: an invented username
went from ~3 ms to a full key derivation, on the one auth route that carried no
attempt ceiling and inside an `async def` that held the event loop while it ran.
The rest of this file is about that consequence — the endpoint now has the
limiter, and the derivation now happens off the loop.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import time

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from gateway.app.db.base import Base
from gateway.app.db.session import get_session
from gateway.app.main import app


PASSWORD = "correct-horse-battery-staple"

# The production cost. A cheap fixture would make both branches fast and the
# test would pass on the unfixed code — it is the *difference* that is the
# defect, and a difference needs a derivation expensive enough to see.
ITERATIONS = 200000

# Concurrent unauthenticated attempts in the event-loop test below. Enough that
# serializing them on the loop is unmistakable, and not so many that the
# threadpool alone saturates the machine — the fix moves the work off the loop,
# it does not make it free.
FLOOD = 6


def _hash(password: str, iterations: int) -> str:
    salt = b"codexbridge-test-salt"
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    encode = lambda raw: base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")  # noqa: E731
    return "$".join(("pbkdf2_sha256", str(iterations), encode(salt), encode(digest)))


def _install_registry(tmp_path, monkeypatch) -> None:
    from gateway.app.core.config import settings

    registry = tmp_path / "users.json"
    registry.write_text(
        json.dumps(
            {
                "users": [
                    {
                        "user_id": "alice",
                        "email": "alice@example.com",
                        "password_hash": _hash(PASSWORD, ITERATIONS),
                        "roles": [],
                        "allowed_projects": ["p1"],
                        "scopes": ["codexbridge.read"],
                        "enabled": True,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(settings, "user_registry_file", str(registry))


async def _install_database():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async def override():
        async with factory() as s:
            yield s

    app.dependency_overrides[get_session] = override
    return engine


@pytest.fixture
async def browser(tmp_path, monkeypatch):
    _install_registry(tmp_path, monkeypatch)
    engine = await _install_database()
    yield TestClient(app, raise_server_exceptions=False)
    app.dependency_overrides.pop(get_session, None)
    await engine.dispose()


@pytest.fixture
async def concurrent_browser(tmp_path, monkeypatch):
    """The same app, driven by a client that can have requests in flight at once.

    `TestClient` runs each call to completion on its own portal, so it cannot
    show what a stalled event loop does to a *concurrent* request — which is the
    whole failure mode here.
    """
    _install_registry(tmp_path, monkeypatch)
    engine = await _install_database()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://gateway") as client:
        yield client
    app.dependency_overrides.pop(get_session, None)
    await engine.dispose()


def _form(username: str, password: str) -> dict:
    return {
        "response_type": "code",
        "client_id": "chatgpt-codexbridge",
        "redirect_uri": "https://chatgpt.com/callback",
        "scope": "codexbridge.read",
        "state": "s",
        "code_challenge": "E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM",
        "code_challenge_method": "S256",
        "username": username,
        "password": password,
    }


def _submit(client: TestClient, username: str, password: str):
    return client.post("/oauth/authorize", data=_form(username, password))


async def test_a_wrong_password_costs_the_same_for_a_real_and_an_invented_account(browser) -> None:
    """Otherwise `/oauth/authorize` enumerates every account in the registry.

    Measured against the unfixed code: ~1.6 ms for an unknown username and
    ~299 ms for a real one — 185x, on the auth route with no rate limiter. Both
    forms answer with the identical re-rendered page, so nothing in the response
    shows it; the clock does.

    A ratio rather than two equal timings, because equal timings are not
    something shared CI hardware can promise.
    """
    _submit(browser, "nobody", "warm the cached decoy")

    started = time.monotonic()
    known = _submit(browser, "alice", "not-the-password")
    known_cost = time.monotonic() - started

    started = time.monotonic()
    unknown = _submit(browser, "no-such-user", "not-the-password")
    unknown_cost = time.monotonic() - started

    assert known.status_code == unknown.status_code == 200
    assert "Invalid username or password." in known.text
    assert "Invalid username or password." in unknown.text

    ratio = known_cost / unknown_cost
    assert 0.4 <= ratio <= 2.5, (
        "a username that exists is answered at a different cost than one that "
        f"does not, which enumerates the registry: {known_cost:.4f}s vs "
        f"{unknown_cost:.4f}s (ratio {ratio:.2f})"
    )


async def test_a_disabled_account_cannot_complete_the_browser_flow(browser) -> None:
    """The short-circuit this replaced also enforced `enabled`; keep it enforced."""
    from gateway.app.core.config import settings

    path = settings.user_registry_file
    registry = json.loads(open(path, encoding="utf-8").read())
    registry["users"][0]["enabled"] = False
    open(path, "w", encoding="utf-8").write(json.dumps(registry))

    response = _submit(browser, "alice", PASSWORD)

    assert response.status_code == 200
    assert "Invalid username or password." in response.text


async def test_a_flood_of_bad_logins_does_not_stall_the_liveness_probe(
    concurrent_browser,
) -> None:
    """A key derivation on the event loop takes the whole process down with it.

    `authenticate` is a few hundred milliseconds of PBKDF2 with no `await` in
    it. Called straight from `async def oauth_authorize_submit`, it holds the
    loop, so every other request in the process waits — including `/health`,
    which a monitor restarts the gateway over. Measured against the synchronous
    call: `/health` went from 0.8 ms idle to 3.3 s under ten unauthenticated
    attempts with invented usernames. No valid credential is needed to cause it,
    which is why it is measured here rather than reasoned about.

    The probe is polled for the whole duration of the flood and the **worst**
    latency is what is asserted on. A single probe raced against the first
    attempt proves nothing: an ASGI request needs a couple of loop iterations to
    reach its handler, so `/health` wins that race even when the loop is about to
    be held for a second. The window is what shows it.

    The bound is derived from a derivation measured on this machine rather than
    written as a millisecond count, because shared CI hardware can promise a
    ratio and not a deadline. It is not tighter than one attempt: the
    derivations still burn every core, and a loop thread *competing* for CPU is
    a different thing from a loop thread *held* by a blocking call. This test is
    about the second, and unfixed it misses by an order of magnitude (816 ms
    against a 200 ms budget), not by a hair.
    """
    from gateway.app.main import rate_limiter

    rate_limiter._events.clear()

    # Warm the cached decoy first: the very first attempt against a registry
    # builds it, which costs a second derivation and would inflate the baseline
    # the budget is computed from.
    await concurrent_browser.post("/oauth/authorize", data=_form("nobody", "warm"))

    started = time.monotonic()
    assert (await concurrent_browser.post("/oauth/authorize", data=_form("nobody", "x"))).status_code == 200
    one_attempt = time.monotonic() - started

    worst_probe = 0.0
    flood_done = asyncio.Event()

    async def poll_health() -> None:
        nonlocal worst_probe
        while not flood_done.is_set():
            sent = time.monotonic()
            probe = await concurrent_browser.get("/health")
            worst_probe = max(worst_probe, time.monotonic() - sent)
            assert probe.status_code == 200

    monitor = asyncio.ensure_future(poll_health())
    responses = await asyncio.gather(
        *(
            concurrent_browser.post("/oauth/authorize", data=_form(f"no-such-user-{index}", "x"))
            for index in range(FLOOD)
        )
    )
    flood_done.set()
    await monitor
    rate_limiter._events.clear()

    assert {response.status_code for response in responses} == {200}

    # Unfixed the worst probe is about `FLOOD * one_attempt`, since every
    # attempt runs to completion on the loop before the probe gets a turn.
    budget = one_attempt * 2
    assert worst_probe < budget, (
        "GET /health waited on unauthenticated password attempts: worst probe "
        f"{worst_probe * 1000:.1f} ms while {FLOOD} were in flight, against "
        f"{one_attempt * 1000:.1f} ms for one attempt. The derivation is "
        "blocking the event loop."
    )


def test_the_browser_login_form_has_an_attempt_ceiling(browser, monkeypatch) -> None:
    """`/oauth/authorize` was the one auth endpoint with no limiter at all.

    That was tolerable while an invented username short-circuited in ~3 ms. It
    stopped being tolerable when closing the enumeration oracle made every
    attempt cost a full derivation: the cheapest unauthenticated request on the
    gateway became the most expensive one to serve, on the only route that would
    not refuse a caller for repeating it.
    """
    from gateway.app.main import rate_limiter

    monkeypatch.setattr(rate_limiter, "limit", 2)
    rate_limiter._events.clear()

    assert _submit(browser, "no-such-user", "x").status_code == 200
    assert _submit(browser, "no-such-user", "x").status_code == 200

    refused = _submit(browser, "no-such-user", "x")
    rate_limiter._events.clear()

    assert refused.status_code == 429
    assert refused.headers["Retry-After"] == str(rate_limiter.window_seconds)


def test_no_request_handler_derives_a_key_on_the_event_loop() -> None:
    """The threadpool hop has to be unforgettable, not merely present.

    Same shape as the test below, one layer out: `authenticate` is correct and
    synchronous, and every `async def` handler that calls it stops the process
    for the duration. The next handler that needs a password check must reach
    for `authenticate_async`, and this is what says so before it ships.
    """
    from pathlib import Path

    root = Path(__file__).resolve().parents[2]
    owner = root / "gateway" / "app" / "core" / "users.py"

    offenders = []
    for path in (root / "gateway").rglob("*.py"):
        if path == owner or "__pycache__" in path.parts:
            continue
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            if "authenticate(" in line:
                offenders.append(f"{path.relative_to(root)}:{number}")

    assert not offenders, (
        "these call sites run a key derivation on the event loop; use "
        f"users.authenticate_async instead: {offenders}"
    )


def test_no_module_outside_the_registry_verifies_a_password_itself() -> None:
    """The guard has to be unforgettable, not merely present.

    `verify_password` is the primitive: it takes a hash and cannot be
    constant-cost, because it has nothing to be constant against. Every caller
    that resolves a *username* must go through `authenticate`, which owns the
    decoy derivation and the refusal of the published example credential. This
    test is what stops the third call site from being written the way the second
    one was.
    """
    from pathlib import Path

    root = Path(__file__).resolve().parents[2]
    owner = root / "gateway" / "app" / "core" / "users.py"

    offenders = []
    for path in (root / "gateway").rglob("*.py"):
        if path == owner or "__pycache__" in path.parts:
            continue
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            if "verify_password(" in line:
                offenders.append(f"{path.relative_to(root)}:{number}")

    assert not offenders, (
        "these call sites check a password without the constant-cost guard; "
        f"use users.authenticate instead: {offenders}"
    )
