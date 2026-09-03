"""REST surface for reminders — issue #72, the second transport in front of

#71's `gateway/app/services/google_calendar.py`. The mobile client speaks
`/api/v1/*` and cannot call `/mcp`, so this is not a second implementation:
`create_reminder`/`cancel_reminder` are called exactly as
`gateway/app/mcp/server.py` calls them, and `list_reminders` (new in this
module's target service, see that module's own docstring) is a REST-only
capability #71 deliberately did not ship.

## Why identity, not the request body, drives `requested_by` and the list filter

`text`/`when`/`notes`/`leadMinutes` mirror #71's tool schema field-for-field,
camelCased to match every other request/response in this contract (the MCP
tool arguments are snake_case because that is MCP's own convention, not this
one). `principal.email` — the authenticated caller, never anything the client
sends — is what `google_calendar.create_reminder`'s `user_id` becomes and what
`list_reminders`'s `requested_by` filter narrows to, the same
`design-standards.md` §4 rule every other write on this surface follows:
identity comes from the token, not the body.

## Error mapping: one shape, matching MCP

`CalendarConfigError` (the gateway itself is not set up) answers `503
dependency_unavailable`; `CalendarAccessError` (Google refused the request, or
a value like `when` failed the service's own validation) answers `409
conflict`. Both carry the exact message text `google_calendar.py` raised —
required by the issue: an unconfigured or misshared calendar must read
identically on this transport and on `/mcp`, so a support conversation about
"reminders aren't working" gets one explanation regardless of client.

Collapsing `CalendarAccessError` to one status means a `when` in the past and a
Google 403 answer the same code, which a REST purist would split. `#71` already
made that call for `/mcp` (`gateway/app/mcp/server.py` maps both to `409`), and
splitting it here would need a distinct exception type in
`google_calendar.py` — a change to a module this issue keeps unchanged. Noted,
not fixed: see this delivery's own report.

## Why no `If-Match`

Every other write on this contract protects a local, revisioned row. A
reminder has none — its only state of record is the Calendar event itself,
which this module never reads back before writing (the same reason `#71`
gives for using a deterministic id instead of a lookup). There is nothing
local to race against.

## Why `GET`'s pagination is not `pagination.py`

That module's cursors are HMAC-signed over an endpoint+filter digest, meant for
this gateway's own keyset-paginated queries. This collection is paged by
Google's own `nextPageToken`, already opaque and already single-purpose to
this one call — wrapping it in a second envelope would teach a client two
cursor dialects for one field. It is still returned under the contract's
`PageInfo` shape (`page.hasMore` / `page.nextCursor`) via
`pagination.page_info`, and `limit` still runs through `pagination.parse_limit`
for the same ceiling every other collection enforces.
"""

from __future__ import annotations

import httpx
from fastapi import APIRouter, Depends, Header, Query, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from gateway.app.api import idempotency, pagination, permissions
from gateway.app.api.auth import require_action
from gateway.app.api.errors import CONFLICT, DEPENDENCY_UNAVAILABLE, ApiError
from gateway.app.core.config import settings
from gateway.app.core.users import AuthenticatedPrincipal
from gateway.app.db.session import get_session
from gateway.app.services import google_calendar


router = APIRouter(prefix="/api/v1")

REMINDERS_ENDPOINT = "/api/v1/reminders"


def _calendar_config() -> google_calendar.CalendarConfig:
    return google_calendar.CalendarConfig(
        credentials_file=settings.google_calendar_credentials_file or "",
        calendar_id=settings.google_calendar_id or "",
    )


def _calendar_error(exc: Exception) -> ApiError:
    if isinstance(exc, google_calendar.CalendarConfigError):
        return ApiError(status_code=503, code=DEPENDENCY_UNAVAILABLE, message=str(exc))
    return ApiError(status_code=409, code=CONFLICT, message=str(exc))


def _reminder_dto(result: dict, *, notes: str | None, created: bool | None = None) -> dict:
    dto: dict = {
        "id": result.get("reminder_id"),
        "text": result.get("summary") or "",
        "when": result.get("scheduled_for"),
        "notes": notes,
        "leadMinutes": result.get("lead_minutes", 0),
        "calendarId": result.get("calendar_id"),
        "timezone": result.get("timezone"),
        "htmlLink": result.get("html_link"),
    }
    if created is not None:
        dto["created"] = created
    return dto


class CreateReminderRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    text: str = Field(min_length=1, max_length=200)
    # Plain string, not the contract's `Timestamp` schema: `Timestamp` forces a
    # UTC `Z` instant, and a reminder must echo the caller's own offset back
    # unchanged (`google_calendar.py`'s own docstring on why `when` is
    # ISO 8601 with an explicit offset, computed by the caller).
    when: str = Field(min_length=1, max_length=64)
    notes: str | None = Field(default=None, max_length=4000)
    lead_minutes: int = Field(default=0, ge=0, le=40320, alias="leadMinutes")
    idempotency_key: str | None = Field(default=None, min_length=1, max_length=128, alias="idempotencyKey")


@router.post("/reminders", tags=["reminders"], status_code=201)
async def create_reminder(
    payload: CreateReminderRequest,
    response: Response,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    principal: AuthenticatedPrincipal = Depends(require_action(permissions.REMINDERS_CREATE)),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Create a reminder on the operator's Google Calendar.

    Two independent idempotency layers, both optional and both safe to use
    together: the `Idempotency-Key` header (this endpoint's own HTTP-level
    replay, `gateway/app/api/idempotency.py`, protecting a client that lost the
    network mid-request) and the body's `idempotencyKey` (folded into a
    deterministic Calendar event id inside `google_calendar.create_reminder`,
    the same mechanism `/mcp`'s `create_reminder` tool uses — protecting
    against a second, later, genuinely separate HTTP request asking for the
    same reminder again).
    """
    fingerprint = idempotency.fingerprint(
        f"create-reminder:{payload.text}:{payload.when}:{payload.idempotency_key}".encode()
    )
    claim = None
    if idempotency_key:
        outcome = await idempotency.reserve(
            session,
            key=idempotency_key,
            endpoint=REMINDERS_ENDPOINT,
            actor_id=principal.user_id,
            request_fingerprint=fingerprint,
        )
        if isinstance(outcome, idempotency.ReplayedResponse):
            response.status_code = outcome.status_code
            response.headers["Idempotent-Replay"] = "true"
            return outcome.body
        claim = outcome

    try:
        async with httpx.AsyncClient() as client:
            result = await google_calendar.create_reminder(
                config=_calendar_config(),
                client=client,
                user_id=principal.email,
                text=payload.text,
                when=payload.when,
                notes=payload.notes,
                lead_minutes=payload.lead_minutes,
                idempotency_key=payload.idempotency_key,
            )
    except (google_calendar.CalendarConfigError, google_calendar.CalendarAccessError) as exc:
        if claim is not None:
            await idempotency.release(
                session, key=idempotency_key, endpoint=REMINDERS_ENDPOINT, actor_id=principal.user_id, claim=claim
            )
        raise _calendar_error(exc) from exc
    except Exception:
        if claim is not None:
            await idempotency.release(
                session, key=idempotency_key, endpoint=REMINDERS_ENDPOINT, actor_id=principal.user_id, claim=claim
            )
        raise

    body = _reminder_dto(result, notes=payload.notes, created=result.get("created", True))
    if claim is not None:
        await idempotency.complete(
            session,
            key=idempotency_key,
            endpoint=REMINDERS_ENDPOINT,
            actor_id=principal.user_id,
            status_code=201,
            body=body,
            claim=claim,
            request_fingerprint=fingerprint,
        )
    response.headers["Cache-Control"] = "no-store"
    return body


@router.get("/reminders", tags=["reminders"])
async def list_reminders(
    response: Response,
    cursor: str | None = Query(default=None),
    limit: int | None = Query(default=None),
    principal: AuthenticatedPrincipal = Depends(require_action(permissions.REMINDERS_READ)),
) -> dict:
    """CodexBridge-created reminders on the operator's calendar, this actor's own.

    Filtered server-side to `extendedProperties.private.source = "codexbridge"`
    and to `requested_by = principal.email` — see
    `google_calendar.list_reminders`'s own docstring for why both are applied
    inside the Google query rather than after the fact. This is what keeps the
    endpoint from ever becoming a way to browse the operator's whole personal
    calendar, which is the issue's own named guard.
    """
    size = pagination.parse_limit(limit)
    try:
        async with httpx.AsyncClient() as client:
            result = await google_calendar.list_reminders(
                config=_calendar_config(),
                client=client,
                requested_by=principal.email,
                limit=size,
                page_token=cursor,
            )
    except (google_calendar.CalendarConfigError, google_calendar.CalendarAccessError) as exc:
        raise _calendar_error(exc) from exc

    next_token = result.get("next_page_token")
    response.headers["Cache-Control"] = "no-store"
    return {
        "items": [_reminder_dto(item, notes=item.get("notes")) for item in result.get("items", [])],
        "page": pagination.page_info(has_more=bool(next_token), next_cursor=next_token),
    }


@router.delete("/reminders/{reminder_id}", tags=["reminders"])
async def cancel_reminder(
    reminder_id: str,
    response: Response,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    principal: AuthenticatedPrincipal = Depends(require_action(permissions.REMINDERS_CANCEL)),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Cancel a previously created reminder.

    `google_calendar.cancel_reminder` treats an already-gone event (Google's
    `410`) as success — the caller's goal ("this reminder should not exist") is
    already true — so a retry after a lost response, with or without
    `Idempotency-Key`, never surfaces as an error.
    """
    endpoint = f"{REMINDERS_ENDPOINT}/{{id}}/cancel"
    fingerprint = idempotency.fingerprint(f"cancel-reminder:{reminder_id}".encode())
    claim = None
    if idempotency_key:
        outcome = await idempotency.reserve(
            session,
            key=idempotency_key,
            endpoint=endpoint,
            actor_id=principal.user_id,
            request_fingerprint=fingerprint,
        )
        if isinstance(outcome, idempotency.ReplayedResponse):
            response.status_code = outcome.status_code
            response.headers["Idempotent-Replay"] = "true"
            return outcome.body
        claim = outcome

    try:
        async with httpx.AsyncClient() as client:
            result = await google_calendar.cancel_reminder(
                config=_calendar_config(), client=client, reminder_id=reminder_id
            )
    except (google_calendar.CalendarConfigError, google_calendar.CalendarAccessError) as exc:
        if claim is not None:
            await idempotency.release(session, key=idempotency_key, endpoint=endpoint, actor_id=principal.user_id, claim=claim)
        raise _calendar_error(exc) from exc
    except Exception:
        if claim is not None:
            await idempotency.release(session, key=idempotency_key, endpoint=endpoint, actor_id=principal.user_id, claim=claim)
        raise

    body = {"id": result["reminder_id"], "cancelled": result["cancelled"]}
    if claim is not None:
        await idempotency.complete(
            session,
            key=idempotency_key,
            endpoint=endpoint,
            actor_id=principal.user_id,
            status_code=200,
            body=body,
            claim=claim,
            request_fingerprint=fingerprint,
        )
    response.headers["Cache-Control"] = "no-store"
    return body
