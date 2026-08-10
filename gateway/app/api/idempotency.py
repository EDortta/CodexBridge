"""Replay-safe writes for a client that goes offline mid-request.

A mobile client that loses the network after sending `POST .../approve` cannot
know whether the server acted. Without this, its only options are to retry and
risk a double approval, or not retry and leave the operator staring at a stuck
decision. With an `Idempotency-Key`, retrying is always safe: the second request
returns the first one's stored response and changes nothing.

Two failure modes are handled explicitly because both are silent otherwise:

- **the same key from a different actor or at a different endpoint** is a
  different operation. The record is keyed by all three, so one client's retry
  can never be answered with another client's response;
- **the same key with a different payload** is a client bug — a key reused
  across operations. Answering it with the earlier response would silently drop
  the second write, so it is reported as a conflict instead.

The flow is **reserve first, complete after**. Writing the record only after the
handler finished left a window in which two concurrent retries both saw "no
record", both performed the side effect — the double approval this exists to
prevent — and then the loser crashed on the primary key with an unhandled
IntegrityError, returning a 500 marked `retryable`, which invites a conforming
client to send the already-applied write a third time.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from gateway.app.api.errors import CONFLICT, ApiError
from gateway.app.models.entities import IdempotencyRecordModel


DEFAULT_TTL_SECONDS = 24 * 60 * 60

# How long an unfinished reservation blocks its key. Deliberately short and
# separate from the response TTL: a worker killed between `reserve` and
# `complete` leaves an IN_FLIGHT row behind, and giving that row the full 24-hour
# TTL turned one crash into a day of 409s telling a client to "retry shortly" for
# a result that was never coming. After this window the reservation is treated as
# abandoned and the next caller takes it over.
IN_FLIGHT_TIMEOUT_SECONDS = 60

IDEMPOTENCY_KEY_HEADER = "Idempotency-Key"


def fingerprint(body: bytes) -> str:
    return hashlib.sha256(body).hexdigest()


# A reservation that no handler has completed yet. Chosen because it is not a
# valid HTTP status, so it can never be mistaken for a stored response.
IN_FLIGHT = 0


class ReplayedResponse:
    """A stored response being returned again, never re-executed."""

    __slots__ = ("status_code", "body")

    def __init__(self, status_code: int, body: dict) -> None:
        self.status_code = status_code
        self.body = body


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def _conflict(message: str, *, retryable: bool = False) -> ApiError:
    return ApiError(status_code=409, code=CONFLICT, message=message, retryable=retryable)


async def _existing(
    session: AsyncSession,
    *,
    key: str,
    endpoint: str,
    actor_id: str,
    request_fingerprint: str,
    now: datetime,
) -> ReplayedResponse | None:
    record = await session.get(IdempotencyRecordModel, (key, endpoint, actor_id))
    if record is None:
        return None
    if _aware(record.expires_at) <= now:
        await session.delete(record)
        await session.commit()
        return None
    if record.request_fingerprint != request_fingerprint:
        raise _conflict(
            "This Idempotency-Key was already used for a different request body. "
            "Use a new key for a new operation."
        )
    if record.status_code == IN_FLIGHT:
        if _aware(record.created_at) + timedelta(seconds=IN_FLIGHT_TIMEOUT_SECONDS) <= now:
            # Abandoned: whoever held this claim died before completing it. The
            # write never happened, so blocking further attempts protects
            # nothing and strands the client until the record expires.
            await session.delete(record)
            await session.commit()
            return None
        # An identical request is being served right now. Reporting it as
        # retryable is honest: the first attempt will finish and the retry will
        # then replay it, whereas executing now would duplicate the write.
        raise _conflict(
            "An identical request with this Idempotency-Key is still in flight. "
            "Retry shortly to receive its result.",
            retryable=True,
        )
    return ReplayedResponse(record.status_code, json.loads(record.response_json))


async def lookup(
    session: AsyncSession,
    *,
    key: str,
    endpoint: str,
    actor_id: str,
    request_fingerprint: str,
    now: datetime | None = None,
) -> ReplayedResponse | None:
    """Read-only: the stored response for this key, or None. Does not reserve."""
    return await _existing(
        session,
        key=key,
        endpoint=endpoint,
        actor_id=actor_id,
        request_fingerprint=request_fingerprint,
        now=now or datetime.now(timezone.utc),
    )


async def reserve(
    session: AsyncSession,
    *,
    key: str,
    endpoint: str,
    actor_id: str,
    request_fingerprint: str,
    ttl_seconds: int = DEFAULT_TTL_SECONDS,
    now: datetime | None = None,
) -> ReplayedResponse | None:
    """Claim this key before doing the work.

    Returns a `ReplayedResponse` when the operation already completed — the
    caller must return it and do nothing else. Returns None when the claim was
    won, meaning the caller should perform the write and then call `complete`
    (or `release` if it fails).

    Raises `conflict` when the key was used for a different body, or when an
    identical request is still in flight.
    """
    now = now or datetime.now(timezone.utc)
    replay = await _existing(
        session,
        key=key,
        endpoint=endpoint,
        actor_id=actor_id,
        request_fingerprint=request_fingerprint,
        now=now,
    )
    if replay is not None:
        return replay

    session.add(
        IdempotencyRecordModel(
            key=key,
            endpoint=endpoint,
            actor_id=actor_id,
            request_fingerprint=request_fingerprint,
            status_code=IN_FLIGHT,
            response_json="{}",
            created_at=now,
            expires_at=now + timedelta(seconds=ttl_seconds),
        )
    )
    try:
        await session.commit()
    except IntegrityError:
        # Another request won the race between the read above and this insert.
        # The primary key is what decides, not our read — so re-read and let the
        # in-flight/replay rules answer.
        await session.rollback()
        replay = await _existing(
            session,
            key=key,
            endpoint=endpoint,
            actor_id=actor_id,
            request_fingerprint=request_fingerprint,
            now=now,
        )
        if replay is not None:
            return replay
        raise _conflict(
            "An identical request with this Idempotency-Key is still in flight. "
            "Retry shortly to receive its result.",
            retryable=True,
        )
    return None


async def complete(
    session: AsyncSession,
    *,
    key: str,
    endpoint: str,
    actor_id: str,
    status_code: int,
    body: dict,
    request_fingerprint: str | None = None,
    ttl_seconds: int = DEFAULT_TTL_SECONDS,
    now: datetime | None = None,
) -> None:
    """Attach the finished response to a reservation this caller won.

    Two cases that look like nothing and are not:

    - **the reservation is gone** (swept, or its short in-flight window elapsed).
      Returning silently would leave no record of a write that did happen, and
      the next identical request would execute it again — the double approval
      this module exists to prevent, reached without any concurrency. The record
      is re-created instead.
    - **the reservation is already completed.** Overwriting would replace the
      canonical replay of a 200 with, say, a 500. A completed record is final.
    """
    now = now or datetime.now(timezone.utc)
    record = await session.get(IdempotencyRecordModel, (key, endpoint, actor_id))
    if record is None:
        session.add(
            IdempotencyRecordModel(
                key=key,
                endpoint=endpoint,
                actor_id=actor_id,
                request_fingerprint=request_fingerprint or "",
                status_code=status_code,
                response_json=json.dumps(body, ensure_ascii=True),
                created_at=now,
                expires_at=now + timedelta(seconds=ttl_seconds),
            )
        )
        await session.commit()
        return
    if record.status_code != IN_FLIGHT:
        return
    record.status_code = status_code
    record.response_json = json.dumps(body, ensure_ascii=True)
    record.expires_at = now + timedelta(seconds=ttl_seconds)
    await session.commit()


async def release(
    session: AsyncSession,
    *,
    key: str,
    endpoint: str,
    actor_id: str,
) -> None:
    """Drop a reservation whose write failed, so the client may try again.

    Without this, a handler that raised would leave the key claimed until its
    TTL expired and every retry would be told "still in flight" — turning one
    transient failure into a day of refusals.
    """
    record = await session.get(IdempotencyRecordModel, (key, endpoint, actor_id))
    if record is not None and record.status_code == IN_FLIGHT:
        await session.delete(record)
        await session.commit()


async def remember(
    session: AsyncSession,
    *,
    key: str,
    endpoint: str,
    actor_id: str,
    request_fingerprint: str,
    status_code: int,
    body: dict,
    ttl_seconds: int = DEFAULT_TTL_SECONDS,
    now: datetime | None = None,
) -> None:
    """Reserve and complete in one step. For a write already known to be done.

    If the key is already completed this is a no-op: `reserve` returns the stored
    response and it is kept. Discarding that return value overwrote a recorded
    200 with a later 500, which is the opposite of what an idempotency record is
    for.
    """
    replay = await reserve(
        session,
        key=key,
        endpoint=endpoint,
        actor_id=actor_id,
        request_fingerprint=request_fingerprint,
        ttl_seconds=ttl_seconds,
        now=now,
    )
    if replay is not None:
        return
    await complete(
        session,
        key=key,
        endpoint=endpoint,
        actor_id=actor_id,
        status_code=status_code,
        body=body,
        request_fingerprint=request_fingerprint,
        ttl_seconds=ttl_seconds,
        now=now,
    )


async def purge_expired(session: AsyncSession, *, now: datetime | None = None) -> int:
    """Drop records past their TTL. Returns how many were removed."""
    now = now or datetime.now(timezone.utc)
    expired = (
        await session.execute(
            select(IdempotencyRecordModel.key, IdempotencyRecordModel.endpoint, IdempotencyRecordModel.actor_id)
            .where(IdempotencyRecordModel.expires_at <= now)
        )
    ).all()
    if not expired:
        return 0
    await session.execute(
        delete(IdempotencyRecordModel).where(IdempotencyRecordModel.expires_at <= now)
    )
    await session.commit()
    return len(expired)
