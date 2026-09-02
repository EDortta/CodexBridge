"""Near-real-time delivery of what changed, and the backlog behind it — issue #13.

Two endpoints, one source of truth:

- `GET /api/v1/events/stream` — Server-Sent Events, the live transport.
- `GET /api/v1/events` — the same events as an ordinary paged read. This is the
  documented **fallback**, not a second-class path: a client on a network that
  breaks long-lived connections, or one in the background where the platform
  will not keep a socket open, polls this and gets exactly the same events with
  exactly the same ids.

## Why SSE and not WebSocket

The gateway already speaks WebSocket at `/agent/ws`, so "we have no WebSocket"
is not the reason. The reasons are:

- **Authentication.** Every endpoint on this contract authenticates with
  `Authorization: Bearer` through `api/auth.py:current_principal`, which is an
  ordinary FastAPI dependency on an ordinary `GET`. A browser/mobile WebSocket
  cannot set that header on the handshake, so a WebSocket stream would need a
  *second* authentication scheme — a token in the URL is what
  `security-standards.md` §3 forbids by name, and a post-handshake auth frame is
  a bespoke protocol to keep correct forever. SSE rides the scheme that already
  exists.
- **Resume is in the transport.** `Last-Event-ID` is part of SSE: a client that
  drops reconnects and the browser/EventSource sends the last id it saw, with no
  application protocol on top. Issue #13's "resume from the last acknowledged
  event" is the mechanism SSE was designed around.
- **One direction is all this needs.** Nothing in the issue asks the client to
  send anything on the channel. A bidirectional transport whose reverse channel
  is unused is surface with no consumer.
- **`/agent/ws` is not a precedent for this.** It is the executor's reverse
  channel, authenticated by a machine token, contracted by `docs/protocol.md`,
  and explicitly excluded from this contract. A mobile client never opens it.

The trade-off, stated rather than hidden: SSE is HTTP/1.1 text and holds a
connection. That is why this module bounds the number of concurrent streams
(`stream_slots`), bounds each stream's lifetime, and sends heartbeats — see
below.

## What is delivered, and what could never be

Events are `audit_events` rows translated by
`gateway/app/services/event_types.py`. That module owns *what may be said*; this
one owns *who may hear it and when*. Three properties this module is responsible
for:

1. **Project authorization is on the query.** `store.list_mobile_events_page`
   filters by the caller's projects in SQL, so a page is never a filtered-down
   view of rows the caller was allowed to load. A row whose project cannot be
   derived is delivered to nobody, admins included.

2. **Authorization is re-checked on every poll, not once at `GET`.** A stream
   opened at 09:00 and still running at 17:00 authorized once, and everything
   after that is a decision made with an eight-hour-old credential. `_authorize`
   below re-resolves the bearer token through `api/auth.py:principal_for_token`
   on each iteration, so a revoked token, an expired token, a disabled account
   and a project removed from `allowed_projects` all take effect within one poll
   interval. Pinned by
   `tests/integration/test_events.py::test_a_revoked_token_stops_the_stream_it_had_already_opened`.

3. **A gap is announced, never silent.** Resume is `id > cursor`, so the only
   way to lose an event is for the row itself to be gone. `store.audit_cursor_status`
   detects that (and the mirror case, a cursor from another deployment) and the
   stream opens with a `stream.gap` frame instead of quietly delivering from
   wherever the log now starts.

## Frames

    event: stream.open        no id — an opening acknowledgement, not a position
    event: stream.gap         no id — resume is not continuous; re-read
    event: <MobileEventType>  id: <audit id>  — the events themselves
    : keep-alive              a comment, so proxies do not time out an idle stream
    event: stream.closed      no id — why the server ended it

Only the third kind carries `id:`, and that is deliberate: `Last-Event-ID` must
never advance past an event the client actually received, so a control frame is
not allowed to move it.
"""

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import AsyncIterator, Callable

from fastapi import APIRouter, Depends, Header, Query, Request, Response
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.background import BackgroundTask

from gateway.app.api import pagination, permissions
from gateway.app.api.auth import bearer_token, principal_for_token, require_action, visible_projects
from gateway.app.api.errors import DEPENDENCY_UNAVAILABLE, VALIDATION_FAILED, ApiError
from gateway.app.api.routes.sessions import redact
from gateway.app.api.timestamps import now_z, utc_z
from gateway.app.core.config import settings
from gateway.app.core.users import AuthenticatedPrincipal
from gateway.app.db.session import get_session, session_factory
from gateway.app.services import event_types, store


router = APIRouter(prefix="/api/v1")

EVENTS_ENDPOINT = "/api/v1/events"

# The largest resume position this API accepts. `audit_events.id` is a 64-bit
# signed identity column, so nothing above this can ever name a row — but until
# this bound existed, `?after=2**63+1` was bound straight into the query and the
# driver raised `OverflowError: Python int too large to convert to SQLite
# INTEGER`, which reached the caller as `500 internal_error`. On the stream it
# was worse: the response had already committed to `200 text/event-stream`, so
# the body emitted `stream.open` and then simply ended — no `stream.gap`, no
# `stream.closed`, and a client cannot tell that from a quiet feed (council
# round 1, the adversarial user). `ge=0` bounded the low end only; an unbounded
# integer parameter is an unbounded integer parameter in both directions.
MAX_EVENT_ID = 2**63 - 1

# How many `details[]` entries a rejected filter or subscription list may quote
# back, and how much of each value. The details array exists so a client can
# show which value it got wrong; quoting an unbounded number of unbounded
# strings turned a large request into an equally large error response.
MAX_ECHOED_DETAILS = 10
MAX_ECHOED_VALUE = 64


def _echo(value: str) -> str:
    """One caller-supplied value, safe to put in an error message.

    Truncated rather than omitted: a client that mistyped one event type needs
    to see which one, and 64 characters is longer than every value this
    vocabulary contains.
    """
    return value if len(value) <= MAX_ECHOED_VALUE else value[:MAX_ECHOED_VALUE] + "…"


# --------------------------------------------------------------------------
# Concurrency ceiling
# --------------------------------------------------------------------------


class StreamSlot:
    """One acquired slot, releasable exactly once, remembering whose it was.

    Idempotent because the slot is released down two paths that both have to
    exist: the generator's `finally`, which covers a normal end and a client
    disconnect once the body has started, and the response's background task,
    which covers the case the `finally` cannot — a connection dropped after the
    route returned but before the generator was ever iterated. An async
    generator that never started running has no `finally` to run, so relying on
    it alone leaked a slot per dropped connection, and a leaked slot is
    permanent: the ceiling ratchets down until the endpoint answers 503 forever.
    """

    def __init__(self, slots: "StreamSlots", owner: str) -> None:
        self._slots = slots
        self._owner = owner
        self._released = False

    def release(self) -> None:
        if self._released:
            return
        self._released = True
        self._slots.release(self._owner)


class StreamSlots:
    """How many event streams this process will hold open at once.

    Not covered by the rate limiter, and that is the point: the limiter counts
    *requests* per window, and one accepted request here becomes a connection
    held for up to `event_stream_max_duration_seconds` that takes a database
    session on every poll. Under the default ceiling of 120 requests/minute a
    single bucket could pin 120 concurrent pollers against the same pool
    `GET /api/v1/sessions` uses — so the endpoint that is cheap per request is
    the one that can take the API down.

    Refusing with `503 dependency_unavailable` + `Retry-After` rather than
    queueing: a client told to come back later reconnects with its
    `Last-Event-ID` and loses nothing, while a queued client holds the
    connection it was refused for.

    **Two ceilings, because one global ceiling is not a share.** The process
    ceiling protects the gateway; the per-actor ceiling is what stops one
    read-only token from taking every slot and answering `503` to everybody
    else — including an administrator — for as long as it keeps its connections
    (council round 1, the adversarial user). Neither is a rate limit: the
    limiter counts requests per window, and a request here is a connection held
    for minutes.
    """

    def __init__(self, limit: int, per_actor: int | None = None) -> None:
        self.limit = limit
        # A per-actor ceiling above the process ceiling would never bind, which
        # reads as "there is a per-actor ceiling" while there is not.
        self.per_actor = min(per_actor if per_actor is not None else limit, limit)
        self._active = 0
        self._by_actor: dict[str, int] = {}

    @property
    def active(self) -> int:
        return self._active

    def active_for(self, owner: str) -> int:
        return self._by_actor.get(owner, 0)

    def acquire(self, owner: str) -> StreamSlot:
        if self._active >= self.limit:
            raise ApiError(
                status_code=503,
                code=DEPENDENCY_UNAVAILABLE,
                message="Too many event streams are open on this gateway. Retry shortly.",
                headers={"Retry-After": "5"},
            )
        if self._by_actor.get(owner, 0) >= self.per_actor:
            raise ApiError(
                status_code=503,
                code=DEPENDENCY_UNAVAILABLE,
                message=(
                    "This account already has as many event streams open as it may. "
                    "Close one, or retry shortly."
                ),
                headers={"Retry-After": "5"},
            )
        self._active += 1
        self._by_actor[owner] = self._by_actor.get(owner, 0) + 1
        return StreamSlot(self, owner)

    def release(self, owner: str) -> None:
        # Never below zero. A counter that underflows reads as "off" forever
        # after, which would silently remove the ceiling
        # (`design-standards.md` §6).
        self._active = max(0, self._active - 1)
        remaining = self._by_actor.get(owner, 0) - 1
        if remaining > 0:
            self._by_actor[owner] = remaining
        else:
            # Popped rather than left at zero: the dict is keyed by user id and
            # would otherwise grow once per actor that ever opened a stream and
            # never shrink — a slow leak in a process that runs for weeks.
            self._by_actor.pop(owner, None)


stream_slots = StreamSlots(
    settings.event_stream_max_concurrent, settings.event_stream_max_per_actor
)


# --------------------------------------------------------------------------
# Shared reads
# --------------------------------------------------------------------------


def _requested_types(types: list[str] | None) -> list[str]:
    """Validate a `type` filter against the published vocabulary.

    Checked against `ALL_EVENT_TYPES`, which includes the types this build
    declares and does not yet emit (`artifact.*`, `androidBuild.*`): a client
    filtering on one of those must get an empty result, not a `400`, or the
    declared-but-unemitted values would be unusable in exactly the way declaring
    them was meant to avoid.
    """
    if not types:
        return []
    unknown = sorted({value for value in types if value not in event_types.ALL_EVENT_TYPES})
    if unknown:
        raise ApiError(
            status_code=400,
            code=VALIDATION_FAILED,
            message="Unknown event type in the type filter.",
            # Bounded in both dimensions. Unbounded, this reflected every
            # rejected value at full length, so a caller could turn a large
            # query string into an equally large error body.
            details=[
                {"field": "?type", "code": "unknown_event_type", "message": f"No such event type: {_echo(value)}."}
                for value in unknown[:MAX_ECHOED_DETAILS]
            ],
        )
    return list(types)


def _narrow_projects(principal: AuthenticatedPrincipal, requested: list[str] | None) -> list[str] | None:
    """The projects to query: the caller's, narrowed by `?project=` if given.

    `project` only ever narrows. An admin's `None` becomes the requested list;
    a restricted caller cannot name a project outside `allowed_projects` and
    have it survive the intersection. Same shape as `routes/decisions.py`.
    """
    projects = visible_projects(principal)
    if requested:
        return [value for value in requested if projects is None or value in projects]
    return projects


async def _gap_for(
    session: AsyncSession, principal: AuthenticatedPrincipal, after: int
) -> tuple[str, dict | None]:
    """The gap block for one resume position, or None when it is continuous.

    One function for both transports so the `stream.gap` frame and the polling
    endpoint's `gap` object cannot describe the position differently — they are
    the same answer to the same question, and a client is expected to move
    between the two mid-feed.
    """
    scope = dict(
        project_ids=visible_projects(principal),
        entity_types=sorted(event_types.DELIVERABLE_ENTITY_TYPES),
        audit_event_types=sorted(event_types.TRANSLATED_AUDIT_EVENT_TYPES),
    )
    status = await store.audit_cursor_status(session, after, **scope)
    if status == store.CURSOR_OK:
        return status, None
    return status, {
        "reason": status,
        "from": after,
        "oldestAvailableId": await store.oldest_audit_event_id(session, **scope),
    }


def _to_event(row, project_id: str) -> event_types.MobileEvent | None:
    """One audit row as a mobile event, or None when it is not one of ours.

    Returns None only for a row the query should already have excluded. Both
    guards are here rather than only in SQL because this function is also the
    one the stream calls, and a translation that silently produced a `type` of
    `None` would ship a malformed frame.
    """
    payload = _payload(row.payload_json)
    classified = event_types.classify(row.event_type, payload)
    if classified is None:
        return None
    mobile_type, entity_kind = classified
    return event_types.MobileEvent(
        id=row.id,
        type=mobile_type,
        project_id=project_id,
        entity_kind=entity_kind,
        entity_id=row.entity_id,
        at=utc_z(row.created_at),
        summary=event_types.summarize(mobile_type, payload, redact),
        state=event_types.state_of(payload),
        actor_id=event_types.actor_of(payload),
    )


def _payload(raw: str | None) -> dict:
    """The stored payload as a dict, or an empty one.

    Never raises. `payload_json` is years of rows written by fifty-one call sites,
    and one unparseable row must not take down a stream that is otherwise
    correct — the summary degrades to its default sentence instead.
    """
    try:
        value = json.loads(raw or "{}")
    except (TypeError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


async def _load_events(
    session: AsyncSession,
    *,
    projects: list[str] | None,
    types: list[str],
    after: int | None,
    limit: int,
) -> tuple[list[event_types.MobileEvent], bool, int | None]:
    """A page of translated events, whether more follow, and the last id *loaded*.

    The `type` filter is applied **after** translation because the client's
    vocabulary is the mobile one and the column holds the internal one; the
    query still narrows by the full set of translatable audit types, so the
    rows loaded are bounded by `limit + 1` either way. `has_more` is computed
    from the over-fetch before filtering, so it stays truthful: a page short
    because of a type filter still reports that more rows exist.

    The third element is the id of the last row this page **loaded**, which is
    not the id of the last event returned when a type filter dropped the tail.
    Both callers advance their position by it, and they need it from the same
    query that produced the page: computing it with a second identical query
    doubled the work of every poll of every open stream, and left a window in
    which the two queries could see different rows — the second one advancing
    the cursor past an event the first had not yet delivered, which is the
    silent loss this endpoint exists to rule out.
    """
    rows = await store.list_mobile_events_page(
        session,
        project_ids=projects,
        entity_types=sorted(event_types.DELIVERABLE_ENTITY_TYPES),
        audit_event_types=sorted(event_types.TRANSLATED_AUDIT_EVENT_TYPES),
        after=after,
        limit=limit,
    )
    has_more = len(rows) > limit
    page = rows[:limit]
    last_loaded_id = page[-1][0].id if page else None
    events: list[event_types.MobileEvent] = []
    for row, project_id in page:
        event = _to_event(row, project_id)
        if event is None or (types and event.type not in types):
            continue
        events.append(event)
    return events, has_more, last_loaded_id


# --------------------------------------------------------------------------
# GET /api/v1/events — the backlog, and the documented polling fallback
# --------------------------------------------------------------------------


@router.get("/events", tags=["events"])
async def list_events(
    response: Response,
    after: int | None = Query(default=None, ge=0, le=MAX_EVENT_ID),
    project: list[str] | None = Query(default=None),
    type: list[str] | None = Query(default=None),  # noqa: A002 - the contract's parameter name
    limit: int | None = Query(default=None),
    principal: AuthenticatedPrincipal = Depends(require_action(permissions.EVENTS_READ)),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Events the caller may see, oldest first, after `after`.

    **Not cursor-paged, deliberately.** Every other collection in this contract
    uses an opaque signed cursor; this one is addressed by the same integer id
    the stream puts in `id:`, for the reason `gateway/app/api/pagination.py`
    already gives about session logs: an append-only stream keyed by a monotonic
    integer must not be given a second paging vocabulary, and here the id is
    *public by necessity* — it is the SSE resume token, so wrapping it in an
    opaque cursor would publish two names for one position and make `Last-Event-ID`
    and `?after=` incompatible.

    Oldest first, like `GET /api/v1/missions/{id}/timeline` and unlike the
    newest-first collections: a client is catching up, and catching up reads
    forward.

    Carries the same `gap` signal the stream sends as a `stream.gap` frame. The
    polling fallback is the transport a client on a hostile network ends up
    living on, and "no silent loss on resume" is a property of the *events*, not
    of one transport — a client that fell out of retention and polls would
    otherwise be handed a page starting wherever the log now begins, with
    nothing to distinguish it from continuity.
    """
    projects = _narrow_projects(principal, project)
    wanted = _requested_types(type)
    size = pagination.parse_limit(limit)

    events, has_more, last_loaded_id = await _load_events(
        session, projects=projects, types=wanted, after=after, limit=size
    )
    # `nextAfter` is the last id **loaded**, not the last id returned: with a
    # type filter the two differ, and reporting the last *returned* id would
    # make the next request re-scan rows the filter already rejected — forever,
    # if nothing in the tail matches.
    next_after = last_loaded_id if has_more else None

    body: dict = {
        "items": [event.as_dict() for event in events],
        "page": {"hasMore": has_more, "nextAfter": next_after},
    }
    if after is not None:
        # Scoped to what this principal may see, and to `visible_projects` rather
        # than to `projects` above: `?project=` is a filter the client chose for
        # this one request, while continuity is a property of the whole feed the
        # client resumes from. Narrowing the gap check by a transient filter
        # would report a gap to a client that had merely changed its filter.
        status, gap = await _gap_for(session, principal, after)
        if gap is not None:
            body["gap"] = gap

    response.headers["Cache-Control"] = "no-store"
    return body


# --------------------------------------------------------------------------
# GET /api/v1/events/stream — Server-Sent Events
# --------------------------------------------------------------------------


def _frame(*, event: str, data: dict, event_id: int | None = None) -> str:
    """One SSE frame.

    `id:` is emitted only when an event actually has a position. A control frame
    that carried one would advance the client's `Last-Event-ID` past events it
    never received, which is precisely the silent loss this endpoint's
    acceptance criterion forbids.
    """
    lines = []
    if event_id is not None:
        lines.append(f"id: {event_id}")
    lines.append(f"event: {event}")
    # What keeps a frame on one line is `json.dumps` escaping `\r` and `\n`,
    # which it does whatever `ensure_ascii` says: no value can end a `data:`
    # line early and split one event into two. The first cut of this comment
    # credited `ensure_ascii` with that, which would have told the next reader
    # that turning it off breaks frame integrity — it does not (council round 1,
    # the claim auditor).
    #
    # `ensure_ascii=True` is still not decorative. With it off, Python leaves
    # U+2028 and U+2029 raw; neither is an SSE line terminator, so the frame
    # survives, but both are *JavaScript* line terminators, and a client that
    # evaluates a payload rather than parsing it would see a different program.
    # An all-ASCII body also survives a proxy or client that mishandles UTF-8.
    # Both properties are pinned by
    # `test_a_newline_in_stored_text_cannot_split_one_frame_into_two`.
    lines.append(f"data: {json.dumps(data, ensure_ascii=True, separators=(',', ':'))}")
    return "\n".join(lines) + "\n\n"


HEARTBEAT_FRAME = ": keep-alive\n\n"


def _resume_from(last_event_id: str | None, after: int | None) -> int:
    """Where to resume, from the SSE header or the query parameter.

    `Last-Event-ID` wins when both are present: the header is what a reconnecting
    EventSource sends by itself, and it is the more recent of the two by
    construction — a client's `?after=` is whatever it first opened with.

    A malformed header is treated as absent rather than as an error. It is set
    by the user agent, not the application, and refusing the connection over it
    would strand a client that cannot control the value.

    A value above `MAX_EVENT_ID` is **clamped, not discarded**. Discarding it
    would fall back to `after`, or to 0, and replay the whole feed to a client
    that asked to resume — the one outcome this endpoint must never produce.
    Clamped, the position is beyond every row, so the client is told
    `cursor_ahead` and knows exactly where it stands.
    """
    if last_event_id is not None:
        try:
            parsed = int(last_event_id.strip())
        except (TypeError, ValueError):
            parsed = -1
        if parsed >= 0:
            return min(parsed, MAX_EVENT_ID)
    return min(after or 0, MAX_EVENT_ID)


async def _authorize(session: AsyncSession, token: str) -> AuthenticatedPrincipal | None:
    """The principal for this stream right now, or None if it may no longer read.

    Both halves matter. `principal_for_token` covers revocation, expiry and a
    disabled account; the `is_allowed` check covers a scope the token no longer
    carries. Together they mean the answer to "may this connection still receive
    events" is recomputed from scratch on every poll rather than inherited from
    the `GET` that opened it.
    """
    principal = await principal_for_token(session, token)
    if principal is None:
        return None
    if not permissions.is_allowed(principal, permissions.EVENTS_READ):
        return None
    return principal


async def event_stream(
    *,
    factory,
    token: str,
    resume_from: int,
    requested_projects: list[str] | None,
    requested_types: list[str],
    poll_interval: float,
    heartbeat_seconds: float,
    max_duration_seconds: float,
    batch_limit: int,
    on_close: Callable[[], None] | None = None,
    is_disconnected: Callable[[], object] | None = None,
    monotonic: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], object] = asyncio.sleep,
) -> AsyncIterator[str]:
    """The SSE body: an async generator of frames.

    Written as a free function taking its collaborators as parameters rather
    than reading them from the request, because that is the seam the tests need
    (`design-standards.md` §2): `tests/integration/test_events.py` drives this
    directly with a tiny poll interval and a real database, and asserts on the
    frames — no sleeping on wall-clock timing, no flaky "did it arrive yet".

    A **session per poll**, not one held for the stream's lifetime. A stream can
    live fifteen minutes; a database session that lives that long pins a pooled
    connection for the whole time and would make the concurrency ceiling a
    ceiling on the pool itself.
    """
    started = monotonic()
    cursor = resume_from
    last_emission = started
    closed_reason = "max_duration"

    try:
        yield _frame(event=event_types.STREAM_OPEN, data={"type": event_types.STREAM_OPEN, "from": cursor, "at": now_z()})

        # Computed on the first poll rather than before the loop, because the
        # answer is scoped to the principal and the principal is resolved inside
        # the loop. That ordering is not merely convenient: the gap block names
        # positions in the caller's own feed, so producing it before the token
        # was re-checked would have been a read performed for a credential this
        # generator had not yet verified.
        pending_gap: dict | None = None
        first_poll = True

        while True:
            if is_disconnected is not None and await is_disconnected():
                closed_reason = "disconnected"
                return

            async with factory() as session:
                principal = await _authorize(session, token)
                if principal is None:
                    closed_reason = "unauthenticated"
                    break
                if first_poll:
                    _status, pending_gap = await _gap_for(session, principal, cursor)
                projects = _narrow_projects(principal, requested_projects)
                # The cursor advances past every row this poll *loaded*, not
                # just the ones a type filter kept. Advancing only past
                # delivered events would re-scan the filtered ones on every
                # poll for as long as the stream lives.
                events, _, last_loaded_id = await _load_events(
                    session,
                    projects=projects,
                    types=requested_types,
                    after=cursor,
                    limit=batch_limit,
                )

            if first_poll:
                first_poll = False
                if pending_gap is not None:
                    # Announced before a single event is delivered. Delivering
                    # first and mentioning the gap later would let a client act
                    # on a partial view believing it was continuous.
                    yield _frame(
                        event=event_types.STREAM_GAP,
                        data={"type": event_types.STREAM_GAP, **pending_gap},
                    )

            for event in events:
                yield _frame(event=event.type, data=event.as_dict(), event_id=event.id)
                last_emission = monotonic()
            # Advanced only after the frames are out. A cursor moved before the
            # yields would skip the batch if the consumer went away mid-loop and
            # the generator were resumed — and `max` because a client's
            # `Last-Event-ID` may legitimately be ahead of anything visible to
            # it, and the cursor must never move backwards.
            if last_loaded_id is not None:
                cursor = max(cursor, last_loaded_id)

            now = monotonic()
            if not events and now - last_emission >= heartbeat_seconds:
                # A comment, not an event: it keeps the connection warm through
                # a proxy's read timeout without appearing in the client's
                # `onmessage` or moving `Last-Event-ID`.
                yield HEARTBEAT_FRAME
                last_emission = now

            if now - started >= max_duration_seconds:
                closed_reason = "max_duration"
                break
            await sleep(poll_interval)

        yield _frame(
            event=event_types.STREAM_CLOSED,
            data={"type": event_types.STREAM_CLOSED, "reason": closed_reason, "at": now_z()},
        )
    finally:
        # Runs on a normal end, on `aclose()` when the client disconnects, and
        # on cancellation. The slot is taken by the route before this generator
        # is handed to the response, so releasing it anywhere else would leak
        # one per dropped connection — and a leaked slot is permanent.
        if on_close is not None:
            on_close()


@router.get("/events/stream", tags=["events"])
async def stream_events(
    request: Request,
    after: int | None = Query(default=None, ge=0, le=MAX_EVENT_ID),
    project: list[str] | None = Query(default=None),
    type: list[str] | None = Query(default=None),  # noqa: A002 - the contract's parameter name
    last_event_id: str | None = Header(default=None, alias="Last-Event-ID"),
    principal: AuthenticatedPrincipal = Depends(require_action(permissions.EVENTS_READ)),
) -> StreamingResponse:
    """Open a live event stream for the caller's projects.

    The `principal` dependency authorizes the *opening* of the stream and gives
    the caller the same `401`/`403` shape as every other endpoint. It is not
    what keeps the stream authorized — `event_stream` re-checks the token on
    every poll; see the module docstring.

    No `AsyncSession` dependency here on purpose. FastAPI closes a request's
    dependencies when the handler returns, which for a streaming response is
    *before* the body is produced, so a session injected here would be closed
    under the generator. The generator opens its own, one per poll, through
    `db/session.py:session_factory`.
    """
    # Validated before the response starts: once the first byte of an
    # `text/event-stream` body is out, there is no status code left to change,
    # so a bad `?type=` would have to be reported inside the stream.
    wanted = _requested_types(type)
    resume = _resume_from(last_event_id, after)

    # Keyed by user id, not by token: two tokens for one account are one
    # account's share, and a client that reconnects with a fresh token must not
    # be able to double its allowance by doing so.
    slot = stream_slots.acquire(principal.user_id)
    try:
        body = event_stream(
            factory=session_factory(),
            token=bearer_token(request) or "",
            resume_from=resume,
            requested_projects=project,
            requested_types=wanted,
            poll_interval=settings.effective_event_stream_poll_interval(),
            heartbeat_seconds=settings.event_stream_heartbeat_seconds,
            max_duration_seconds=settings.event_stream_max_duration_seconds,
            batch_limit=settings.effective_event_stream_batch_limit(),
            on_close=slot.release,
            is_disconnected=request.is_disconnected,
        )
    except Exception:
        slot.release()
        raise
    return StreamingResponse(
        body,
        media_type="text/event-stream",
        # Belt and braces on the slot; `StreamSlot.release` is idempotent. The
        # generator's `finally` covers everything from its first iteration
        # onwards, and this covers the gap before it — a connection dropped
        # between this `return` and the first `__anext__` leaves an async
        # generator that never started, and one that never started has no
        # `finally` to run.
        background=BackgroundTask(slot.release),
        headers={
            "Cache-Control": "no-store",
            # nginx buffers a proxied response by default, which would hold each
            # frame until the buffer filled and turn a live stream into a batch
            # one. This header switches it off for this response only, so the
            # vhost's `/api/` block does not have to disable buffering for every
            # other endpoint. Harmless to a proxy that does not understand it.
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )
