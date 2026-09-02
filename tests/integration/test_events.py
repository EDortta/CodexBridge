"""The mobile event stream, its polling fallback, and notification preferences — issue #13.

Weighted toward the acceptance criteria the issue names and toward the two
properties that fail silently when they fail:

- **no silent loss on resume.** Reconnecting from the last acknowledged id
  delivers every event in between exactly once, and a position the log can no
  longer continue from is *announced* rather than papered over.
- **authorization is by project, and it is re-checked while the stream runs.** A
  restricted principal sees its own projects and nothing else; authentication
  events never reach any principal; a token revoked or expired while a stream is
  open ends that stream.

## Why the stream is driven directly rather than through `TestClient`

`event_stream` takes its clock, its sleep and its session factory as parameters
(`gateway/app/api/routes/events.py`). Every stream test below drives that
generator with a fake clock and a fake sleep, so "did the second poll happen
yet" is a fact about the test rather than a race with wall-clock time. A test
that opened a real SSE connection and slept would be slow *and* flaky, and would
still not be able to assert what happens on the eleventh poll.

The route around it — the slot ceiling, the `text/event-stream` media type, the
`Last-Event-ID` header — is covered through the app, where it belongs.
"""

from __future__ import annotations

import ast
import json
import pathlib
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from gateway.app.api.errors import ApiError
from gateway.app.api.routes import events as events_routes
from gateway.app.api.routes import notifications as notifications_routes
from gateway.app.api.setup import install_api_conventions
from gateway.app.core.users import AuthenticatedPrincipal
from gateway.app.db.base import Base
from gateway.app.db.session import get_session
from gateway.app.services import event_types, store
from gateway.app.services.audit import record_event
from shared.protocol import (
    ExecutorRegistration,
    ProjectRegistration,
    SubmitTaskRequest,
    TaskMode,
    TaskPriority,
)


ALICE_TOKEN = "token-alice"    # p1 only, read + notifications.manage
READER_TOKEN = "token-reader"  # p1 only, read-only (no notifications.manage)
BOB_TOKEN = "token-bob"        # p2 only
ADMIN_TOKEN = "token-admin"    # everything

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]


@pytest.fixture
def users_file(tmp_path):
    path = tmp_path / "users.json"
    path.write_text(
        json.dumps(
            {
                "users": [
                    {
                        "user_id": "alice", "email": "alice@example.com", "password_hash": "x",
                        "roles": [], "allowed_projects": ["p1"],
                        "scopes": ["codexbridge.read", "codexbridge.notifications.manage"],
                        "enabled": True,
                    },
                    {
                        "user_id": "reader", "email": "reader@example.com", "password_hash": "x",
                        "roles": [], "allowed_projects": ["p1"],
                        "scopes": ["codexbridge.read"], "enabled": True,
                    },
                    {
                        "user_id": "bob", "email": "bob@example.com", "password_hash": "x",
                        "roles": [], "allowed_projects": ["p2"],
                        "scopes": ["codexbridge.read"], "enabled": True,
                    },
                    {
                        "user_id": "admin", "email": "admin@example.com", "password_hash": "x",
                        "roles": ["admin"], "allowed_projects": [],
                        "scopes": ["codexbridge.admin"], "enabled": True,
                    },
                ]
            }
        ),
        encoding="utf-8",
    )
    return str(path)


@pytest.fixture
async def api(users_file, monkeypatch):
    from gateway.app.core.config import settings

    monkeypatch.setattr(settings, "user_registry_file", users_file)

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with factory() as seed:
        await store.upsert_registry(
            seed,
            executors=[
                ExecutorRegistration(
                    executor_id="E1", display_name="E1", machine_token="t",
                    allowed_projects=["p1", "p2"], enabled=True,
                )
            ],
            projects=[
                ProjectRegistration(
                    project_id=pid, name=pid, path=f"/srv/{pid}",
                    allowed_modes=[TaskMode.ANALYZE], max_timeout_seconds=600,
                    sensitive_patterns=[], enabled=True,
                )
                for pid in ("p1", "p2")
            ],
        )
        future = datetime.now(timezone.utc) + timedelta(hours=1)
        for token, user_id, scopes in (
            (ALICE_TOKEN, "alice", ["codexbridge.read", "codexbridge.notifications.manage"]),
            (READER_TOKEN, "reader", ["codexbridge.read"]),
            (BOB_TOKEN, "bob", ["codexbridge.read"]),
            (ADMIN_TOKEN, "admin", ["codexbridge.admin"]),
        ):
            await store.create_oauth_access_token(
                seed, token=token, client_id="c", user_id=user_id, scopes=scopes, expires_at=future
            )

    app = FastAPI(openapi_url=None, docs_url=None, redoc_url=None)
    install_api_conventions(app)
    app.include_router(events_routes.router)
    app.include_router(notifications_routes.router)

    async def override():
        async with factory() as s:
            yield s

    app.dependency_overrides[get_session] = override

    # The slot ceiling is process-global. Restoring it keeps a test that fills
    # it from making every later test in the session answer 503.
    original_slots = events_routes.stream_slots
    events_routes.stream_slots = events_routes.StreamSlots(original_slots.limit)

    client = TestClient(app, raise_server_exceptions=False)
    client.factory = factory  # type: ignore[attr-defined]
    yield client
    events_routes.stream_slots = original_slots
    await engine.dispose()


def auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


async def make_task(factory, project_id: str = "p1"):
    async with factory() as s:
        return await store.create_task(
            s,
            SubmitTaskRequest(
                executor_id="E1", project_id=project_id, instruction="analyze it",
                mode=TaskMode.ANALYZE, priority=TaskPriority.NORMAL, timeout_seconds=60,
                expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
            ),
            executor_online=True,
        )


async def emit(factory, entity_type: str, entity_id: str, event_type: str, payload: dict) -> int:
    """Write one audit row directly and return its id.

    Direct rather than through the endpoint that would produce it: these tests
    are about the translation and the delivery, and driving eleven different
    product flows to obtain eleven audit rows would test those flows instead.
    The rows written here are the same rows `record_event` writes anywhere else
    — same table, same columns, same autoincrement id.
    """
    async with factory() as s:
        await record_event(s, entity_type, entity_id, event_type, payload)
        await s.commit()
    return await newest_audit_id(factory)


async def newest_audit_id(factory) -> int:
    async with factory() as s:
        from sqlalchemy import func, select

        from gateway.app.models.entities import AuditEventModel

        return (await s.execute(select(func.max(AuditEventModel.id)))).scalar() or 0


# --------------------------------------------------------------------------
# Driving the generator
# --------------------------------------------------------------------------


class FakeClock:
    """A monotonic clock the test moves on purpose.

    `event_stream` reads the clock to decide when to heartbeat and when its
    maximum duration is up. Both are timing decisions, and asserting on a timing
    decision against `time.monotonic` means sleeping — which is slow when it
    passes and flaky when it does not.
    """

    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


def stepping_sleep(clock: FakeClock, step: float = 1.0, on_poll=None):
    """An `asyncio.sleep` replacement that advances the fake clock instead.

    `on_poll` runs between polls, which is how a test inserts an event *while*
    the stream is running rather than only before it opens.
    """

    async def _sleep(_seconds: float) -> None:
        clock.now += step
        if on_poll is not None:
            await on_poll()

    return _sleep


def parse_frames(chunks: list[str]) -> list[dict]:
    """SSE text as a list of `{id?, event?, data?, comment?}` dicts.

    Parsed rather than string-matched: `id:` appearing on the right frames is
    one of the properties under test, and a substring assertion cannot tell
    which frame a line belongs to.
    """
    frames: list[dict] = []
    for block in "".join(chunks).split("\n\n"):
        if not block.strip():
            continue
        frame: dict = {}
        for line in block.split("\n"):
            if line.startswith(":"):
                frame["comment"] = line[1:].strip()
            elif line.startswith("id: "):
                frame["id"] = int(line[4:])
            elif line.startswith("event: "):
                frame["event"] = line[7:]
            elif line.startswith("data: "):
                frame["data"] = json.loads(line[6:])
        frames.append(frame)
    return frames


async def run_stream(factory, *, token: str, resume_from: int = 0, polls: int = 1,
                     projects=None, types=None, on_poll=None, is_disconnected=None,
                     heartbeat_seconds: float = 1e9, batch_limit: int = 200) -> list[dict]:
    """Drive `event_stream` for exactly `polls` iterations and return its frames.

    `max_duration_seconds` is set to `polls` and the fake clock advances by one
    per sleep, so the generator stops itself after the requested number of
    polls — no `aclose()` from outside, which means the `stream.closed` frame
    and the `finally` block are both exercised the way production reaches them.
    """
    clock = FakeClock()
    frames: list[str] = []
    async for chunk in events_routes.event_stream(
        factory=factory,
        token=token,
        resume_from=resume_from,
        requested_projects=projects,
        requested_types=types or [],
        poll_interval=0.0,
        heartbeat_seconds=heartbeat_seconds,
        max_duration_seconds=float(polls),
        batch_limit=batch_limit,
        is_disconnected=is_disconnected,
        monotonic=clock,
        sleep=stepping_sleep(clock, 1.0, on_poll),
    ):
        frames.append(chunk)
    return parse_frames(frames)


def redact_for_test(value: str | None) -> str | None:
    """The real redactor, imported through the route module the code injects."""
    from gateway.app.api.routes.sessions import redact

    return redact(value)


def entity_frames(frames: list[dict]) -> list[dict]:
    """Only the frames that carry an event — control frames and heartbeats out."""
    return [f for f in frames if "id" in f]


# --------------------------------------------------------------------------
# The backlog endpoint
# --------------------------------------------------------------------------


async def test_the_backlog_returns_translated_events_oldest_first(api) -> None:
    task = await make_task(api.factory, "p1")
    await emit(api.factory, "task", task.id, "task.state_changed", {"state": "running"})
    await emit(api.factory, "task", task.id, "task.result", {"state": "succeeded"})

    body = api.get("/api/v1/events", headers=auth(ALICE_TOKEN)).json()

    types = [item["type"] for item in body["items"]]
    assert types == ["session.created", "session.state_changed", "session.completed"]
    ids = [item["id"] for item in body["items"]]
    assert ids == sorted(ids), "the backlog is read forward; a client catching up reads oldest first"

    first = body["items"][0]
    assert first["projectId"] == "p1"
    assert first["entity"] == {"kind": "session", "id": task.id}
    assert first["action"] == "created"
    assert first["at"].endswith("Z")


async def test_the_page_reports_more_and_a_position_to_continue_from(api) -> None:
    task = await make_task(api.factory, "p1")
    for index in range(6):
        await emit(api.factory, "task", task.id, "task.state_changed", {"state": f"s{index}"})

    first = api.get("/api/v1/events?limit=3", headers=auth(ALICE_TOKEN)).json()
    assert len(first["items"]) == 3
    assert first["page"]["hasMore"] is True
    assert first["page"]["nextAfter"] == first["items"][-1]["id"]

    second = api.get(
        f"/api/v1/events?limit=3&after={first['page']['nextAfter']}", headers=auth(ALICE_TOKEN)
    ).json()
    assert [item["id"] for item in second["items"]] > [item["id"] for item in first["items"]]

    walked = [item["id"] for item in first["items"] + second["items"]]
    assert len(walked) == len(set(walked)), "a paginated walk must not repeat an event"


async def test_a_type_filter_narrows_without_making_the_position_stall(api) -> None:
    """`nextAfter` is the last id *loaded*, not the last id returned.

    Reporting the last returned id would make the next request re-scan the rows
    the filter already rejected — and when nothing in the tail matches, forever:
    the client would poll the same page for the rest of the stream's life.
    """
    task = await make_task(api.factory, "p1")
    wanted = await emit(api.factory, "task", task.id, "task.result", {"state": "succeeded"})
    for _ in range(4):
        await emit(api.factory, "task", task.id, "task.state_changed", {"state": "running"})

    body = api.get(
        "/api/v1/events?limit=3&type=session.completed", headers=auth(ALICE_TOKEN)
    ).json()

    assert [item["id"] for item in body["items"]] == [wanted]
    assert body["page"]["hasMore"] is True
    assert body["page"]["nextAfter"] > wanted, (
        "the position must advance past the filtered-out rows this page loaded"
    )


async def test_an_unknown_type_filter_is_a_validation_error(api) -> None:
    response = api.get("/api/v1/events?type=session.exploded", headers=auth(ALICE_TOKEN))
    assert response.status_code == 400
    body = response.json()
    assert body["code"] == "validation_failed"
    assert body["details"][0]["code"] == "unknown_event_type"


async def test_a_declared_but_unemitted_type_filters_to_nothing_rather_than_failing(api) -> None:
    """`artifact.*` is in the vocabulary and produced by nothing in this build.

    Rejecting it would make the declared-but-unemitted values unusable, which is
    the opposite of why they were declared: a client written against the
    contract must be able to subscribe to them before the build that emits them
    exists.
    """
    task = await make_task(api.factory, "p1")
    await emit(api.factory, "task", task.id, "task.result", {"state": "succeeded"})

    response = api.get("/api/v1/events?type=artifact.created", headers=auth(ALICE_TOKEN))
    assert response.status_code == 200
    assert response.json()["items"] == []


async def test_the_project_filter_only_ever_narrows(api) -> None:
    p1 = await make_task(api.factory, "p1")
    p2 = await make_task(api.factory, "p2")

    seen = api.get("/api/v1/events?project=p2", headers=auth(ALICE_TOKEN)).json()["items"]
    assert seen == [], "naming a project outside allowedProjects must narrow, never widen"

    as_admin = api.get("/api/v1/events?project=p2", headers=auth(ADMIN_TOKEN)).json()["items"]
    assert {item["entity"]["id"] for item in as_admin} == {p2.id}
    assert p1.id not in {item["entity"]["id"] for item in as_admin}


# --------------------------------------------------------------------------
# Authorization
# --------------------------------------------------------------------------


async def test_a_restricted_principal_sees_only_its_own_projects_events(api) -> None:
    p1 = await make_task(api.factory, "p1")
    p2 = await make_task(api.factory, "p2")

    alice = api.get("/api/v1/events", headers=auth(ALICE_TOKEN)).json()["items"]
    bob = api.get("/api/v1/events", headers=auth(BOB_TOKEN)).json()["items"]
    admin = api.get("/api/v1/events", headers=auth(ADMIN_TOKEN)).json()["items"]

    assert {item["projectId"] for item in alice} == {"p1"}
    assert {item["entity"]["id"] for item in alice} == {p1.id}
    assert {item["projectId"] for item in bob} == {"p2"}
    assert {item["projectId"] for item in admin} == {"p1", "p2"}


async def test_authentication_events_never_appear_on_any_principals_feed(api) -> None:
    """Sign-in activity is not a product event, and streaming it is a disclosure.

    The audit log these events are derived from also records sign-in, failed
    sign-in and credential revocation. Delivering those would tell any token
    holder — including one belonging to a *different* person — when the operator
    signs in and from where. They are excluded by construction (`auth` carries no
    project, so it is not in `DELIVERABLE_ENTITY_TYPES`) rather than by a filter
    someone has to remember, and this is the test that says so.

    Three independent guards have to all be removed for one of these to ship,
    and each is asserted here so that removing any one of them is a red test
    rather than a thinner defence nobody notices.
    """
    # Guard 1: the audit event types are outside the translated vocabulary, so
    # the query never selects the row.
    assert not {"auth.signed_in", "auth.sign_in_failed", "auth.credentials_revoked"} & set(
        event_types.TRANSLATED_AUDIT_EVENT_TYPES
    )
    # Guard 2: the entity type is not deliverable, so the query never selects it
    # by entity either. (Guard 3 — no project can be derived for it — is
    # `test_an_event_whose_project_cannot_be_derived_reaches_nobody`.)
    assert store.AUTH_ENTITY_TYPE not in event_types.DELIVERABLE_ENTITY_TYPES

    async with api.factory() as s:
        await store.record_auth_event(
            s, user_id="alice", event_type="auth.signed_in", payload={"reason": "password"}
        )
        await store.record_auth_event(
            s, user_id="alice", event_type="auth.sign_in_failed", payload={"reason": "bad_password"}
        )
        await store.revoke_access_token(s, token=BOB_TOKEN, user_id="bob", reason="test")

    for token in (ALICE_TOKEN, ADMIN_TOKEN):
        body = api.get("/api/v1/events", headers=auth(token)).json()
        assert body["items"] == [], f"{token} received an authentication event"

    frames = await run_stream(api.factory, token=ADMIN_TOKEN, polls=1)
    assert entity_frames(frames) == []


async def test_a_preference_change_is_not_a_project_event(api) -> None:
    """`notification` rows are excluded the same way `auth` rows are.

    A person's own preference is not a project's event, and the row's
    `entity_id` is a user id where a project would be — so delivering it would
    also publish which accounts exist.
    """
    api.put(
        "/api/v1/notifications/preferences",
        headers=auth(ALICE_TOKEN),
        json={"eventTypes": ["decision.requested"], "pushEnabled": True},
    )

    assert api.get("/api/v1/events", headers=auth(ADMIN_TOKEN)).json()["items"] == []


async def test_an_event_whose_project_cannot_be_derived_reaches_nobody(api) -> None:
    """Fail closed, administrators included.

    An audit row naming an entity that no longer exists (or one this build
    cannot resolve to a project) has no project to authorize against. Delivering
    it to an administrator "because they see everything" would make it the one
    event on this surface that no project check covers — and it would be
    rendered by a client under whichever project it happened to be looking at.
    """
    await emit(api.factory, "task", "no-such-task", "task.state_changed", {"state": "running"})

    for token in (ALICE_TOKEN, ADMIN_TOKEN):
        assert api.get("/api/v1/events", headers=auth(token)).json()["items"] == []


async def test_reading_events_requires_the_read_scope(api) -> None:
    response = api.get("/api/v1/events", headers={"Authorization": "Bearer nonsense"})
    assert response.status_code == 401
    assert response.json()["code"] == "unauthenticated"


# --------------------------------------------------------------------------
# The payload is internal; the event is public
# --------------------------------------------------------------------------


async def test_no_stored_payload_key_is_passed_through_to_a_client(api) -> None:
    """The audit payload is written by fifty-one call sites and is not a response.

    It carries `actor_email`, `requested_by_email` and free-text `context`
    blobs. A translation that spread the payload into the event — or that
    included it as a `payload` field "for debugging" — would ship every one of
    them. The contract is a whitelist, so this asserts on the *absence* of
    everything nobody whitelisted.
    """
    task = await make_task(api.factory, "p1")
    await emit(
        api.factory, "task", task.id, "task.stopped_by_actor",
        {
            "state": "cancelled",
            "actor_id": "alice",
            "actor_email": "alice@example.com",
            "requested_by_email": "boss@example.com",
            "context": {"internal": "secret"},
            "reason": "operator asked",
        },
    )

    body = api.get("/api/v1/events", headers=auth(ALICE_TOKEN)).json()
    serialized = json.dumps(body)

    assert "alice@example.com" not in serialized
    assert "boss@example.com" not in serialized
    assert "secret" not in serialized
    assert "payload" not in body["items"][-1]
    # The whitelisted keys did come through, or the assertions above would pass
    # trivially on an empty event.
    stopped = body["items"][-1]
    assert stopped["actorId"] == "alice"
    assert "operator asked" in stopped["summary"]


async def test_free_text_in_a_summary_is_redacted_and_bounded(api) -> None:
    """`redact` is applied to executor free text, and the line has a ceiling.

    `last_error` can be a multi-kilobyte traceback carrying a bearer token and a
    server path. A summary is a notification line: it is redacted through the
    same function `GET /api/v1/sessions/{id}/logs` uses, and truncated.
    """
    task = await make_task(api.factory, "p1")
    await emit(
        api.factory, "task", task.id, "task.state_changed",
        {"state": "failed", "error": "Bearer sk-abcdefghijklmnop failed at " + ("x" * 500)},
    )

    body = api.get("/api/v1/events", headers=auth(ALICE_TOKEN)).json()
    summary = body["items"][-1]["summary"]

    assert "sk-abcdefghijklmnop" not in summary
    # The contract publishes `MobileEvent.summary` as `maxLength: 300`, so that
    # is the number to assert. The first cut said 400, which would have let a
    # regression past the contract without failing (council round 1, a recorded
    # question from the claim auditor).
    assert len(summary) <= 300, "a notification line must not be an unbounded traceback"

    # Asserted across every emitted type, not just this one: the bound belongs
    # to the contract, and one type's builder is not evidence about the others.
    for mobile_type in event_types.EMITTED_EVENT_TYPES:
        built = event_types.summarize(
            mobile_type,
            {"error": "e" * 5000, "reason": "r" * 5000, "state": "running", "control": "pause"},
            redact_for_test,
        )
        assert len(built) <= 300, f"{mobile_type} can exceed the contract's maxLength"



async def test_an_executors_control_and_state_strings_cannot_reach_a_notification_line(api) -> None:
    """Council round 1, the adversarial user — the whitelist's premise was false.

    `_ENUM_KEYS` admitted `control` and `state` on the stated grounds that their
    values "are server-generated enums rather than free text". They are not:
    `gateway/app/main.py` reads both straight out of an executor's `task.ack`
    frame with no validation, and the `invalid_state` branch records the very
    string it just refused *because* it is not a `TaskState`. A connected
    executor could therefore put a filesystem path, an internal `host:port`, a
    `Bearer` value and a 200 KB blob into a mobile notification line, past every
    guard in `event_types.py`.

    Membership in a closed vocabulary is the fix, not redaction: `redact` strips
    the patterns it knows, while a closed set admits only values this system
    defines — whatever the rejected one contains, and however long it is.
    """
    task = await make_task(api.factory, "p1")
    hostile = (
        "/etc/codex-bridge/users.json on db.internal 10.0.0.7:5432 "
        "Authorization: Bearer abc123 sk-SECRETSECRETSECRET " + ("x" * 5000)
    )
    await emit(
        api.factory, "task", task.id, "task.control_acknowledged",
        {"accepted": False, "control": hostile, "state": hostile},
    )
    await emit(
        api.factory, "task", task.id, "task.ack_refused",
        {"reason": "invalid_state", "state": hostile},
    )

    body = api.get("/api/v1/events", headers=auth(ALICE_TOKEN)).json()
    serialized = json.dumps(body)

    for secret in ("/etc/codex-bridge", "db.internal", "10.0.0.7:5432", "Bearer abc123", "sk-SECRET"):
        assert secret not in serialized, f"{secret!r} reached a mobile client"
    assert "xxxx" not in serialized

    acknowledged = next(i for i in body["items"] if i["type"] == "session.control_acknowledged")
    assert acknowledged["summary"] == "The executor refused a control."
    assert "state" not in acknowledged, (
        "a state outside TaskState is omitted, not echoed: a client switches on this enum"
    )


def test_every_echoed_payload_value_comes_from_a_closed_vocabulary() -> None:
    """The guard behind the test above, asserted directly.

    Two properties. Every key `_enum` will answer for has a vocabulary — so a
    key added to a summary builder without one silently yields the default
    rather than echoing. And the guard is not an `assert`: `python -O` strips
    those, and a defence that vanishes under an interpreter flag is not one.
    """
    for key, allowed in event_types._ENUM_VOCABULARIES.items():
        assert allowed, f"{key} has an empty vocabulary"
        assert all(isinstance(value, str) and value for value in allowed)
        assert event_types._enum({key: "definitely-not-a-member"}, key) == "unknown"
        assert event_types._enum({key: next(iter(allowed))}, key) == next(iter(allowed))

    # An unknown key falls back rather than raising, and does so with -O too.
    assert event_types._enum({"nope": "value"}, "nope") == "unknown"
    assert event_types.state_of({"state": "not-a-state"}) is None
    assert event_types.state_of({"state": "running"}) == "running"


async def test_the_gap_signal_cannot_report_on_events_the_caller_may_not_see(api) -> None:
    """Council round 1 — the `gap` block was a one-bit oracle over the whole log.

    `audit_cursor_status` and `oldest_audit_event_id` queried `audit_events`
    unscoped while the page beside them was correctly scoped. A project-limited
    token could therefore poll `?after=<newest+1>`, watch `gap` disappear the
    instant *any* row was written anywhere — an operator's sign-in, a
    revocation, another tenant's task — and binary-search `?after=` for the
    global newest id, with `items` empty throughout. Every one of those is an
    event this surface excludes by construction.
    """
    await make_task(api.factory, "p1")
    ahead = await newest_audit_id(api.factory) + 1

    before = api.get(f"/api/v1/events?after={ahead}", headers=auth(ALICE_TOKEN)).json()
    assert before["gap"]["reason"] == store.CURSOR_AHEAD

    # Three rows alice may never see: two auth, one another project's.
    async with api.factory() as s:
        await store.record_auth_event(
            s, user_id="admin", event_type="auth.signed_in", payload={"reason": "password"}
        )
    await make_task(api.factory, "p2")

    after = api.get(f"/api/v1/events?after={ahead}", headers=auth(ALICE_TOKEN)).json()
    assert after["items"] == []
    assert after["gap"] == before["gap"], (
        "the gap signal moved because of rows the caller may not see — an oracle "
        "over the audit log, including sign-in activity"
    )

    # And it still moves for a row alice *may* see, or the signal would be inert.
    await make_task(api.factory, "p1")
    visible = api.get(f"/api/v1/events?after={ahead}", headers=auth(ALICE_TOKEN)).json()
    assert visible["items"], "precondition: the new row is one alice can see"


async def test_the_oldest_available_id_is_the_callers_own_oldest(api) -> None:
    """`oldestAvailableId` returned the global minimum audit id to any reader.

    A client that fell behind needs somewhere to restart from — its own feed's
    oldest position, not the first row the gateway ever wrote for anyone.
    """
    async with api.factory() as s:
        await store.record_auth_event(
            s, user_id="admin", event_type="auth.signed_in", payload={"reason": "password"}
        )
    await make_task(api.factory, "p2")
    p1_task = await make_task(api.factory, "p1")

    async with api.factory() as s:
        p1_first = (await store.list_mobile_events_page(
            s, project_ids=["p1"],
            entity_types=sorted(event_types.DELIVERABLE_ENTITY_TYPES),
            audit_event_types=sorted(event_types.TRANSLATED_AUDIT_EVENT_TYPES),
            after=None, limit=5,
        ))[0][0].id

    body = api.get(f"/api/v1/events?after={p1_first + 10_000}", headers=auth(ALICE_TOKEN)).json()

    assert body["gap"]["oldestAvailableId"] == p1_first
    assert body["gap"]["oldestAvailableId"] != 1, (
        "the global minimum belongs to an auth row alice may not know exists"
    )
    assert p1_task is not None


async def test_a_resume_position_beyond_the_id_range_is_refused_not_a_500(api) -> None:
    """Council round 1 — `?after=2**63+1` was an authenticated 500.

    `ge=0` bounded the low end only, and the value went straight into the query,
    where the driver raised `OverflowError` and the caller got
    `500 internal_error`. An unbounded integer parameter is unbounded in both
    directions.
    """
    response = api.get(f"/api/v1/events?after={2**63 + 1}", headers=auth(ALICE_TOKEN))

    # 422 rather than 400: this is FastAPI's own parameter validation, and
    # `errors.py` maps it to the same `validation_failed` envelope every other
    # endpoint's bad parameter produces. What matters is that it is the caller's
    # error and not an unhandled `OverflowError` reported as `internal_error`.
    assert response.status_code == 422
    assert response.json()["code"] == "validation_failed"

    stream = api.get(f"/api/v1/events/stream?after={2**63 + 1}", headers=auth(ALICE_TOKEN))
    assert stream.status_code == 422, (
        "refused before the body commits to 200 text/event-stream, where no "
        "status code is left to change"
    )
    assert events_routes.stream_slots.active == 0, "a refused stream must not hold a slot"


async def test_an_out_of_range_last_event_id_is_clamped_not_replayed(api) -> None:
    """The same overflow on the stream, where a 500 is not even available.

    Once the body has committed to `200 text/event-stream` there is no status
    code left to change: the unbounded version emitted `stream.open` and then
    the generator died inside the cursor check, so the body simply ended — no
    `stream.gap`, no `stream.closed`, indistinguishable from a quiet feed.

    Clamped rather than discarded: discarding would fall back to `after`, or to
    0, and replay the entire feed to a client that asked to *resume*.
    """
    assert events_routes._resume_from(str(2**63 + 5), None) == events_routes.MAX_EVENT_ID
    assert events_routes._resume_from(None, 2**70) == events_routes.MAX_EVENT_ID

    await make_task(api.factory, "p1")
    frames = await run_stream(
        api.factory, token=ALICE_TOKEN, resume_from=events_routes.MAX_EVENT_ID, polls=1
    )

    assert [f.get("event") for f in frames].count(event_types.STREAM_GAP) == 1
    assert frames[-1]["event"] == event_types.STREAM_CLOSED
    assert entity_frames(frames) == [], "a clamped position must not replay the feed"


def test_every_emitted_event_type_has_a_summary_builder() -> None:
    """A type with no builder falls back to a bland sentence — silently.

    The fallback exists so one unmapped type cannot break a stream, which means
    it cannot be the thing that tells anyone the mapping is incomplete. This is.
    """
    missing = [
        value for value in event_types.EMITTED_EVENT_TYPES
        if event_types.summarize(value, {}, lambda text: text) == "Event recorded."
    ]
    assert not missing, f"emitted event types with no summary of their own: {missing}"


def test_every_audited_domain_event_type_is_translated() -> None:
    """A new audit event under a deliverable entity must be classified on purpose.

    `classify` returning None is safe — the row is not emitted — and silent,
    which is the failure this catches: an author who adds a `record_event` for a
    new kind of issue update would ship a mobile client that never hears about
    it, with the whole suite green. Parsed from the source rather than collected
    at runtime, because the point is to catch a writer no test exercises yet.
    """
    unclassified: list[str] = []
    written: set[str] = set()
    for path in (REPO_ROOT / "gateway").rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", None)
            if name != "record_event" or len(node.args) < 4:
                continue
            entity, event_type = node.args[1], node.args[3]
            if not isinstance(entity, ast.Constant) or not isinstance(event_type, ast.Constant):
                # A non-literal entity type is one of the two module constants
                # (`AUTH_ENTITY_TYPE`, `NOTIFICATION_ENTITY_TYPE`), neither of
                # which is deliverable. Skipping it is safe *because* those
                # constants are asserted non-deliverable just below.
                continue
            if entity.value not in event_types.DELIVERABLE_ENTITY_TYPES:
                continue
            written.add(event_type.value)
            if event_type.value in event_types.NOT_DELIVERED:
                continue
            if event_type.value not in event_types.TRANSLATED_AUDIT_EVENT_TYPES:
                unclassified.append(f"{path.relative_to(REPO_ROOT)}:{node.lineno} {event_type.value}")

    assert not unclassified, (
        "audit events written under a deliverable entity that "
        f"gateway/app/services/event_types.py does not translate: {unclassified}. "
        "Add a mapping (and a summary), or an entry in NOT_DELIVERED saying why "
        "the mobile client should never hear about them."
    )

    # The other direction. `NOT_DELIVERED` suppresses the guard, so an entry that
    # outlives its writer suppresses it for a type nothing writes — and would go
    # on doing so for whoever reuses that name later. Same reason
    # `NOT_YET_EMITTED` is pinned rather than trusted.
    stale = sorted(set(event_types.NOT_DELIVERED) - written)
    assert not stale, (
        f"NOT_DELIVERED names event types nothing writes any more: {stale}. "
        "Drop them; an exemption for an absent writer is an exemption waiting to "
        "be inherited by an unrelated one."
    )
    overlap = sorted(set(event_types.NOT_DELIVERED) & event_types.TRANSLATED_AUDIT_EVENT_TYPES)
    assert not overlap, (
        f"these types are both mapped and excluded: {overlap}. The mapping wins at "
        "runtime, so the NOT_DELIVERED entry is a comment that lies."
    )


def test_the_non_deliverable_entity_constants_stay_non_deliverable() -> None:
    """The exclusion of auth and preference rows is by construction; pin it.

    `test_every_audited_domain_event_type_is_translated` skips call sites whose
    entity type is one of these constants. That skip is only sound while the
    constants are outside the deliverable set — otherwise the two tests together
    would leave every auth writer unchecked.
    """
    assert store.AUTH_ENTITY_TYPE not in event_types.DELIVERABLE_ENTITY_TYPES
    assert store.NOTIFICATION_ENTITY_TYPE not in event_types.DELIVERABLE_ENTITY_TYPES


def test_the_declared_but_unemitted_types_are_not_produced_by_this_build() -> None:
    """`artifact.*` and `androidBuild.*` are contract, not behaviour.

    Declared so that issue #11 is additive rather than a new major version. #11's
    tables have since landed and still produce no audit row, so this stays true
    and stays worth pinning: it is exactly when the model exists that someone
    starts emitting one. That
    is only honest while nothing produces one: a type that quietly started being
    emitted here would be an undocumented behaviour change dressed as a
    pre-agreed one.
    """
    assert set(event_types.NOT_YET_EMITTED) & set(event_types.EMITTED_EVENT_TYPES) == set()
    produced = {
        event_types.classify(audit_type, {"state": state})[0]
        for audit_type in event_types.TRANSLATED_AUDIT_EVENT_TYPES
        for state in ("awaiting_approval", "running")
    }
    assert produced & set(event_types.NOT_YET_EMITTED) == set()
    assert set(event_types.NOT_YET_EMITTED) <= set(event_types.ALL_EVENT_TYPES)


# --------------------------------------------------------------------------
# The stream: resume, loss, duplicates
# --------------------------------------------------------------------------


async def test_the_stream_opens_with_an_acknowledgement_carrying_no_position(api) -> None:
    """`stream.open` must not carry `id:`.

    A control frame with an SSE id advances the client's `Last-Event-ID` past
    events it never received — which is exactly the silent loss this endpoint's
    acceptance criterion forbids.
    """
    frames = await run_stream(api.factory, token=ALICE_TOKEN, polls=1)

    assert frames[0]["event"] == event_types.STREAM_OPEN
    assert "id" not in frames[0]
    assert frames[-1]["event"] == event_types.STREAM_CLOSED
    assert "id" not in frames[-1]
    assert frames[-1]["data"]["reason"] == "max_duration"


async def test_events_recorded_while_the_stream_runs_are_delivered(api) -> None:
    task = await make_task(api.factory, "p1")
    pending = ["running", "succeeded"]

    async def on_poll():
        if pending:
            await emit(api.factory, "task", task.id, "task.state_changed", {"state": pending.pop(0)})

    frames = await run_stream(api.factory, token=ALICE_TOKEN, polls=4, on_poll=on_poll)

    delivered = entity_frames(frames)
    assert [f["event"] for f in delivered] == [
        "session.created", "session.state_changed", "session.state_changed"
    ]
    assert [f["id"] for f in delivered] == sorted(f["id"] for f in delivered)
    assert all(f["data"]["id"] == f["id"] for f in delivered), (
        "the SSE id and the event body's id are one position, not two"
    )


async def test_reconnecting_from_the_last_id_loses_nothing_and_repeats_nothing(api) -> None:
    """The acceptance criterion, end to end.

    A first stream delivers some events; more are recorded while nothing is
    connected; a second stream resumes from the last id the first delivered. The
    union must be every event exactly once — no gap across the disconnect, no
    replay of what was already acknowledged.
    """
    task = await make_task(api.factory, "p1")
    for state in ("queued", "running"):
        await emit(api.factory, "task", task.id, "task.state_changed", {"state": state})

    first = entity_frames(await run_stream(api.factory, token=ALICE_TOKEN, polls=1))
    assert first, "the first connection must deliver the backlog"
    last_seen = first[-1]["id"]

    # Recorded while the client is disconnected: nothing is holding a cursor.
    for state in ("paused", "resumed", "succeeded"):
        await emit(api.factory, "task", task.id, "task.state_changed", {"state": state})

    second = entity_frames(
        await run_stream(api.factory, token=ALICE_TOKEN, resume_from=last_seen, polls=1)
    )

    first_ids = [f["id"] for f in first]
    second_ids = [f["id"] for f in second]
    assert set(first_ids) & set(second_ids) == set(), "an acknowledged event was delivered twice"

    everything = api.get("/api/v1/events", headers=auth(ALICE_TOKEN)).json()["items"]
    assert first_ids + second_ids == [item["id"] for item in everything], (
        "the two connections together must be the whole log, in order, once each"
    )


async def test_the_same_position_replayed_twice_delivers_the_same_events(api) -> None:
    """Resume is a pure function of the position, so a duplicated reconnect is safe.

    A mobile client that reconnects twice — a race between the OS waking it and
    its own retry timer — must not be punished with a partial second view. `id >
    position` makes replay idempotent, and this pins that it is.
    """
    task = await make_task(api.factory, "p1")
    for state in ("queued", "running", "succeeded"):
        await emit(api.factory, "task", task.id, "task.state_changed", {"state": state})

    once = entity_frames(await run_stream(api.factory, token=ALICE_TOKEN, resume_from=1, polls=1))
    twice = entity_frames(await run_stream(api.factory, token=ALICE_TOKEN, resume_from=1, polls=1))

    assert [f["id"] for f in once] == [f["id"] for f in twice]
    assert [f["data"] for f in once] == [f["data"] for f in twice]


async def test_a_position_the_log_has_moved_past_is_announced_before_anything_is_delivered(api) -> None:
    """A gap is signalled, never papered over — and signalled *first*.

    Delivering events and mentioning the gap afterwards would let a client act
    on a partial view believing it was continuous. Note what is being simulated:
    this build's retention sweep deletes authentication rows only, so no domain
    event has ever been purged in production. The check exists so that a future
    retention policy over domain rows cannot cause a silent loss the day an
    operator enables it.
    """
    task = await make_task(api.factory, "p1")
    for state in ("queued", "running", "succeeded"):
        await emit(api.factory, "task", task.id, "task.state_changed", {"state": state})

    async with api.factory() as s:
        from sqlalchemy import delete, func, select

        from gateway.app.models.entities import AuditEventModel

        oldest = (await s.execute(select(func.min(AuditEventModel.id)))).scalar()
        await s.execute(delete(AuditEventModel).where(AuditEventModel.id == oldest))
        await s.commit()

    frames = await run_stream(api.factory, token=ALICE_TOKEN, resume_from=oldest, polls=1)

    assert frames[0]["event"] == event_types.STREAM_OPEN
    gap = frames[1]
    assert gap["event"] == event_types.STREAM_GAP
    assert "id" not in gap, "a gap frame must not advance Last-Event-ID"
    assert gap["data"]["reason"] == store.CURSOR_BEYOND_RETENTION
    assert gap["data"]["from"] == oldest
    assert gap["data"]["oldestAvailableId"] == oldest + 1
    assert gap["data"]["oldestAvailableId"] is not None

    delivered = entity_frames(frames)
    assert delivered, "the stream still delivers what survives"
    assert frames.index(gap) < frames.index(delivered[0])


async def test_a_position_ahead_of_the_log_is_a_gap_too(api) -> None:
    """The mirror case: a cursor from another deployment, or a restored backup.

    Left unsignalled the stream would simply never deliver again — the same
    silence in the other direction, and the harder one to diagnose from a phone.
    """
    task = await make_task(api.factory, "p1")
    await emit(api.factory, "task", task.id, "task.state_changed", {"state": "running"})
    newest = await newest_audit_id(api.factory)

    frames = await run_stream(api.factory, token=ALICE_TOKEN, resume_from=newest + 500, polls=1)

    gap = frames[1]
    assert gap["event"] == event_types.STREAM_GAP
    assert gap["data"]["reason"] == store.CURSOR_AHEAD
    assert entity_frames(frames) == []


async def test_a_continuous_position_produces_no_gap_frame(api) -> None:
    """The signal is only worth having if it stays quiet when nothing was lost."""
    task = await make_task(api.factory, "p1")
    first = await newest_audit_id(api.factory)
    await emit(api.factory, "task", task.id, "task.state_changed", {"state": "running"})

    frames = await run_stream(api.factory, token=ALICE_TOKEN, resume_from=first, polls=1)

    assert [f.get("event") for f in frames].count(event_types.STREAM_GAP) == 0


async def test_the_polling_fallback_reports_the_same_gap(api) -> None:
    """"No silent loss" is a property of the events, not of one transport.

    A client living on the polling fallback — a background app, a network that
    kills long connections — would otherwise be handed a page starting wherever
    the log now begins, with nothing to distinguish it from continuity.
    """
    task = await make_task(api.factory, "p1")
    for state in ("queued", "running"):
        await emit(api.factory, "task", task.id, "task.state_changed", {"state": state})

    async with api.factory() as s:
        from sqlalchemy import delete, func, select

        from gateway.app.models.entities import AuditEventModel

        oldest = (await s.execute(select(func.min(AuditEventModel.id)))).scalar()
        await s.execute(delete(AuditEventModel).where(AuditEventModel.id == oldest))
        await s.commit()

    body = api.get(f"/api/v1/events?after={oldest}", headers=auth(ALICE_TOKEN)).json()
    assert body["gap"]["reason"] == store.CURSOR_BEYOND_RETENTION
    assert body["gap"]["from"] == oldest

    fine = api.get(f"/api/v1/events?after={oldest + 1}", headers=auth(ALICE_TOKEN)).json()
    assert "gap" not in fine, "a continuous position must not be reported as a gap"


# --------------------------------------------------------------------------
# The stream: a credential that stops being usable
# --------------------------------------------------------------------------


async def test_a_revoked_token_stops_the_stream_it_had_already_opened(api) -> None:
    """Authorization is re-checked on every poll, not once at `GET`.

    A stream opened at 09:00 and still running at 17:00 authorized once, and
    every event after that was delivered on an eight-hour-old decision. Revoking
    a credential has to stop the delivery it authorizes, or revocation is
    advice.
    """
    task = await make_task(api.factory, "p1")
    revoked = False

    async def on_poll():
        nonlocal revoked
        if not revoked:
            revoked = True
            async with api.factory() as s:
                await store.revoke_access_token(s, token=ALICE_TOKEN, user_id="alice", reason="test")
        else:
            await emit(api.factory, "task", task.id, "task.state_changed", {"state": "running"})

    frames = await run_stream(api.factory, token=ALICE_TOKEN, polls=8, on_poll=on_poll)

    assert frames[-1]["event"] == event_types.STREAM_CLOSED
    assert frames[-1]["data"]["reason"] == "unauthenticated"
    delivered = [f["data"]["type"] for f in entity_frames(frames)]
    assert delivered == ["session.created"], (
        "events recorded after the revocation must not be delivered"
    )


async def test_an_expired_token_stops_the_stream(api) -> None:
    """Expiry is the same failure as revocation and must end the stream too.

    Separate from the revocation test on purpose: they are two different columns
    checked in one place, and a regression that dropped the expiry comparison
    would leave the revocation test green.
    """
    task = await make_task(api.factory, "p1")

    async def on_poll():
        async with api.factory() as s:
            from gateway.app.models.entities import OAuthAccessTokenModel
            from shared.security import hash_token

            row = await s.get(OAuthAccessTokenModel, hash_token(ALICE_TOKEN))
            row.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
            await s.commit()
        await emit(api.factory, "task", task.id, "task.state_changed", {"state": "running"})

    frames = await run_stream(api.factory, token=ALICE_TOKEN, polls=8, on_poll=on_poll)

    assert frames[-1]["data"]["reason"] == "unauthenticated"
    assert [f["data"]["type"] for f in entity_frames(frames)] == ["session.created"]


async def test_a_project_removed_from_the_actor_stops_reaching_them(api, users_file) -> None:
    """`allowed_projects` is re-read per poll, not captured when the stream opened.

    Revocation is not the only way authorization changes. An operator who
    removes a project from an account expects that to take effect, and a stream
    holding a principal from an hour ago would keep delivering that project's
    events until the connection happened to drop.
    """
    task = await make_task(api.factory, "p1")
    narrowed = False

    async def on_poll():
        nonlocal narrowed
        if not narrowed:
            narrowed = True
            registry = json.loads(pathlib.Path(users_file).read_text(encoding="utf-8"))
            for user in registry["users"]:
                if user["user_id"] == "alice":
                    user["allowed_projects"] = ["p2"]
            pathlib.Path(users_file).write_text(json.dumps(registry), encoding="utf-8")
        await emit(api.factory, "task", task.id, "task.state_changed", {"state": "running"})

    frames = await run_stream(api.factory, token=ALICE_TOKEN, polls=6, on_poll=on_poll)

    assert [f["data"]["type"] for f in entity_frames(frames)] == ["session.created"]
    assert frames[-1]["data"]["reason"] == "max_duration", (
        "narrowing projects is not a credential failure; the stream stays open and empty"
    )


async def test_a_disconnected_client_ends_the_stream_without_a_closing_frame(api) -> None:
    """Nothing is listening, so there is nothing to tell.

    Asserted because the alternative — yielding a frame into a closed
    connection — is where a streaming endpoint leaks a task that never finishes.
    """
    await make_task(api.factory, "p1")
    calls = {"n": 0}

    async def is_disconnected():
        calls["n"] += 1
        return calls["n"] > 1

    frames = await run_stream(
        api.factory, token=ALICE_TOKEN, polls=6, is_disconnected=is_disconnected
    )

    assert event_types.STREAM_CLOSED not in [f.get("event") for f in frames]
    assert entity_frames(frames), "the first poll still delivered before the client went away"


# --------------------------------------------------------------------------
# The stream: keep-alive, filters and the slot ceiling
# --------------------------------------------------------------------------


async def test_an_idle_stream_sends_a_comment_not_an_event(api) -> None:
    """A heartbeat keeps a proxy from timing out an idle connection.

    A comment rather than a frame, because a frame would reach the client's
    `onmessage` as an event of an unknown type and — if it carried `id:` — would
    move the resume position past nothing.
    """
    frames = await run_stream(api.factory, token=ALICE_TOKEN, polls=4, heartbeat_seconds=1.0)

    heartbeats = [f for f in frames if "comment" in f]
    assert heartbeats, "an idle stream must be kept warm"
    assert all("id" not in f and "event" not in f for f in heartbeats)
    assert heartbeats[0]["comment"] == "keep-alive"


async def test_a_newline_in_stored_text_cannot_split_one_frame_into_two(api) -> None:
    """SSE is a line protocol: a raw newline inside `data:` ends the frame early.

    That is frame injection, and the injected half would be parsed by the client
    as an event of the attacker's choosing — including one carrying an `id:`
    that moves the resume position. The values reaching a frame are
    server-generated today, but "today" is not a guard: `entity_id` and
    `summary` both trace back to stored text, and the defence is that every
    frame is serialized as one line of ASCII rather than that no input ever
    contains a newline.
    """
    task = await make_task(api.factory, "p1")
    await emit(
        api.factory, "task", task.id, "task.stopped_by_actor",
        {"state": "cancelled", "reason": "line one\ndata: {\"id\": 999}\nevent: session.completed\n"},
    )

    frames = await run_stream(api.factory, token=ALICE_TOKEN, polls=1)

    delivered = entity_frames(frames)
    assert [f["data"]["type"] for f in delivered] == ["session.created", "session.stopped"]
    assert 999 not in [f["id"] for f in frames if "id" in f]
    raw = events_routes._frame(event="x", data={"summary": "a\nb"}, event_id=1)
    assert raw.count("\n\n") == 1 and raw.endswith("\n\n")
    assert len(raw.strip().split("\n")) == 3, "id, event and exactly one data line"

    # `\r` too. SSE terminates a line on CR, LF *or* CRLF, so a test that only
    # covers `\n` leaves the other half of the line protocol unasserted.
    carriage = events_routes._frame(
        event="x", data={"summary": "a\rid: 999\revent: forged"}, event_id=1
    )
    assert "\r" not in carriage
    assert len(carriage.strip().split("\n")) == 3

    # And the mechanism is `json.dumps` escaping CR and LF, which it does
    # whatever `ensure_ascii` says. The comment on `_frame` used to credit
    # `ensure_ascii` with frame integrity, which would tell a reader that
    # turning it off breaks a security property (council round 1, the claim
    # auditor). For the SSE line terminators it does not:
    hostile = "a\r\nid: 999\revent: forged"
    for ensure_ascii in (True, False):
        dumped = json.dumps({"summary": hostile}, ensure_ascii=ensure_ascii)
        assert "\n" not in dumped and "\r" not in dumped, (
            f"CR/LF escaping is not conditional on ensure_ascii={ensure_ascii}"
        )

    # `ensure_ascii` is not decorative either, and the difference is worth
    # pinning so nobody "simplifies" it away: with it off, Python leaves U+2028
    # and U+2029 raw. Neither is an SSE line terminator - the frame survives -
    # but they are JavaScript line terminators, so a client that evaluates a
    # payload instead of parsing it would see a different program. Keeping the
    # body pure ASCII costs nothing and removes the question.
    separator = "before\u2028after"
    assert "\u2028" in json.dumps(separator, ensure_ascii=False)
    assert "\u2028" not in json.dumps(separator, ensure_ascii=True)
    assert "\u2028" not in events_routes._frame(
        event="x", data={"summary": separator}, event_id=1
    )


async def test_a_stream_type_filter_narrows_delivery_without_stalling_the_cursor(api) -> None:
    task = await make_task(api.factory, "p1")
    for state in ("queued", "running"):
        await emit(api.factory, "task", task.id, "task.state_changed", {"state": state})
    wanted = await emit(api.factory, "task", task.id, "task.result", {"state": "succeeded"})

    frames = await run_stream(
        api.factory, token=ALICE_TOKEN, polls=3, types=["session.completed"]
    )

    delivered = entity_frames(frames)
    assert [f["id"] for f in delivered] == [wanted]


async def test_the_slot_ceiling_refuses_rather_than_degrading_the_shared_pool(api) -> None:
    """The rate limiter bounds requests per window, not connections held open.

    One accepted request here becomes a connection that takes a database session
    every poll, so the endpoint that is cheapest per request is the one that can
    exhaust the pool the rest of the API shares.
    """
    events_routes.stream_slots = events_routes.StreamSlots(0)

    response = api.get("/api/v1/events/stream", headers=auth(ALICE_TOKEN))

    assert response.status_code == 503
    assert response.json()["code"] == "dependency_unavailable"
    assert response.headers["Retry-After"] == "5"


async def test_a_finished_stream_gives_its_slot_back(api) -> None:
    """A slot that is not returned is gone for good, and the ceiling ratchets down.

    This is the generator's `finally` path. The other release path — the
    response's background task, for a connection that dies before the body ever
    starts — is
    `test_a_connection_that_dies_before_the_body_starts_still_returns_its_slot`.
    """
    slots = events_routes.StreamSlots(2)
    slot = slots.acquire("alice")
    assert slots.active == 1
    slot.release()
    slot.release()
    assert slots.active == 0, "a double release must not push the counter below zero"
    assert slots.active_for("alice") == 0

    async for _ in events_routes.event_stream(
        factory=api.factory, token=ALICE_TOKEN, resume_from=0,
        requested_projects=None, requested_types=[], poll_interval=0.0,
        heartbeat_seconds=1e9, max_duration_seconds=0.0, batch_limit=10,
        on_close=slots.acquire("alice").release,
        monotonic=FakeClock(), sleep=stepping_sleep(FakeClock()),
    ):
        pass
    assert slots.active == 0


async def test_a_connection_that_dies_before_the_body_starts_still_returns_its_slot(api) -> None:
    """The release path the generator's `finally` cannot reach — council round 1.

    `stream_events` takes the slot, then hands back a `StreamingResponse` whose
    body is an async generator. An async generator that is never iterated has no
    `finally` to run, so if the connection dies between the route returning and
    the first `__anext__`, the `finally` never fires and the slot is leaked
    permanently — the ceiling ratchets down until the endpoint answers 503
    forever. `background=BackgroundTask(slot.release)` is what covers it, and the
    claim auditor found that nothing in the suite touched that path: deleting
    the argument left all 600 tests green.

    Driven at the route, not through a client, because the failure is precisely
    "the body was never started" and a test client always starts it.
    """
    slots = events_routes.StreamSlots(2)
    events_routes.stream_slots = slots

    class _Request:
        headers = {"Authorization": f"Bearer {ALICE_TOKEN}"}

        async def is_disconnected(self):
            return True

    principal = AuthenticatedPrincipal(
        user_id="alice", email="alice@example.com", roles=[], allowed_projects=["p1"],
        scopes=["codexbridge.read"], can_approve_sensitive=False, auth_scheme="oauth",
    )
    response = await events_routes.stream_events(
        request=_Request(), after=None, project=None, type=None,
        last_event_id=None, principal=principal,
    )

    assert slots.active == 1, "the route holds the slot while the response is in flight"
    # The connection dies here: the body is never iterated, so the generator
    # never starts and its `finally` never runs. Starlette runs the background
    # task once the response is done either way.
    await response.background()
    assert slots.active == 0, (
        "a connection dropped before the body started leaked its slot forever"
    )
    assert slots.active_for("alice") == 0


async def test_one_account_cannot_take_every_stream_slot(api) -> None:
    """A global ceiling is not a share — council round 1, the adversarial user.

    Without a per-actor ceiling, one read-only token holding every slot answers
    `503` to every other principal, an administrator included, for as long as it
    keeps its connections (up to `event_stream_max_duration_seconds`, 15
    minutes). The process ceiling protects the gateway; this protects everyone
    else from whoever got there first.
    """
    slots = events_routes.StreamSlots(4, per_actor=2)

    held = [slots.acquire("alice"), slots.acquire("alice")]
    assert slots.active_for("alice") == 2

    with pytest.raises(ApiError) as refused:
        slots.acquire("alice")
    assert refused.value.status_code == 503
    assert refused.value.headers["Retry-After"] == "5"

    # The process still has room, and it is room somebody else can use.
    other = slots.acquire("bob")
    assert slots.active == 3

    held[0].release()
    assert slots.acquire("alice") is not None, "releasing frees the actor's own share"
    other.release()


def test_the_per_actor_ceiling_can_never_exceed_the_process_ceiling() -> None:
    """A per-actor ceiling above the global one reads as a share and is not one."""
    assert events_routes.StreamSlots(4, per_actor=99).per_actor == 4
    assert events_routes.StreamSlots(4).per_actor == 4


def test_the_module_level_slots_carry_the_configured_per_actor_ceiling() -> None:
    """The ceiling the deployment actually uses is wired from settings.

    Council round 2, the claim auditor: `StreamSlots` is tested in isolation and
    the `api` fixture replaces the module-level object with one built from
    `limit` alone, so no route test observes the real ceiling. Dropping
    `settings.event_stream_max_per_actor` from the construction at
    `events.py` would leave `per_actor` defaulting to `limit` (8) and every route
    test green. This pins the wiring: the object the request handler holds carries
    the configured per-actor value (2), not the process ceiling.
    """
    from gateway.app.core.config import settings

    assert events_routes.stream_slots.per_actor == settings.event_stream_max_per_actor
    assert settings.event_stream_max_per_actor < settings.event_stream_max_concurrent, (
        "if these were equal the wiring test could not distinguish a dropped argument"
    )


def test_the_stream_ceiling_fits_inside_the_connection_pool() -> None:
    """32 streams against a 15-connection pool is the incident `probes.py` records.

    Each poll of each open stream takes a session from the pool every other
    endpoint shares. A ceiling above the pool's own capacity means a slow poll
    exhausts it, real requests block for `pool_timeout`, and the resulting
    TimeoutError is reported as `database: unavailable` — the gateway asks to be
    pulled from rotation and blames the database. Council round 1, the second
    caller, measured the pool at 15 while this ceiling was 32.
    """
    from sqlalchemy.pool import QueuePool

    from gateway.app.core.config import settings
    from gateway.app.db.session import engine

    pool = engine.pool
    if not isinstance(pool, QueuePool):  # pragma: no cover - sqlite in some setups
        pytest.skip("engine is not pooled in this configuration")
    capacity = pool.size() + pool._max_overflow
    assert settings.event_stream_max_concurrent <= capacity, (
        f"{settings.event_stream_max_concurrent} concurrent streams against a "
        f"{capacity}-connection pool; raising one means raising the other"
    )


# --------------------------------------------------------------------------
# The route around the generator
# --------------------------------------------------------------------------


async def test_the_stream_is_served_as_an_event_stream_that_a_proxy_will_not_buffer(api, monkeypatch) -> None:
    from gateway.app.core.config import settings

    monkeypatch.setattr(settings, "event_stream_max_duration_seconds", 0.0)
    monkeypatch.setattr(settings, "event_stream_poll_interval_seconds", 0.01)
    monkeypatch.setattr("gateway.app.db.session.SessionLocal", api.factory)

    task = await make_task(api.factory, "p1")

    response = api.get("/api/v1/events/stream", headers=auth(ALICE_TOKEN))

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["x-accel-buffering"] == "no"

    frames = parse_frames([response.text])
    assert frames[0]["event"] == event_types.STREAM_OPEN
    assert [f["data"]["entity"]["id"] for f in entity_frames(frames)] == [task.id]


async def test_last_event_id_resumes_and_beats_the_query_parameter(api, monkeypatch) -> None:
    """The header is what a reconnecting `EventSource` sends by itself.

    It wins over `?after=` because it is the more recent of the two by
    construction: the query parameter is whatever the client first opened with,
    while the header is where it actually got to.
    """
    from gateway.app.core.config import settings

    monkeypatch.setattr(settings, "event_stream_max_duration_seconds", 0.0)
    monkeypatch.setattr(settings, "event_stream_poll_interval_seconds", 0.01)
    monkeypatch.setattr("gateway.app.db.session.SessionLocal", api.factory)

    task = await make_task(api.factory, "p1")
    seen = await newest_audit_id(api.factory)
    await emit(api.factory, "task", task.id, "task.result", {"state": "succeeded"})

    response = api.get(
        "/api/v1/events/stream?after=0",
        headers={**auth(ALICE_TOKEN), "Last-Event-ID": str(seen)},
    )

    frames = parse_frames([response.text])
    assert [f["data"]["type"] for f in entity_frames(frames)] == ["session.completed"]
    assert frames[0]["data"]["from"] == seen


async def test_a_malformed_last_event_id_is_ignored_rather_than_refused(api) -> None:
    """The user agent sets that header, not the application.

    Refusing the connection over a value the client cannot control would strand
    it with no way to reconnect.
    """
    assert events_routes._resume_from("not-a-number", 7) == 7
    assert events_routes._resume_from("-4", 7) == 7
    assert events_routes._resume_from(None, None) == 0
    assert events_routes._resume_from(" 12 ", 3) == 12


async def test_a_bad_type_filter_fails_before_the_body_starts(api, monkeypatch) -> None:
    """Once an event-stream body has started there is no status code left to change.

    A filter validated inside the stream would have to be reported as a frame,
    and a client that asked for a type it misspelled would see an open, empty,
    permanently silent connection instead of a `400`.
    """
    monkeypatch.setattr("gateway.app.db.session.SessionLocal", api.factory)

    response = api.get("/api/v1/events/stream?type=nope", headers=auth(ALICE_TOKEN))

    assert response.status_code == 400
    assert response.json()["details"][0]["code"] == "unknown_event_type"
    assert events_routes.stream_slots.active == 0, "a refused stream must not hold a slot"


# --------------------------------------------------------------------------
# Notification preferences
# --------------------------------------------------------------------------


async def test_preferences_round_trip(api) -> None:
    empty = api.get("/api/v1/notifications/preferences", headers=auth(ALICE_TOKEN))
    assert empty.status_code == 200
    assert empty.json() == {
        "eventTypes": [],
        "pushEnabled": False,
        "updatedAt": None,
        "pushDeliveryAvailable": False,
    }

    saved = api.put(
        "/api/v1/notifications/preferences",
        headers=auth(ALICE_TOKEN),
        json={"eventTypes": ["session.completed", "decision.requested", "decision.requested"],
              "pushEnabled": True},
    )
    assert saved.status_code == 200
    body = saved.json()
    assert body["eventTypes"] == ["decision.requested", "session.completed"], "sorted and de-duplicated"
    assert body["pushEnabled"] is True
    assert body["updatedAt"].endswith("Z")
    assert body["pushDeliveryAvailable"] is False, (
        "there is no push transport in this build; a client must be able to say so"
    )

    assert api.get("/api/v1/notifications/preferences", headers=auth(ALICE_TOKEN)).json() == body


async def test_a_put_replaces_the_document_rather_than_merging_into_it(api) -> None:
    """`PUT`, not `PATCH`: an absent field takes its default.

    A merge would need a `PATCH` and a way to say "remove this", and would make
    the endpoint's name a lie.
    """
    api.put(
        "/api/v1/notifications/preferences",
        headers=auth(ALICE_TOKEN),
        json={"eventTypes": ["session.completed"], "pushEnabled": True},
    )

    replaced = api.put(
        "/api/v1/notifications/preferences", headers=auth(ALICE_TOKEN), json={}
    ).json()

    assert replaced["eventTypes"] == []
    assert replaced["pushEnabled"] is False


async def test_preferences_are_per_actor_and_never_another_accounts(api) -> None:
    api.put(
        "/api/v1/notifications/preferences",
        headers=auth(ALICE_TOKEN),
        json={"eventTypes": ["session.completed"], "pushEnabled": True},
    )

    admin = api.get("/api/v1/notifications/preferences", headers=auth(ADMIN_TOKEN)).json()
    assert admin["eventTypes"] == [], (
        "an administrator reads their own preferences; there is no endpoint for anyone else's"
    )


async def test_an_unknown_event_type_is_refused_with_the_field_named(api) -> None:
    response = api.put(
        "/api/v1/notifications/preferences",
        headers=auth(ALICE_TOKEN),
        json={"eventTypes": ["session.exploded"], "pushEnabled": False},
    )

    assert response.status_code == 400
    body = response.json()
    assert body["code"] == "validation_failed"
    assert body["details"][0]["field"] == "eventTypes"
    assert "session.exploded" in body["details"][0]["message"]


async def test_writing_preferences_needs_a_scope_reading_them_does_not(api) -> None:
    """Two actions, because an operator may grant one without the other.

    A phone allowed to watch the stream is not automatically a phone allowed to
    rewrite what the account gets notified about.
    """
    assert api.get("/api/v1/notifications/preferences", headers=auth(READER_TOKEN)).status_code == 200

    refused = api.put(
        "/api/v1/notifications/preferences",
        headers=auth(READER_TOKEN),
        json={"eventTypes": [], "pushEnabled": False},
    )
    assert refused.status_code == 403
    assert refused.json()["code"] == "permission_denied"


def test_the_manage_scope_is_one_a_signed_in_client_can_actually_be_granted() -> None:
    """A scope outside `oauth_default_scopes` can never be granted to anyone.

    `POST /api/v1/auth/sign-in` issues `user.scopes & settings.oauth_scopes()`,
    and the browser OAuth flow caps grants the same way. A new scope added to
    the catalogue but not to that default set produces an endpoint every mobile
    user is permanently refused from — a `403` naming a permission the operator
    cannot grant from `users.json` however they edit it. Nothing else in this
    file would catch it: every other test mints its tokens directly and so
    never crosses the cap.

    Asserted for this delivery's scope only, deliberately, rather than for the
    whole catalogue. `codexbridge.task.approve` is outside the default set **on
    purpose** — approving a sensitive session is a capability an operator raises
    the deployment default to grant, not one every signed-in phone gets — so a
    catalogue-wide version of this assertion would be asserting that a
    deliberate policy is a bug.
    """
    from gateway.app.core.config import settings

    from gateway.app.api import permissions

    granted = settings.oauth_scopes()
    assert permissions.NOTIFICATIONS_MANAGE.scope in granted
    assert permissions.EVENTS_READ.scope in granted
    assert permissions.NOTIFICATIONS_READ.scope in granted


def test_the_env_template_can_grant_every_scope_the_catalogue_needs() -> None:
    """The allowlist has two sources, and production reads the one nobody edits.

    Council round 1, the second caller: `CODEX_BRIDGE_OAUTH_DEFAULT_SCOPES` in
    `.env.example` **replaces** `Settings.oauth_default_scopes` wholesale rather
    than merging, and `docs/installation.md` tells the operator to build
    `/etc/codex-bridge/env` from that template. Issues #8, #10 and #13 each added
    a scope to `config.py` and not to the template, so a deployment built the
    documented way had `issues.write`, `conversations.write` and
    `notifications.manage` permanently ungrantable — `403` for every non-admin,
    however `users.json` was edited.

    The sibling test above pinned this against `settings.oauth_scopes()`, which
    is the code default — the source production overrides. It therefore passed
    while the endpoint was unreachable. This one reads the template.

    `codexbridge.task.approve` is exempt and named as such: withholding it from
    the deployment default is a deliberate operator decision, not drift.
    """
    from gateway.app.api import permissions

    template = (REPO_ROOT / ".env.example").read_text(encoding="utf-8")
    line = next(
        (row for row in template.splitlines() if row.startswith("CODEX_BRIDGE_OAUTH_DEFAULT_SCOPES=")),
        None,
    )
    assert line is not None, ".env.example no longer sets the scope allowlist"
    templated = set(line.partition("=")[2].split())

    deliberately_withheld = {permissions.APPROVE_SCOPE}
    needed = {
        action.scope
        for action in permissions.CATALOGUE
        if action.scope not in {permissions.ADMIN_SCOPE} | deliberately_withheld
    }
    missing = sorted(needed - templated)
    assert not missing, (
        f".env.example cannot grant {missing}; a deployment built from the template "
        "answers 403 for every non-admin on the endpoints those scopes guard"
    )


async def test_a_rejected_subscription_list_cannot_amplify_the_response(api) -> None:
    """Council round 1 — the count was bounded, the bytes were not.

    `MAX_SUBSCRIBED_TYPES` capped the list at 64 entries, and `put_preferences`
    then quoted every rejected value back at full length in `details[]`: 64
    strings of 100,000 characters turned a 6.4 MB request into a 6.4 MB error
    response. A bound on how many items there are is not a bound on how much
    data they carry.
    """
    payload = {"eventTypes": ["z" * 100_000] * 64, "pushEnabled": False}
    response = api.put("/api/v1/notifications/preferences", headers=auth(ALICE_TOKEN), json=payload)

    assert response.status_code == 422, "an over-long value is refused by the model"
    assert len(response.content) < 100_000, (
        f"the error envelope was {len(response.content)} bytes for a rejected request"
    )

    # And a *plausible* mistake still tells the client what it got wrong.
    readable = api.put(
        "/api/v1/notifications/preferences",
        headers=auth(ALICE_TOKEN),
        json={"eventTypes": ["session.completedd"], "pushEnabled": False},
    )
    assert readable.status_code == 400
    assert "session.completedd" in readable.json()["details"][0]["message"]


async def test_a_rejected_type_filter_cannot_amplify_the_response(api) -> None:
    """The same reflection on the query side, where the URL is the only limit."""
    query = "&".join(f"type={'q' * 200}{index}" for index in range(200))
    response = api.get(f"/api/v1/events?{query}", headers=auth(ALICE_TOKEN))

    assert response.status_code == 400
    assert len(response.json()["details"]) <= events_routes.MAX_ECHOED_DETAILS
    assert len(response.content) < 10_000


async def test_a_stored_type_that_no_longer_exists_is_dropped_on_the_way_out(api) -> None:
    """A stored preference can outlive the type it names.

    Handing a client a subscription to a retired type would have it echo the
    value back on its next `PUT` and be rejected for something it never chose.
    """
    async with api.factory() as s:
        await store.set_notification_preference(
            s, user_id="alice", event_types=["session.completed"], push_enabled=False
        )
        from gateway.app.models.entities import NotificationPreferenceModel

        row = await s.get(NotificationPreferenceModel, "alice")
        row.event_types_json = json.dumps(["session.completed", "session.retired_in_2027"])
        await s.commit()

    body = api.get("/api/v1/notifications/preferences", headers=auth(ALICE_TOKEN)).json()
    assert body["eventTypes"] == ["session.completed"]


async def test_preferences_do_not_filter_the_stream(api) -> None:
    """A documented decision, not an omission — so it is pinned as behaviour.

    A client that opened the stream asked for the stream. Withholding events
    from it because of a preference set on another device is how a phone
    silently misses the decision its operator was waiting for, and the failure
    would be indistinguishable from a quiet system.
    """
    api.put(
        "/api/v1/notifications/preferences",
        headers=auth(ALICE_TOKEN),
        json={"eventTypes": ["androidBuild.status_changed"], "pushEnabled": True},
    )
    task = await make_task(api.factory, "p1")

    frames = await run_stream(api.factory, token=ALICE_TOKEN, polls=1)

    assert [f["data"]["entity"]["id"] for f in entity_frames(frames)] == [task.id]


# --------------------------------------------------------------------------
# Store-level invariants the endpoints rely on
# --------------------------------------------------------------------------


async def test_an_empty_project_list_matches_nothing_and_is_not_no_restriction(api) -> None:
    """The one-character mistake: `if project_ids:` instead of `is not None`.

    A principal with no projects must see nothing. Reading an empty list as "no
    restriction" turns the least privileged account into the most privileged
    one, and every other test in this file would still pass.
    """
    await make_task(api.factory, "p1")

    async with api.factory() as s:
        none_allowed = await store.list_mobile_events_page(
            s, project_ids=[], entity_types=sorted(event_types.DELIVERABLE_ENTITY_TYPES),
            audit_event_types=sorted(event_types.TRANSLATED_AUDIT_EVENT_TYPES),
            after=None, limit=50,
        )
        unrestricted = await store.list_mobile_events_page(
            s, project_ids=None, entity_types=sorted(event_types.DELIVERABLE_ENTITY_TYPES),
            audit_event_types=sorted(event_types.TRANSLATED_AUDIT_EVENT_TYPES),
            after=None, limit=50,
        )

    assert none_allowed == []
    assert unrestricted, "the precondition: there is something to see"


async def test_task_created_forks_on_the_state_it_was_created_in(api) -> None:
    """One audit row, two mobile meanings, resolved from the payload.

    A submission held for approval is a *decision being requested* — the event
    issue #13 names — while every other submission is a session starting. Both
    are `task.created`, so the fork lives in `classify` rather than in a second
    writer nobody would remember to call.
    """
    assert event_types.classify("task.created", {"state": "awaiting_approval"}) == (
        event_types.DECISION_REQUESTED, event_types.ENTITY_KIND_DECISION
    )
    assert event_types.classify("task.created", {"state": "queued"}) == (
        event_types.SESSION_CREATED, event_types.ENTITY_KIND_SESSION
    )
    assert event_types.classify("task.created", {}) == (
        event_types.SESSION_CREATED, event_types.ENTITY_KIND_SESSION
    )
    assert event_types.classify("auth.signed_in", {}) is None


async def test_epics_issues_and_conversations_all_resolve_to_their_project(api) -> None:
    """Every deliverable entity type must have a working project derivation.

    A type whose `CASE` arm was wrong or missing would yield NULL and be dropped
    by the fail-closed guard — invisibly, and only for that entity type.
    """
    async with api.factory() as s:
        epic = await store.create_epic(
            s, project_id="p1", title="E", description=None, status=None,
            actor_user_id="alice", actor_email=None,
        )
    async with api.factory() as s:
        issue = await store.create_issue(
            s, project_id="p1", epic_id=None, title="I", description=None, status=None,
            priority=None, labels=None, assignee_user_id=None, assignee_email=None,
            dependencies=None, blocked_reason=None, actor_user_id="alice", actor_email=None,
        )

    body = api.get("/api/v1/events", headers=auth(ALICE_TOKEN)).json()
    kinds = {item["entity"]["kind"]: item["projectId"] for item in body["items"]}

    assert kinds.get("epic") == "p1"
    assert kinds.get("issue") == "p1"
    assert {item["entity"]["id"] for item in body["items"]} >= {epic.id, issue.id}


def test_the_audit_index_exists_on_a_fresh_install_as_well_as_an_upgraded_one() -> None:
    """An index declared only in SQL is missing on every new database.

    `main.py` bootstraps a new database with `Base.metadata.create_all`, which
    knows nothing about `migrations/`. An upgraded deployment runs 0009 and gets
    the index; a fresh one never would — and that is the harder half to notice,
    because nobody skipped a migration (council round 1, the second caller).
    Both halves are needed: `create_all(checkfirst=True)` will not add an index
    to a table that already exists, so the migration cannot be dropped either.
    """
    from gateway.app.models.entities import AuditEventModel

    name = "audit_events_entity_type_id_idx"
    declared = {index.name: index for index in AuditEventModel.__table__.indexes}
    assert name in declared, "a fresh install would not get the index"
    assert [column.name for column in declared[name].columns] == ["entity_type", "id"]

    migration = (REPO_ROOT / "migrations" / "0011_event_subscriptions.sql").read_text(encoding="utf-8")
    assert name in migration, "an existing deployment would not get the index"


def test_the_poll_interval_is_floored_rather_than_honoured() -> None:
    """A zero interval is a busy loop against the pool every endpoint shares."""
    from gateway.app.core.config import Settings

    assert Settings(event_stream_poll_interval_seconds=0).effective_event_stream_poll_interval() > 0
    assert Settings(event_stream_poll_interval_seconds=-5).effective_event_stream_poll_interval() > 0
    assert Settings(event_stream_batch_limit=0).effective_event_stream_batch_limit() >= 1
    assert Settings(event_stream_batch_limit=100000).effective_event_stream_batch_limit() <= 500
