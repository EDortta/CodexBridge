"""Representative-endpoint compliance for the cross-cutting API rules (issue #12).

No `/api` endpoint exists yet — #3 and #9 add the first ones. The machinery is
nevertheless exercised against real endpoints here, because a helper that is only
unit-tested proves that the function works, not that a request passing through
FastAPI's middleware stack and exception handlers comes out shaped the way the
contract says. The representative app below is deliberately built the same way
the gateway builds itself: same middleware, same handlers, same scope predicate.

The `test_mcp_*` cases guard the other direction: these rules must NOT reach the
JSON-RPC transport ChatGPT already uses.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from fastapi import FastAPI, Header, HTTPException
from fastapi.testclient import TestClient
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from gateway.app.api import concurrency, idempotency, pagination
from gateway.app.api.idempotency import Claim
from gateway.app.api.errors import ApiError
from gateway.app.api.request_context import REQUEST_ID_HEADER
from gateway.app.api.setup import install_api_conventions
from gateway.app.db.base import Base
from gateway.app.models.entities import IdempotencyRecordModel


# --------------------------------------------------------------------------
# A representative contract app: one read, one paginated list, one guarded
# write, plus the two failure modes no handler writes by hand.
# --------------------------------------------------------------------------


class ApproveBody(BaseModel):
    reason: str


def build_app() -> FastAPI:
    app = FastAPI(openapi_url=None, docs_url=None, redoc_url=None)
    install_api_conventions(app)

    state = {"revision": 7}

    @app.get("/api/v1/things")
    async def list_things(cursor: str | None = None, limit: int | None = None):
        scope = pagination.scope_digest("/api/v1/things", {"project": None})
        start = (
            pagination.decode_cursor(scope, cursor, expect={"after": int})["after"] if cursor else 0
        )
        size = pagination.parse_limit(limit)
        rows = list(range(start, min(start + size + 1, 10)))
        page, info = pagination.paginate(
            rows, limit=size, scope=scope, position_of=lambda row: {"after": row + 1}
        )
        return {"items": page, "page": info}

    @app.post("/api/v1/things/{thing_id}/approve")
    async def approve(thing_id: str, body: ApproveBody, if_match: str | None = Header(default=None)):
        concurrency.require_if_match(if_match, state["revision"])
        state["revision"] += 1
        return {"id": thing_id, "revision": state["revision"], "reason": body.reason}

    @app.get("/api/v1/missing")
    async def missing():
        raise HTTPException(status_code=404, detail="No such thing.")

    @app.get("/api/v1/boom")
    async def boom():
        raise RuntimeError("driver said: connection to host 10.0.0.5:5432 failed")

    @app.get("/api/v1/limited")
    async def limited():
        raise ApiError(status_code=429, code="rate_limited", message="Slow down.", headers={"Retry-After": "30"})

    # Outside the contract surface: must keep FastAPI's own shape.
    @app.get("/mcp-like")
    async def mcp_like():
        raise HTTPException(status_code=403, detail="invalid_bearer_token")

    @app.get("/mcp-like-boom")
    async def mcp_like_boom():
        raise RuntimeError("unhandled outside the contract surface")

    return app


@pytest.fixture
def client() -> TestClient:
    return TestClient(build_app(), raise_server_exceptions=False)


@pytest.fixture
async def db_session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        yield session
    await engine.dispose()


# --------------------------------------------------------------------------
# Request identifier
# --------------------------------------------------------------------------


def test_request_id_is_generated_and_echoed(client: TestClient) -> None:
    response = client.get("/api/v1/things")
    assert response.headers[REQUEST_ID_HEADER]
    assert response.status_code == 200


def test_client_request_id_is_honoured(client: TestClient) -> None:
    response = client.get("/api/v1/missing", headers={REQUEST_ID_HEADER: "mobile-42"})
    assert response.headers[REQUEST_ID_HEADER] == "mobile-42"
    assert response.json()["requestId"] == "mobile-42"


def test_hostile_request_id_is_replaced_not_echoed(client: TestClient) -> None:
    """The header is written into response headers and log lines.

    Echoing arbitrary client bytes there is a header-injection and log-forging
    primitive, so a value that is not a valid `Id` is discarded.
    """
    hostile = "abc def <script>"
    response = client.get("/api/v1/missing", headers={REQUEST_ID_HEADER: hostile})
    assert response.headers[REQUEST_ID_HEADER] != hostile
    assert response.json()["requestId"] != hostile


def test_request_ids_differ_between_requests(client: TestClient) -> None:
    first = client.get("/api/v1/missing").json()["requestId"]
    second = client.get("/api/v1/missing").json()["requestId"]
    assert first != second


# --------------------------------------------------------------------------
# Error envelope
# --------------------------------------------------------------------------


REQUIRED_ERROR_FIELDS = {"code", "message", "requestId", "retryable"}


def test_validation_failure_uses_the_envelope(client: TestClient) -> None:
    response = client.post(
        "/api/v1/things/t1/approve", json={}, headers={"If-Match": '"7"'}
    )
    body = response.json()
    assert response.status_code == 422
    assert REQUIRED_ERROR_FIELDS <= body.keys()
    assert body["code"] == "validation_failed"
    assert body["retryable"] is False
    assert body["details"], "validation errors must name the offending field"
    assert body["details"][0]["field"] == "/reason"


def test_http_exception_inside_contract_path_uses_the_envelope(client: TestClient) -> None:
    response = client.get("/api/v1/missing")
    body = response.json()
    assert response.status_code == 404
    assert body["code"] == "not_found"
    assert body["retryable"] is False
    assert "detail" not in body


def test_unhandled_exception_returns_envelope_without_leaking_detail(client: TestClient) -> None:
    """A raw driver error names hosts, ports and schema. It stays in the log."""
    response = client.get("/api/v1/boom")
    body = response.json()
    assert response.status_code == 500
    assert body["code"] == "internal_error"
    assert body["retryable"] is True
    serialized = response.text
    assert "10.0.0.5" not in serialized
    assert "RuntimeError" not in serialized
    assert "Traceback" not in serialized


def test_rate_limited_carries_retry_after(client: TestClient) -> None:
    response = client.get("/api/v1/limited")
    assert response.status_code == 429
    assert response.headers["Retry-After"] == "30"
    assert response.json()["retryable"] is True


def test_non_contract_path_keeps_framework_error_shape(client: TestClient) -> None:
    """`POST /mcp` speaks JSON-RPC; reshaping it would break the live client."""
    response = client.get("/mcp-like")
    assert response.status_code == 403
    assert response.json() == {"detail": "invalid_bearer_token"}


def test_real_gateway_leaves_mcp_error_shape_untouched() -> None:
    from gateway.app.main import app as gateway_app

    with TestClient(gateway_app, raise_server_exceptions=False) as gateway_client:
        response = gateway_client.post("/mcp", json={"method": "tools/list"})
    assert response.status_code in {401, 403}
    assert "detail" in response.json()
    assert "requestId" not in response.json()


# --------------------------------------------------------------------------
# Pagination
# --------------------------------------------------------------------------


def test_pagination_walks_every_item_exactly_once(client: TestClient) -> None:
    seen: list[int] = []
    cursor = None
    for _ in range(10):
        params = {"limit": 3}
        if cursor:
            params["cursor"] = cursor
        body = client.get("/api/v1/things", params=params).json()
        seen.extend(body["items"])
        cursor = body["page"]["nextCursor"]
        if not body["page"]["hasMore"]:
            break
    assert seen == list(range(10))
    assert cursor is None


def test_next_cursor_is_null_exactly_when_there_is_no_more(client: TestClient) -> None:
    body = client.get("/api/v1/things", params={"limit": 100}).json()
    assert body["page"]["hasMore"] is False
    assert body["page"]["nextCursor"] is None


def test_cursor_from_another_scope_is_rejected(client: TestClient) -> None:
    """A cursor is single-purpose; reinterpreting one pages through wrong rows."""
    foreign = pagination.encode_cursor(
        pagination.scope_digest("/api/v1/other", {}), {"after": 3}
    )
    response = client.get("/api/v1/things", params={"cursor": foreign})
    assert response.status_code == 400
    assert response.json()["code"] == "validation_failed"


@pytest.mark.parametrize(
    ("cursor", "expected"),
    [
        ("not-base64!!", 400),          # undecodable
        ("eyJub3RhbWFwIjoxfQ", 400),    # decodes, but is not a cursor envelope
        ("eyJzIjoiZGVhZGJlZWYiLCJwIjp7fX0", 400),  # well formed, wrong scope
        ("", 200),                      # absent and empty mean the same thing
    ],
)
def test_malformed_cursor_is_rejected(client: TestClient, cursor: str, expected: int) -> None:
    """Every rejection collapses to one message on purpose.

    Distinguishing "malformed" from "valid but issued elsewhere" would describe
    server state to someone holding a token they were never given.
    """
    response = client.get("/api/v1/things", params={"cursor": cursor})
    assert response.status_code == expected
    if expected == 400:
        assert response.json()["code"] == "validation_failed"


def test_limit_above_maximum_is_clamped_not_rejected() -> None:
    assert pagination.parse_limit(10_000) == pagination.MAX_LIMIT


def test_limit_below_one_is_rejected() -> None:
    with pytest.raises(ApiError) as raised:
        pagination.parse_limit(0)
    assert raised.value.code == "validation_failed"


def test_page_info_never_advertises_a_cursor_without_more() -> None:
    """The contract binds these two fields; building them apart lets them drift."""
    assert pagination.page_info(has_more=False, next_cursor="something") == {
        "hasMore": False,
        "nextCursor": None,
    }


# --------------------------------------------------------------------------
# Optimistic concurrency
# --------------------------------------------------------------------------


def test_write_without_if_match_is_refused(client: TestClient) -> None:
    response = client.post("/api/v1/things/t1/approve", json={"reason": "ok"})
    assert response.status_code == 428
    assert response.json()["code"] == "validation_failed"


def test_write_with_stale_if_match_reports_stale_write(client: TestClient) -> None:
    response = client.post(
        "/api/v1/things/t1/approve", json={"reason": "ok"}, headers={"If-Match": '"3"'}
    )
    assert response.status_code == 412
    assert response.json()["code"] == "stale_write"
    assert response.json()["retryable"] is False
    assert response.headers["ETag"] == '"7"'


def test_second_of_two_concurrent_approvals_loses(client: TestClient) -> None:
    """The scenario the feature exists for: two operators, two devices."""
    headers = {"If-Match": '"7"'}
    first = client.post("/api/v1/things/t1/approve", json={"reason": "first"}, headers=headers)
    second = client.post("/api/v1/things/t1/approve", json={"reason": "second"}, headers=headers)
    assert first.status_code == 200
    assert second.status_code == 412
    assert second.json()["code"] == "stale_write"


def test_if_match_star_is_accepted(client: TestClient) -> None:
    response = client.post(
        "/api/v1/things/t1/approve", json={"reason": "ok"}, headers={"If-Match": "*"}
    )
    assert response.status_code == 200


def test_strong_validator_matches_and_wrong_revision_does_not() -> None:
    concurrency.require_if_match('"7"', 7)
    with pytest.raises(ApiError) as raised:
        concurrency.require_if_match('"6"', 7)
    assert raised.value.code == "stale_write"


def test_weak_validator_never_matches() -> None:
    """RFC 9110 requires strong comparison for If-Match.

    A weak tag asserts *semantic* equivalence — and "semantically equivalent" is
    exactly what a second operator's approval of the same decision is. Accepting
    `W/"7"` as `"7"` would be lenient in the one place leniency defeats the
    feature.
    """
    with pytest.raises(ApiError) as raised:
        concurrency.require_if_match('W/"7"', 7)
    assert raised.value.code == "stale_write"


def test_if_match_list_matches_when_any_member_is_current() -> None:
    concurrency.require_if_match('"5", "7", "9"', 7)
    with pytest.raises(ApiError):
        concurrency.require_if_match('"5", "9"', 7)


async def test_task_revision_advances_on_every_mutation(db_session) -> None:
    """Every mutator, not a sample of them.

    The first version of this test asserted two of the four and passed, which is
    why the claim "bumped by every mutator" survived while
    `recover_tasks_after_startup` — the one that runs unattended, on every
    restart, and moves a task to `lost` — did not bump at all. A client holding
    the pre-restart ETag then passed `If-Match` against a changed entity: the
    exact stale write the column exists to catch.
    """
    from gateway.app.services import store
    from shared.protocol import (
        ApprovalDecision,
        ExecutorRegistration,
        ProjectRegistration,
        SubmitTaskRequest,
        TaskMode,
        TaskPriority,
        TaskState,
    )

    await store.upsert_registry(
        db_session,
        executors=[
            ExecutorRegistration(
                executor_id="E1",
                display_name="E1",
                machine_token="t",
                allowed_projects=["p1"],
                enabled=True,
            )
        ],
        projects=[
            ProjectRegistration(
                project_id="p1",
                name="P1",
                path="/tmp/p1",
                allowed_modes=[TaskMode.ANALYZE, TaskMode.IMPLEMENT],
                max_timeout_seconds=600,
                sensitive_patterns=["deploy"],
                enabled=True,
            )
        ],
    )

    async def new_task(instruction: str) -> object:
        return await store.create_task(
            db_session,
            SubmitTaskRequest(
                executor_id="E1",
                project_id="p1",
                instruction=instruction,
                mode=TaskMode.IMPLEMENT,
                priority=TaskPriority.NORMAL,
                timeout_seconds=60,
                expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
            ),
            executor_online=True,
        )

    # 1. decide_task_approval — moves approval_state, and no timestamp a reader sees.
    task = await new_task("deploy the thing")
    assert task.revision == 1
    decided = await store.decide_task_approval(db_session, task.id, ApprovalDecision.APPROVED)
    assert decided.revision == 2
    assert concurrency.etag_for(decided.revision) != concurrency.etag_for(1)

    # 2. update_task_state
    running = await store.update_task_state(db_session, task.id, TaskState.RUNNING)
    assert running.revision == 3

    # 3. store_result
    finished = await store.store_result(db_session, task.id, {"ok": True}, TaskState.COMPLETED)
    assert finished.revision == 4

    # 4. recover_tasks_after_startup — the unattended one, previously unbumped.
    other = await new_task("analyze the thing")
    await store.update_task_state(db_session, other.id, TaskState.RUNNING)
    before = (await store.get_task(db_session, other.id)).revision
    await store.recover_tasks_after_startup(db_session)
    recovered = await store.get_task(db_session, other.id)
    assert recovered.state == TaskState.LOST.value
    assert recovered.revision > before, (
        "recovery changed state without changing the validator: a stale If-Match "
        "would be accepted against a task that moved to lost"
    )

    # Recovery is unattended, so its audit trail is the only record that the
    # state moved at all. The other three mutators record one; this one did not.
    from sqlalchemy import select

    from gateway.app.models.entities import AuditEventModel

    events = (
        await db_session.execute(
            select(AuditEventModel.event_type).where(AuditEventModel.entity_id == other.id)
        )
    ).scalars().all()
    assert "task.recovered" in events


# --------------------------------------------------------------------------
# Idempotency
# --------------------------------------------------------------------------


IDEM_ARGS = {"key": "k-1", "endpoint": "/api/v1/things/t1/approve", "actor_id": "alice"}


async def test_first_request_has_nothing_to_replay(db_session) -> None:
    assert await idempotency.lookup(db_session, request_fingerprint="fp", **IDEM_ARGS) is None


async def test_retry_replays_the_stored_response(db_session) -> None:
    await idempotency.remember(
        db_session, request_fingerprint="fp", status_code=200, body={"id": "t1"}, **IDEM_ARGS
    )
    replay = await idempotency.lookup(db_session, request_fingerprint="fp", **IDEM_ARGS)
    assert replay is not None
    assert replay.status_code == 200
    assert replay.body == {"id": "t1"}


async def test_same_key_different_body_is_a_conflict(db_session) -> None:
    """Answering with the earlier response would silently drop the second write."""
    await idempotency.remember(
        db_session, request_fingerprint="fp-a", status_code=200, body={"id": "t1"}, **IDEM_ARGS
    )
    with pytest.raises(ApiError) as raised:
        await idempotency.lookup(db_session, request_fingerprint="fp-b", **IDEM_ARGS)
    assert raised.value.code == "conflict"
    assert raised.value.status_code == 409


async def test_same_key_from_another_actor_is_a_different_operation(db_session) -> None:
    """Otherwise one client's retry could be answered with another's response."""
    await idempotency.remember(
        db_session, request_fingerprint="fp", status_code=200, body={"id": "t1"}, **IDEM_ARGS
    )
    other = dict(IDEM_ARGS, actor_id="bob")
    assert await idempotency.lookup(db_session, request_fingerprint="fp", **other) is None


async def test_same_key_at_another_endpoint_is_a_different_operation(db_session) -> None:
    await idempotency.remember(
        db_session, request_fingerprint="fp", status_code=200, body={"id": "t1"}, **IDEM_ARGS
    )
    other = dict(IDEM_ARGS, endpoint="/api/v1/things/t1/reject")
    assert await idempotency.lookup(db_session, request_fingerprint="fp", **other) is None


async def test_expired_record_does_not_replay(db_session) -> None:
    await idempotency.remember(
        db_session,
        request_fingerprint="fp",
        status_code=200,
        body={"id": "t1"},
        ttl_seconds=1,
        now=datetime.now(timezone.utc) - timedelta(hours=2),
        **IDEM_ARGS,
    )
    assert await idempotency.lookup(db_session, request_fingerprint="fp", **IDEM_ARGS) is None


async def test_purge_expired_removes_only_expired(db_session) -> None:
    await idempotency.remember(
        db_session,
        request_fingerprint="fp",
        status_code=200,
        body={},
        ttl_seconds=1,
        now=datetime.now(timezone.utc) - timedelta(hours=2),
        **IDEM_ARGS,
    )
    await idempotency.remember(
        db_session,
        request_fingerprint="fp",
        status_code=200,
        body={},
        **dict(IDEM_ARGS, key="k-2"),
    )
    assert await idempotency.purge_expired(db_session) == 1
    survivors = (await db_session.execute(__import__("sqlalchemy").select(IdempotencyRecordModel))).scalars().all()
    assert [row.key for row in survivors] == ["k-2"]


def test_fingerprint_distinguishes_bodies() -> None:
    assert idempotency.fingerprint(b'{"reason":"a"}') != idempotency.fingerprint(b'{"reason":"b"}')
    assert idempotency.fingerprint(b'{"reason":"a"}') == idempotency.fingerprint(b'{"reason":"a"}')


# --------------------------------------------------------------------------
# Regressions found by the council. Each of these passed before the fix.
# --------------------------------------------------------------------------


def test_five_hundred_reports_the_same_id_in_body_and_header(client: TestClient) -> None:
    """The screenshot and the log must name the same request.

    Starlette invokes `@app.exception_handler(Exception)` from
    `ServerErrorMiddleware`, which sits outside every user middleware — so by
    then the request-id contextvar is gone. The 500 carried a freshly minted
    UUID in the body, a second one in the log, no `X-Request-Id` header at all,
    and discarded the client's value: unlinkable on exactly the failure an
    operator most needs to trace.
    """
    response = client.get("/api/v1/boom", headers={REQUEST_ID_HEADER: "mobile-42"})
    assert response.status_code == 500
    assert response.headers[REQUEST_ID_HEADER] == "mobile-42"
    assert response.json()["requestId"] == "mobile-42"
    # The central claim of the fix, asserted rather than assumed: the header the
    # operator reads off a screenshot and the id in the body are the same value.
    assert response.headers[REQUEST_ID_HEADER] == response.json()["requestId"]


def test_generated_request_id_also_agrees_between_header_and_body(client: TestClient) -> None:
    """Same equality when the server mints the id, which is the common case."""
    response = client.get("/api/v1/boom")
    assert response.status_code == 500
    assert response.headers[REQUEST_ID_HEADER] == response.json()["requestId"]
    assert response.headers[REQUEST_ID_HEADER]


def test_unmatched_api_path_returns_the_envelope(client: TestClient) -> None:
    """A typo'd URL is the commonest client mistake, and it missed the envelope.

    The router raises `starlette.exceptions.HTTPException`; the handler was keyed
    on FastAPI's subclass, and Starlette resolves handlers by walking the raised
    class's MRO — a parent never resolves to a child's handler. So every
    unmatched `/api/...` returned `{"detail": "Not Found"}`.
    """
    response = client.get("/api/v1/no-such-endpoint")
    body = response.json()
    assert response.status_code == 404
    assert body["code"] == "not_found"
    assert "detail" not in body
    assert body["requestId"]


def test_non_contract_unhandled_error_keeps_a_body(client: TestClient) -> None:
    """Re-raising from inside the exception handler produced a bodyless 500."""
    response = client.get("/mcp-like-boom")
    assert response.status_code == 500
    assert response.content, "a JSON-RPC client must not receive an empty 500"


@pytest.mark.parametrize("hostile", ["abc\n", "abc\r\n", "abc\nX-Evil: 1", "a" * 200, "spa ce"])
def test_control_characters_never_reach_the_response_header(hostile: str) -> None:
    """`re.match` with `$` also matches before a trailing newline.

    So "abc\n" passed the guard and was echoed verbatim into a response header —
    the single thing the guard exists to prevent.
    """
    from gateway.app.api.request_context import _accept_inbound

    accepted = _accept_inbound(hostile)
    assert accepted != hostile
    assert "\n" not in accepted and "\r" not in accepted


def test_forged_cursor_is_rejected_not_executed(client: TestClient) -> None:
    """The scope digest is computed from public inputs, so it authenticates nothing.

    Anyone who can read `pagination.py` could mint a cursor whose decoded position
    went straight into the caller's query: a forged `{"nope": 1}` was an
    unauthenticated remote 500.
    """
    scope = pagination.scope_digest("/api/v1/things", {"project": None})
    payload = __import__("json").dumps({"s": scope, "p": {"nope": 1}}, sort_keys=True, separators=(",", ":"))
    unsigned = __import__("base64").urlsafe_b64encode(payload.encode()).decode().rstrip("=")
    for forged in (unsigned, f"{unsigned}.AAAA"):
        response = client.get("/api/v1/things", params={"cursor": forged})
        assert response.status_code == 400, f"forged cursor accepted: {forged}"
        assert response.json()["code"] == "validation_failed"


@pytest.mark.parametrize("position", [{"nope": 1}, {"after": "3"}, {"after": [1]}, {"after": True}, {}])
def test_signed_cursor_with_a_wrong_position_is_a_400_not_a_500(client: TestClient, position: dict) -> None:
    """Even a genuine cursor must not hand unchecked JSON to the caller."""
    scope = pagination.scope_digest("/api/v1/things", {"project": None})
    cursor = pagination.encode_cursor(scope, position)
    response = client.get("/api/v1/things", params={"cursor": cursor})
    assert response.status_code == 400
    assert response.json()["code"] == "validation_failed"


def test_oversized_cursor_is_rejected_before_decoding(client: TestClient) -> None:
    response = client.get("/api/v1/things", params={"cursor": "a" * 5000})
    assert response.status_code == 400


def test_quoted_asterisk_is_an_entity_tag_not_the_wildcard() -> None:
    """`"*"` is a legitimate tag value; only the bare token `*` is the wildcard."""
    with pytest.raises(ApiError) as raised:
        concurrency.require_if_match('"*"', 7)
    assert raised.value.code == "stale_write"
    concurrency.require_if_match("*", 7)


async def test_concurrent_retries_do_not_both_execute(db_session) -> None:
    """The window between "no record" and "record written" was a double approval.

    Reserving before the work closes it: the second caller is told the first is
    in flight instead of performing the side effect and then crashing on the
    primary key with an unhandled IntegrityError.
    """
    first = await idempotency.reserve(db_session, request_fingerprint="fp", **IDEM_ARGS)
    assert isinstance(first, Claim), "the first caller wins the claim and does the work"

    with pytest.raises(ApiError) as raised:
        await idempotency.reserve(db_session, request_fingerprint="fp", **IDEM_ARGS)
    assert raised.value.code == "conflict"
    assert raised.value.retryable is True

    await idempotency.complete(
        db_session, status_code=200, body={"id": "t1"}, claim=first, request_fingerprint="fp", **IDEM_ARGS
    )
    replay = await idempotency.reserve(db_session, request_fingerprint="fp", **IDEM_ARGS)
    assert isinstance(replay, idempotency.ReplayedResponse) and replay.body == {"id": "t1"}


async def test_release_lets_a_failed_write_be_retried(db_session) -> None:
    """Otherwise one transient failure locks the key for its whole TTL."""
    claim = await idempotency.reserve(db_session, request_fingerprint="fp", **IDEM_ARGS)
    assert isinstance(claim, Claim)
    await idempotency.release(db_session, claim=claim, **IDEM_ARGS)
    assert isinstance(
        await idempotency.reserve(db_session, request_fingerprint="fp", **IDEM_ARGS), Claim
    )


async def test_release_does_not_discard_a_completed_response(db_session) -> None:
    await idempotency.remember(
        db_session, request_fingerprint="fp", status_code=200, body={"id": "t1"}, **IDEM_ARGS
    )
    await idempotency.release(db_session, claim=Claim("whatever"), **IDEM_ARGS)
    replay = await idempotency.lookup(db_session, request_fingerprint="fp", **IDEM_ARGS)
    assert replay is not None and replay.body == {"id": "t1"}


async def test_abandoned_reservation_does_not_lock_the_key_for_a_day(db_session) -> None:
    """A worker killed between reserve and complete must not strand the client.

    The reservation carried the full 24h response TTL, so one crash produced a
    day of 409s saying "retry shortly to receive its result" for a result that
    was never coming — and `retryable: true` invited the client to keep trying.
    """
    stale = datetime.now(timezone.utc) - timedelta(seconds=idempotency.IN_FLIGHT_TIMEOUT_SECONDS + 5)
    assert isinstance(
        await idempotency.reserve(db_session, request_fingerprint="fp", now=stale, **IDEM_ARGS), Claim
    )

    # Still inside the window: correctly refused.
    with pytest.raises(ApiError):
        await idempotency.reserve(
            db_session, request_fingerprint="fp", now=stale + timedelta(seconds=1), **IDEM_ARGS
        )

    # Past it: the claim is abandoned and the next caller takes over.
    assert isinstance(
        await idempotency.reserve(db_session, request_fingerprint="fp", **IDEM_ARGS), Claim
    )


async def test_completing_a_lost_reservation_still_records_the_write(db_session) -> None:
    """Otherwise the next identical request executes the side effect again."""
    claim = await idempotency.reserve(db_session, request_fingerprint="fp", **IDEM_ARGS)
    assert isinstance(claim, Claim)
    await idempotency.release(db_session, claim=claim, **IDEM_ARGS)  # the row is swept

    await idempotency.complete(
        db_session, status_code=200, body={"v": 1}, claim=claim, request_fingerprint="fp", **IDEM_ARGS
    )
    replay = await idempotency.reserve(db_session, request_fingerprint="fp", **IDEM_ARGS)
    assert isinstance(replay, idempotency.ReplayedResponse) and replay.body == {"v": 1}


async def test_a_completed_record_is_final(db_session) -> None:
    """Replacing a recorded 200 with a later 500 defeats the whole mechanism."""
    await idempotency.remember(
        db_session, request_fingerprint="fp", status_code=200, body={"v": "first"}, **IDEM_ARGS
    )
    await idempotency.remember(
        db_session, request_fingerprint="fp", status_code=500, body={"v": "second"}, **IDEM_ARGS
    )
    replay = await idempotency.lookup(db_session, request_fingerprint="fp", **IDEM_ARGS)
    assert replay is not None
    assert (replay.status_code, replay.body) == (200, {"v": "first"})

    await idempotency.complete(
        db_session,
        status_code=500,
        body={"v": "third"},
        claim=Claim("stale-token"),
        request_fingerprint="fp",
        **IDEM_ARGS,
    )
    replay = await idempotency.lookup(db_session, request_fingerprint="fp", **IDEM_ARGS)
    assert (replay.status_code, replay.body) == (200, {"v": "first"})


def test_non_contract_unhandled_error_is_logged_once(client: TestClient, caplog) -> None:
    """Two full tracebacks for one failure, on the highest-volume transport.

    `render_unhandled` logged before checking scope and then re-raised, so
    Starlette's ServerErrorMiddleware logged the same exception again.
    """
    import logging

    with caplog.at_level(logging.ERROR, logger="gateway.app.api.errors"):
        client.get("/mcp-like-boom")
    ours = [record for record in caplog.records if record.message == "unhandled_exception"]
    assert ours == [], "a non-contract failure is Starlette's to log, not ours"

    caplog.clear()
    with caplog.at_level(logging.ERROR, logger="gateway.app.api.errors"):
        client.get("/api/v1/boom")
    ours = [record for record in caplog.records if record.message == "unhandled_exception"]
    assert len(ours) == 1
