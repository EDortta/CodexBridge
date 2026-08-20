"""Epics — issue #8.

An epic groups issues within one project. This build owns epics and issues
itself: there is no GitHub sync yet. `EpicModel.provider` ("local" on every row
this build writes) is the seam a future sync would use to tell a
gateway-authored epic from a mirrored one, the same way `ProjectModel` already
mirrors `registry.json` rather than owning it — see
`docs/api/README.md` §"Epics and Issues" for why that seam is a column and not
a bigger abstraction with one implementation.
"""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Header, Query, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from gateway.app.api import concurrency, idempotency, pagination, permissions, timestamps
from gateway.app.api.auth import require_action, visible_projects
from gateway.app.api.errors import NOT_FOUND, VALIDATION_FAILED, ApiError
from gateway.app.core.users import AuthenticatedPrincipal
from gateway.app.db.session import get_session
from gateway.app.services import store
from gateway.app.services.issue_types import IssuePlanningError


router = APIRouter(prefix="/api/v1")

EPICS_ENDPOINT = "/api/v1/epics"


def _epic_not_found() -> ApiError:
    return ApiError(status_code=404, code=NOT_FOUND, message="No such epic.")


def _project_not_found() -> ApiError:
    # Same message and code as "no such epic": an inaccessible project is
    # indistinguishable from a nonexistent one to the caller, for the same
    # probing-prevention reason sessions.py returns 404 for a hidden session.
    return ApiError(status_code=404, code=NOT_FOUND, message="No such project.")


def _planning_error(exc: IssuePlanningError) -> ApiError:
    return ApiError(
        status_code=400,
        code=VALIDATION_FAILED,
        message=exc.message,
        details=[{"field": exc.field, "code": exc.code, "message": exc.message}],
    )


def _epic_dto(epic) -> dict:
    return {
        "id": epic.id,
        "projectId": epic.project_id,
        "title": epic.title,
        "description": epic.description,
        "status": epic.status,
        "revision": epic.revision,
        "createdAt": timestamps.utc_z(epic.created_at),
        "updatedAt": timestamps.utc_z(epic.updated_at),
        "createdBy": epic.created_by_email or epic.created_by_user_id,
        "updatedBy": (epic.updated_by_email or epic.updated_by_user_id) if epic.updated_by_user_id else None,
    }


class CreateEpicRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    project_id: str = Field(alias="projectId", min_length=1, max_length=128)
    title: str = Field(min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=20000)
    status: str | None = Field(default=None, max_length=32)


@router.get("/projects/{project_id}/epics", tags=["epics"])
async def list_epics(
    project_id: str,
    response: Response,
    status: list[str] | None = Query(default=None),
    cursor: str | None = Query(default=None),
    limit: int | None = Query(default=None),
    principal: AuthenticatedPrincipal = Depends(require_action(permissions.EPICS_READ)),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Epics in one project, newest first.

    `projectId` outside the caller's visible projects answers `404`, never
    `403`: the same probing-prevention rule `get_task_for_projects` applies to
    a single session applies here to a whole project.
    """
    projects = visible_projects(principal)
    if projects is not None and project_id not in projects:
        raise _project_not_found()

    size = pagination.parse_limit(limit)
    endpoint = f"{EPICS_ENDPOINT}:{project_id}"
    scope = pagination.scope_digest(
        endpoint,
        {"projectId": project_id, "status": sorted(status) if status else None, "actor": principal.user_id},
    )
    after = None
    if cursor:
        position = pagination.decode_cursor(scope, cursor, expect={"createdAt": str, "id": str})
        after = (position["createdAt"], position["id"])

    rows = await store.list_epics_page(session, project_id=project_id, status=status, after=after, limit=size)
    page, info = pagination.paginate(
        rows,
        limit=size,
        scope=scope,
        position_of=lambda epic: {"createdAt": timestamps.cursor_z(epic.created_at), "id": epic.id},
    )
    response.headers["Cache-Control"] = "no-store"
    return {"items": [_epic_dto(epic) for epic in page], "page": info}


@router.post("/epics", tags=["epics"], status_code=201)
async def create_epic(
    payload: CreateEpicRequest,
    response: Response,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    principal: AuthenticatedPrincipal = Depends(require_action(permissions.EPICS_CREATE)),
    session: AsyncSession = Depends(get_session),
) -> dict:
    projects = visible_projects(principal)
    if projects is not None and payload.project_id not in projects:
        raise _project_not_found()

    fingerprint = idempotency.fingerprint(
        f"create-epic:{payload.project_id}:{payload.title}".encode()
    )
    claim = None
    if idempotency_key:
        outcome = await idempotency.reserve(
            session,
            key=idempotency_key,
            endpoint=EPICS_ENDPOINT,
            actor_id=principal.user_id,
            request_fingerprint=fingerprint,
        )
        if isinstance(outcome, idempotency.ReplayedResponse):
            response.status_code = outcome.status_code
            response.headers["Idempotent-Replay"] = "true"
            return outcome.body
        claim = outcome

    try:
        epic = await store.create_epic(
            session,
            project_id=payload.project_id,
            title=payload.title,
            description=payload.description,
            status=payload.status,
            actor_user_id=principal.user_id,
            actor_email=principal.email,
        )
    except IssuePlanningError as exc:
        if claim is not None:
            await idempotency.release(
                session, key=idempotency_key, endpoint=EPICS_ENDPOINT, actor_id=principal.user_id, claim=claim
            )
        raise _planning_error(exc) from exc
    except Exception:
        if claim is not None:
            await idempotency.release(
                session, key=idempotency_key, endpoint=EPICS_ENDPOINT, actor_id=principal.user_id, claim=claim
            )
        raise

    body = _epic_dto(epic)
    if claim is not None:
        await idempotency.complete(
            session,
            key=idempotency_key,
            endpoint=EPICS_ENDPOINT,
            actor_id=principal.user_id,
            status_code=201,
            body=body,
            claim=claim,
            request_fingerprint=fingerprint,
        )
    response.headers[concurrency.ETAG_HEADER] = concurrency.etag_for(epic.revision)
    return body


@router.post("/epics/{epic_id}/issues/{issue_id}", tags=["epics"])
async def link_issue(
    epic_id: str,
    issue_id: str,
    response: Response,
    if_match: str | None = Header(default=None, alias="If-Match"),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    principal: AuthenticatedPrincipal = Depends(require_action(permissions.EPICS_LINK_ISSUE)),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Attach an issue to an epic. Both must be in a project the caller may see."""
    from gateway.app.api.routes.issues import ISSUES_ENDPOINT, _issue_dto, _issue_not_found

    projects = visible_projects(principal)
    issue = await store.get_issue_for_projects(session, issue_id, projects)
    if issue is None:
        raise _issue_not_found()
    epic = await store.get_epic_for_projects(session, epic_id, projects)
    if epic is None:
        raise _epic_not_found()

    endpoint = f"{EPICS_ENDPOINT}/{{epicId}}/issues/{{issueId}}"
    fingerprint = idempotency.fingerprint(f"link:{epic_id}:{issue_id}".encode())
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
            fresh = await store.get_issue_for_projects(session, issue_id, projects)
            if fresh is not None:
                response.headers[concurrency.ETAG_HEADER] = concurrency.etag_for(fresh.revision)
            return outcome.body
        claim = outcome

    try:
        concurrency.require_if_match(if_match, issue.revision)
        updated = await store.link_issue_to_epic(
            session,
            issue_id=issue_id,
            epic_id=epic_id,
            actor_user_id=principal.user_id,
            actor_email=principal.email,
        )
    except IssuePlanningError as exc:
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

    body = _issue_dto(updated)
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
    response.headers[concurrency.ETAG_HEADER] = concurrency.etag_for(updated.revision)
    return body
