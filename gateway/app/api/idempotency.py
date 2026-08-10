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
from uuid import uuid4
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

# The abandonment window is a guess about how long a handler can legitimately
# take, and a handler slower than it would otherwise have its claim taken over
# while still running — executing the write twice, which is the one thing this
# module exists to prevent. So a claim carries a token: whoever took it over
# owns it, and the original holder's `complete` is refused rather than allowed
# to overwrite someone else's result.
CLAIM_TOKEN_FIELD = "claim"

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


class Claim:
    """Proof that this caller, and not a later one, owns the reservation."""

    __slots__ = ("token",)

    def __init__(self, token: str) -> None:
        self.token = token


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def _claim_token(record: IdempotencyRecordModel) -> str | None:
    """The token stored with an unfinished reservation, if any."""
    try:
        stored = json.loads(record.response_json or "{}")
    except ValueError:
        return None
    return stored.get(CLAIM_TOKEN_FIELD) if isinstance(stored, dict) else None


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
) -> ReplayedResponse | Claim:
    """Claim this key before doing the work.

    Returns a `ReplayedResponse` when the operation already completed — return
    it and do nothing else. Returns a `Claim` when this caller won: perform the
    write, then pass the claim to `complete` (or to `release` if it fails).

    The claim is a token, not a boolean, because the abandonment window is a
    guess. A handler slower than `IN_FLIGHT_TIMEOUT_SECONDS` would otherwise
    have its reservation taken over while still running, both callers would
    execute the write, and the first one's `complete` would overwrite the
    second's result. With a token, a `complete` from a superseded holder is
    refused instead.

    Raises `conflict` when the key was used for a different body, or when an
    identical request is still in flight and not yet abandoned.
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

    token = uuid4().hex
    session.add(
        IdempotencyRecordModel(
            key=key,
            endpoint=endpoint,
            actor_id=actor_id,
            request_fingerprint=request_fingerprint,
            status_code=IN_FLIGHT,
            response_json=json.dumps({CLAIM_TOKEN_FIELD: token}),
            created_at=now,
            expires_at=now + timedelta(seconds=ttl_seconds),
        )
    )
    try:
        await session.commit()
    except IntegrityError:
        # Another request won the race between the read above and this insert.
        # The primary key decides, not our read — re-read and let the
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
    return Claim(token)


async def complete(
    session: AsyncSession,
    *,
    key: str,
    endpoint: str,
    actor_id: str,
    status_code: int,
    body: dict,
    claim: Claim,
    request_fingerprint: str,
    ttl_seconds: int = DEFAULT_TTL_SECONDS,
    now: datetime | None = None,
) -> bool:
    """Attach the finished response to a reservation this caller still owns.

    Returns whether the response was recorded. Three cases that look like
    nothing and are not:

    - **the reservation is gone** (swept, or its abandonment window elapsed and
      nobody else took it). Returning silently would leave no record of a write
      that did happen, and the next identical request would execute it again.
      The record is re-created, carrying the real fingerprint — writing `""`
      there made every later legitimate retry look like a body mismatch and get
      a non-retryable 409 for the full TTL.
    - **the reservation is already completed.** A completed record is final;
      overwriting would replace the canonical replay of a 200 with, say, a 500.
    - **the claim was taken over** by a later caller after the abandonment
      window. That caller owns the outcome now, so this one's result is
      discarded rather than allowed to overwrite it.
    """
    now = now or datetime.now(timezone.utc)
    record = await session.get(IdempotencyRecordModel, (key, endpoint, actor_id))
    if record is None:
        session.add(
            IdempotencyRecordModel(
                key=key,
                endpoint=endpoint,
                actor_id=actor_id,
                request_fingerprint=request_fingerprint,
                status_code=status_code,
                response_json=json.dumps(body, ensure_ascii=True),
                created_at=now,
                expires_at=now + timedelta(seconds=ttl_seconds),
            )
        )
        await session.commit()
        return True
    if record.status_code != IN_FLIGHT:
        return False
    if _claim_token(record) != claim.token:
        return False
    record.status_code = status_code
    record.response_json = json.dumps(body, ensure_ascii=True)
    record.expires_at = now + timedelta(seconds=ttl_seconds)
    await session.commit()
    return True


async def release(
    session: AsyncSession,
    *,
    key: str,
    endpoint: str,
    actor_id: str,
    claim: Claim,
) -> None:
    """Drop a reservation whose write failed, so the client may try again.

    Only the current holder may release. Without the claim check, a caller whose
    reservation was already taken over would delete the new holder's claim on
    its way out.

    Without `release` at all, a handler that raised would leave the key claimed
    until its window elapsed and every retry would be told "still in flight" —
    turning one transient failure into a stretch of refusals.
    """
    record = await session.get(IdempotencyRecordModel, (key, endpoint, actor_id))
    if record is None or record.status_code != IN_FLIGHT:
        return
    if _claim_token(record) != claim.token:
        return
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
    """Reserve and complete in one step, for a write already known to be done.

    If the key is already completed this is a no-op: `reserve` returns the
    stored response and it is kept. Discarding that return value overwrote a
    recorded 200 with a later 500, which is the opposite of what an idempotency
    record is for.
    """
    outcome = await reserve(
        session,
        key=key,
        endpoint=endpoint,
        actor_id=actor_id,
        request_fingerprint=request_fingerprint,
        ttl_seconds=ttl_seconds,
        now=now,
    )
    if not isinstance(outcome, Claim):
        return
    await complete(
        session,
        key=key,
        endpoint=endpoint,
        actor_id=actor_id,
        status_code=status_code,
        body=body,
        claim=outcome,
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
