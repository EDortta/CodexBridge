"""What this actor wants to be notified about — issue #13.

Two operations over one document: `GET /api/v1/notifications/preferences` and
`PUT` of the same shape back. One row per actor, keyed by the `user_id` from
`users.json`.

## Recorded intent, not a delivery mechanism, and not a stream filter

There is no push transport in this build — `GET /api/version` reports
`pushNotifications`/`artifactDownloads` style flags for exactly this reason, and
nothing reads these rows to decide delivery. They are the hook a later push
integration reads, stored now so a client can offer the setting and so the
choice survives a reinstall.

They also **do not filter `GET /api/v1/events/stream`**, and that is a decision
rather than an omission. A client that opened the stream asked for the stream;
withholding events from it because of a preference set on another device is how
a phone silently misses the decision its operator was waiting for, and the
failure would be invisible from the client side — indistinguishable from a quiet
system. A client that wants a narrower live feed says so per connection, with
`?type=`, which is per-connection state and cannot be changed underneath it.
`docs/api/README.md` §"Events and notifications (issue #13)" states this to the
client author in the same words.

## No `ETag`, no `If-Match`

The only writer of a row is the actor it belongs to, through a `PUT` that
replaces the document wholesale. Optimistic concurrency protects against a
concurrent *third party*, and there is not one: two devices of the same person
racing is last-write-wins on a two-field preference, which is what the person
would expect either way. `ConversationModel` is this schema's other
revision-less table for a related reason (`docs/api/README.md` §"No `revision`,
no `ETag`, no `If-Match`").

## Reading is `notifications.read`, writing is `notifications.manage`

Two actions, because an operator may want a phone that can watch the event
stream without that phone being able to rewrite what the account gets notified
about. Reading needs only `codexbridge.read`; the write has a scope of its own.
"""

from __future__ import annotations

import json

from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from gateway.app.api import permissions
from gateway.app.api.auth import require_action
from gateway.app.api.errors import VALIDATION_FAILED, ApiError
from gateway.app.api.timestamps import utc_z
from gateway.app.core.users import AuthenticatedPrincipal
from gateway.app.db.session import get_session
from gateway.app.services import event_types, store


router = APIRouter(prefix="/api/v1")

# Bounded independently of `ALL_EVENT_TYPES`'s current size. The list is stored
# as JSON text and echoed back to its author, so its length is caller-controlled
# input to a database column; a subset of a closed vocabulary can never
# legitimately need more entries than the vocabulary has, and the ceiling has to
# be a constant rather than `len(ALL_EVENT_TYPES)` so that adding a type cannot
# quietly widen an accepted request body.
MAX_SUBSCRIBED_TYPES = 64


class NotificationPreferencesRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    # Validated against the published vocabulary in the handler rather than with
    # a Pydantic `Literal[...]`: the rejection has to be an `Error` envelope with
    # a `details[].field` naming `eventTypes`, and a 422 from the model layer
    # names the Python field and lists every allowed value back at the caller.
    event_types: list[str] = Field(default_factory=list, alias="eventTypes", max_length=MAX_SUBSCRIBED_TYPES)
    push_enabled: bool = Field(default=False, alias="pushEnabled")


def _body(event_types_json: str | None, push_enabled: bool, updated_at) -> dict:
    """The document, from a row or from the absence of one.

    `eventTypes` is re-validated against the current vocabulary on the way
    **out**, not only on the way in. A stored value can outlive the type it
    names — a later build that retires an event type would otherwise keep
    handing a client a subscription to something that no longer exists, and the
    client would echo it back on its next `PUT` and be rejected for a value it
    never chose.
    """
    try:
        stored = json.loads(event_types_json or "[]")
    except (TypeError, ValueError):
        stored = []
    known = [
        value
        for value in (stored if isinstance(stored, list) else [])
        if isinstance(value, str) and value in event_types.ALL_EVENT_TYPES
    ]
    return {
        "eventTypes": sorted(set(known)),
        "pushEnabled": bool(push_enabled),
        # Null when the actor has never saved preferences, so a client can tell
        # "defaults, never touched" from "explicitly set to the defaults".
        "updatedAt": utc_z(updated_at) if updated_at is not None else None,
        # Stated in the payload, not only in the prose: a client rendering a
        # "push notifications" switch needs to know, at the moment it renders
        # it, that saving the setting will not make anything arrive yet.
        "pushDeliveryAvailable": False,
    }


@router.get("/notifications/preferences", tags=["notifications"])
async def get_preferences(
    response: Response,
    principal: AuthenticatedPrincipal = Depends(require_action(permissions.NOTIFICATIONS_READ)),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """This actor's preferences, or the defaults when nothing was ever saved.

    Always this actor's own. There is no `userId` parameter and no admin
    override: a preference document is personal data, and an endpoint that could
    read another account's would be a disclosure with no product behind it.
    """
    row = await store.get_notification_preference(session, principal.user_id)
    response.headers["Cache-Control"] = "no-store"
    if row is None:
        return _body(None, False, None)
    return _body(row.event_types_json, row.push_enabled, row.updated_at)


@router.put("/notifications/preferences", tags=["notifications"])
async def put_preferences(
    payload: NotificationPreferencesRequest,
    response: Response,
    principal: AuthenticatedPrincipal = Depends(require_action(permissions.NOTIFICATIONS_MANAGE)),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Replace this actor's preferences.

    A full replacement, and idempotent by construction: the same body sent twice
    produces the same document. That is why there is no `Idempotency-Key` here —
    the header exists so a retried *creating* write does not create twice, and a
    `PUT` of a single document owned by one actor has nothing to duplicate.
    """
    unknown = sorted({value for value in payload.event_types if value not in event_types.ALL_EVENT_TYPES})
    if unknown:
        raise ApiError(
            status_code=400,
            code=VALIDATION_FAILED,
            message="Unknown event type in the subscription list.",
            details=[
                {"field": "eventTypes", "code": "unknown_event_type", "message": f"No such event type: {value}."}
                for value in unknown
            ],
        )

    row = await store.set_notification_preference(
        session,
        user_id=principal.user_id,
        event_types=list(payload.event_types),
        push_enabled=payload.push_enabled,
    )
    response.headers["Cache-Control"] = "no-store"
    return _body(row.event_types_json, row.push_enabled, row.updated_at)
