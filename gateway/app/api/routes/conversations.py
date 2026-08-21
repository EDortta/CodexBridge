"""Conversations and contextual messaging — issue #10.

A **conversation** is a thread linked to one or more product entities — a
project, a session/decision/mission (all the same `TaskModel`, under three
vocabularies — see `docs/api/README.md`'s "Decisions" and "Missions"
sections), or an issue. Every conversation carries at least one such
**context reference**, resolved and authorization-checked the same way
`epics.py:link_issue` resolves both sides of an epic-issue link: the route
loads each referenced entity through the existing `*_for_projects` getter, so
a reference to an entity the caller cannot see is indistinguishable from a
reference to one that does not exist — both answer `404`, never a `400` that
would confirm existence to someone who was not given it.

## Why `artifact` is not a context type

See `gateway/app/services/conversation_types.py`'s module docstring. In
short: five of the six entity kinds issue #10 names have a backing model
this build can check a reference against; `artifact` does not (issue #11
has not shipped `ArtifactModel`), so it is omitted from the context type
vocabulary rather than accepted and left unverifiable — which would be
exactly the acceptance criterion this validation exists to satisfy, broken
for one type. Message **attachments** are unaffected: they are opaque
artifact/file identifiers on the message itself, recorded and returned
unvalidated for the same reason `IssueModel.dependencies_json` does not own
a graph.

## Unread and last-activity, without a "mark as read" endpoint

Issue #10 names no such endpoint, so the read cursor
(`ConversationReadStateModel`) can only move as a side effect of an endpoint
that already exists:

- `GET .../messages` advances the caller's cursor to the newest message
  **actually returned in that page** — not to "now". A client paging forward
  from the oldest message must not have messages it has not fetched yet
  marked as seen just because it fetched an earlier page.
- `POST .../messages` advances the sender's own cursor to the message just
  sent, so posting does not leave the sender's own conversation reported
  back to them as unread.
- Creating a conversation marks its creator caught up immediately: they were
  just looking at what they wrote.

`unread` is therefore a real, changing value rather than a field that can
only ever read one way — the same discipline `docs/api/README.md` already
applies to `probes.CAPABILITIES` and to issue #7's dropped `dependencies`
field: no permanently-stuck field ships.

## Ordering: conversations list is stable, not "most recent first"

`GET /conversations` orders by `createdAt`/`id` — creation order — never by
`lastActivityAt`. Sorting by an activity timestamp would move a
conversation's position in the list the instant a new message lands, which
can skip or repeat rows across a paginated walk. That is the direct opposite
of the acceptance criterion ("pagination preserves stable ordering").
`lastActivityAt` is still reported on every item for a client that wants to
sort the page itself. `GET .../messages` is oldest-first, the same
reasoning `store.list_task_events_page` gives for a mission's timeline: a
thread is read forward from where it starts, unlike every newest-first
collection elsewhere in this API.

## Idempotency, reused rather than reinvented

`POST /conversations` and `POST .../messages` both accept `Idempotency-Key`
and follow `routes/issues.py:create_issue`'s reserve-then-complete shape
exactly, including the endpoint-is-a-constant-template convention
`routes/epics.py:link_issue` establishes: the idempotency `endpoint` key is
the literal route template, not the interpolated path, because the
fingerprint (which does embed the concrete ids and body) is what tells a key
reused for a genuinely different operation apart — a same-key,
different-fingerprint retry is answered `409`, never silently replayed.
"""

from __future__ import annotations

import json

from fastapi import APIRouter, Depends, Header, Query, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from gateway.app.api import idempotency, pagination, permissions, timestamps
from gateway.app.api.auth import require_action, visible_projects
from gateway.app.api.errors import NOT_FOUND, VALIDATION_FAILED, ApiError
from gateway.app.core.users import AuthenticatedPrincipal
from gateway.app.db.session import get_session
from gateway.app.services import store
from gateway.app.services.conversation_types import CONTEXT_TYPES, ConversationPlanningError


router = APIRouter(prefix="/api/v1")

CONVERSATIONS_ENDPOINT = "/api/v1/conversations"


def _conversation_not_found() -> ApiError:
    return ApiError(status_code=404, code=NOT_FOUND, message="No such conversation.")


def _context_not_found(context_type: str) -> ApiError:
    # Same message-shape rule epics.py/issues.py use for a hidden project: a
    # context reference the caller cannot see must answer exactly like one
    # that does not exist.
    return ApiError(status_code=404, code=NOT_FOUND, message=f"No such {context_type}.")


def _invalid_context_type(value: str) -> ApiError:
    return ApiError(
        status_code=400,
        code=VALIDATION_FAILED,
        message=f"context[].type must be one of {sorted(CONTEXT_TYPES)}.",
        details=[
            {
                "field": "/context",
                "code": "invalid_context_type",
                "message": f"{value!r} is not a supported context type.",
            }
        ],
    )


def _mixed_project_context() -> ApiError:
    return ApiError(
        status_code=400,
        code=VALIDATION_FAILED,
        message="Every context reference must resolve to the same project.",
        details=[
            {
                "field": "/context",
                "code": "mixed_project",
                "message": "context references named more than one project.",
            }
        ],
    )


def _planning_error(exc: ConversationPlanningError) -> ApiError:
    return ApiError(
        status_code=400,
        code=VALIDATION_FAILED,
        message=exc.message,
        details=[{"field": exc.field, "code": exc.code, "message": exc.message}],
    )


def _conversation_dto(conversation, *, unread: bool) -> dict:
    return {
        "id": conversation.id,
        "projectId": conversation.project_id,
        "title": conversation.title,
        "context": json.loads(conversation.context_json or "[]"),
        "unread": unread,
        "lastActivityAt": timestamps.utc_z(conversation.last_activity_at),
        "createdAt": timestamps.utc_z(conversation.created_at),
        "createdBy": conversation.created_by_email or conversation.created_by_user_id,
    }


def _message_dto(message) -> dict:
    return {
        "id": message.id,
        "conversationId": message.conversation_id,
        "author": message.author_email or message.author_user_id,
        "body": message.body,
        "attachments": json.loads(message.attachments_json or "[]"),
        "createdAt": timestamps.utc_z(message.created_at),
    }


def _effective_project_ids(
    principal: AuthenticatedPrincipal, requested: list[str] | None
) -> list[str] | None:
    """`visible_projects`, narrowed by an explicit `projectId` filter.

    Same helper `routes/missions.py` keeps as its own local copy rather than
    a shared one: a requested project outside the caller's visibility is
    dropped rather than surfaced as an error, so a filter naming a project
    the caller cannot see cannot become a way to probe which ids exist.
    """
    visible = visible_projects(principal)
    if requested is None:
        return visible
    if visible is None:
        return requested
    allowed = set(visible)
    return [project_id for project_id in requested if project_id in allowed]


class ContextReference(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    type: str = Field(min_length=1, max_length=32)
    id: str = Field(min_length=1, max_length=128)


class CreateConversationRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    title: str | None = Field(default=None, max_length=255)
    # `min_length=1` is the acceptance criterion itself ("every conversation
    # has at least one explicit context reference") — enforced by the request
    # never reaching the handler, the same way `DecisionRejectRequest.reason`
    # enforces "not empty".
    context: list[ContextReference] = Field(min_length=1, max_length=16)


class CreateMessageRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    # Markdown source. The server stores and returns it unrendered.
    body: str = Field(min_length=1, max_length=50000)
    attachments: list[str] | None = Field(default=None, max_length=20)


@router.get("/conversations", tags=["conversations"])
async def list_conversations(
    response: Response,
    project_id: list[str] | None = Query(default=None, alias="projectId"),
    cursor: str | None = Query(default=None),
    limit: int | None = Query(default=None),
    principal: AuthenticatedPrincipal = Depends(require_action(permissions.CONVERSATIONS_READ)),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Conversations the caller may see, newest-created first."""
    projects = visible_projects(principal)
    effective_projects = _effective_project_ids(principal, project_id)
    size = pagination.parse_limit(limit)

    scope = pagination.scope_digest(
        CONVERSATIONS_ENDPOINT,
        {
            "projectId": sorted(project_id) if project_id else None,
            "actor": principal.user_id,
            "projects": sorted(projects) if projects is not None else "*",
        },
    )
    after = None
    if cursor:
        position = pagination.decode_cursor(scope, cursor, expect={"createdAt": str, "id": str})
        after = (position["createdAt"], position["id"])

    rows = await store.list_conversations_page(
        session, project_ids=effective_projects, after=after, limit=size
    )
    page, info = pagination.paginate(
        rows,
        limit=size,
        scope=scope,
        position_of=lambda c: {"createdAt": timestamps.cursor_z(c.created_at), "id": c.id},
    )
    read_states = await store.conversation_read_states(
        session, user_id=principal.user_id, conversation_ids=[c.id for c in page]
    )
    response.headers["Cache-Control"] = "no-store"
    return {
        "items": [
            _conversation_dto(
                c,
                unread=store.conversation_unread(
                    last_activity_at=c.last_activity_at, last_read_at=read_states.get(c.id)
                ),
            )
            for c in page
        ],
        "page": info,
    }


@router.get("/conversations/{conversation_id}", tags=["conversations"])
async def get_conversation(
    conversation_id: str,
    response: Response,
    principal: AuthenticatedPrincipal = Depends(require_action(permissions.CONVERSATIONS_READ)),
    session: AsyncSession = Depends(get_session),
) -> dict:
    conversation = await store.get_conversation_for_projects(
        session, conversation_id, visible_projects(principal)
    )
    if conversation is None:
        raise _conversation_not_found()
    read_states = await store.conversation_read_states(
        session, user_id=principal.user_id, conversation_ids=[conversation.id]
    )
    response.headers["Cache-Control"] = "no-store"
    return _conversation_dto(
        conversation,
        unread=store.conversation_unread(
            last_activity_at=conversation.last_activity_at,
            last_read_at=read_states.get(conversation.id),
        ),
    )


@router.get("/conversations/{conversation_id}/messages", tags=["conversations"])
async def list_messages(
    conversation_id: str,
    response: Response,
    cursor: str | None = Query(default=None),
    limit: int | None = Query(default=None),
    principal: AuthenticatedPrincipal = Depends(require_action(permissions.CONVERSATIONS_READ)),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """A conversation's messages, oldest first."""
    conversation = await store.get_conversation_for_projects(
        session, conversation_id, visible_projects(principal)
    )
    if conversation is None:
        raise _conversation_not_found()

    size = pagination.parse_limit(limit)
    scope = pagination.scope_digest(
        f"{CONVERSATIONS_ENDPOINT}/{conversation_id}/messages",
        {"conversationId": conversation_id, "actor": principal.user_id},
    )
    after = None
    if cursor:
        position = pagination.decode_cursor(scope, cursor, expect={"createdAt": str, "id": str})
        after = (position["createdAt"], position["id"])

    rows = await store.list_conversation_messages_page(
        session, conversation_id=conversation_id, after=after, limit=size
    )
    page, info = pagination.paginate(
        rows,
        limit=size,
        scope=scope,
        position_of=lambda m: {"createdAt": timestamps.cursor_z(m.created_at), "id": m.id},
    )

    # Advance the caller's read cursor to the newest message *in this page*,
    # not to "now" — see the module docstring's "Unread and last-activity"
    # section for why marking further than what was actually fetched is wrong.
    newest_fetched = max((m.created_at for m in page), default=None)
    if newest_fetched is not None:
        await store.mark_conversation_read(
            session, conversation_id=conversation_id, user_id=principal.user_id, at=newest_fetched
        )
        await session.commit()

    response.headers["Cache-Control"] = "no-store"
    return {"items": [_message_dto(m) for m in page], "page": info}


@router.post("/conversations", tags=["conversations"], status_code=201)
async def create_conversation(
    payload: CreateConversationRequest,
    response: Response,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    principal: AuthenticatedPrincipal = Depends(require_action(permissions.CONVERSATIONS_CREATE)),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Start a conversation. Every context reference is resolved and checked here.

    `projectId` is not a request field: the conversation's project is derived
    from its context references, and every reference must agree on the same
    one (`400 mixed_project` otherwise) — see the module docstring.
    """
    projects = visible_projects(principal)

    ordered_context: list[dict] = []
    seen: set[tuple[str, str]] = set()
    resolved_project_ids: set[str] = set()
    for ref in payload.context:
        key = (ref.type, ref.id)
        if key in seen:
            continue
        seen.add(key)

        if ref.type not in CONTEXT_TYPES:
            raise _invalid_context_type(ref.type)
        if ref.type == "project":
            entity = await store.get_project_for_caller(session, ref.id, projects)
        elif ref.type == "issue":
            entity = await store.get_issue_for_projects(session, ref.id, projects)
        else:
            # "session" and "decision" and "mission" are the same TaskModel
            # under three vocabularies — see the module docstring.
            entity = await store.get_task_for_projects(session, ref.id, projects)
        if entity is None:
            raise _context_not_found(ref.type)

        resolved_project_ids.add(entity.id if ref.type == "project" else entity.project_id)
        ordered_context.append({"type": ref.type, "id": ref.id})

    if len(resolved_project_ids) > 1:
        raise _mixed_project_context()
    project_id = next(iter(resolved_project_ids))

    fingerprint = idempotency.fingerprint(
        json.dumps(
            {"projectId": project_id, "title": payload.title, "context": ordered_context},
            sort_keys=True,
        ).encode()
    )
    claim = None
    if idempotency_key:
        outcome = await idempotency.reserve(
            session,
            key=idempotency_key,
            endpoint=CONVERSATIONS_ENDPOINT,
            actor_id=principal.user_id,
            request_fingerprint=fingerprint,
        )
        if isinstance(outcome, idempotency.ReplayedResponse):
            response.status_code = outcome.status_code
            response.headers["Idempotent-Replay"] = "true"
            return outcome.body
        claim = outcome

    try:
        conversation = await store.create_conversation(
            session,
            project_id=project_id,
            title=payload.title,
            context=ordered_context,
            actor_user_id=principal.user_id,
            actor_email=principal.email,
        )
    except ConversationPlanningError as exc:
        if claim is not None:
            await idempotency.release(
                session, key=idempotency_key, endpoint=CONVERSATIONS_ENDPOINT,
                actor_id=principal.user_id, claim=claim,
            )
        raise _planning_error(exc) from exc
    except Exception:
        if claim is not None:
            await idempotency.release(
                session, key=idempotency_key, endpoint=CONVERSATIONS_ENDPOINT,
                actor_id=principal.user_id, claim=claim,
            )
        raise

    # The creator is caught up by construction (store.create_conversation
    # records their read state at creation time).
    body = _conversation_dto(conversation, unread=False)
    if claim is not None:
        await idempotency.complete(
            session,
            key=idempotency_key,
            endpoint=CONVERSATIONS_ENDPOINT,
            actor_id=principal.user_id,
            status_code=201,
            body=body,
            claim=claim,
            request_fingerprint=fingerprint,
        )
    return body


@router.post("/conversations/{conversation_id}/messages", tags=["conversations"], status_code=201)
async def post_message(
    conversation_id: str,
    payload: CreateMessageRequest,
    response: Response,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    principal: AuthenticatedPrincipal = Depends(require_action(permissions.CONVERSATIONS_POST_MESSAGE)),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Post a message. `Idempotency-Key` is what makes an offline retry safe.

    A mobile client that loses the network right after sending cannot know
    whether the message landed; retrying with the same key returns the first
    response rather than posting a second copy — the acceptance criterion
    this endpoint exists to satisfy.
    """
    conversation = await store.get_conversation_for_projects(
        session, conversation_id, visible_projects(principal)
    )
    if conversation is None:
        raise _conversation_not_found()

    # Literal route template, not the interpolated path — see the module
    # docstring's "Idempotency, reused rather than reinvented" section.
    endpoint = f"{CONVERSATIONS_ENDPOINT}/{{conversationId}}/messages"
    fingerprint = idempotency.fingerprint(
        json.dumps(
            {"conversationId": conversation_id, "body": payload.body, "attachments": payload.attachments or []},
            sort_keys=True,
        ).encode()
    )
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
        message = await store.create_conversation_message(
            session,
            conversation_id=conversation_id,
            author_user_id=principal.user_id,
            author_email=principal.email,
            body=payload.body,
            attachments=payload.attachments,
        )
    except ConversationPlanningError as exc:
        if claim is not None:
            await idempotency.release(
                session, key=idempotency_key, endpoint=endpoint, actor_id=principal.user_id, claim=claim
            )
        raise _planning_error(exc) from exc
    except Exception:
        if claim is not None:
            await idempotency.release(
                session, key=idempotency_key, endpoint=endpoint, actor_id=principal.user_id, claim=claim
            )
        raise

    body = _message_dto(message)
    if claim is not None:
        await idempotency.complete(
            session,
            key=idempotency_key,
            endpoint=endpoint,
            actor_id=principal.user_id,
            status_code=201,
            body=body,
            claim=claim,
            request_fingerprint=fingerprint,
        )
    return body
