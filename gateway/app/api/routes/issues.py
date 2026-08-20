"""Issues — issue #8.

Status, priority, labels, assignee, dependencies and blocked reasons, scoped to
a project and optionally grouped under an epic. See `gateway/app/api/routes/epics.py`
for the epic side and the module docstring there for the provider boundary.
"""

from __future__ import annotations

import json

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

ISSUES_ENDPOINT = "/api/v1/issues"

# Sent as an explicit sentinel for a PATCH field the caller did not mention, so
# `UpdateIssueRequest.model_dump(exclude_unset=True)` can tell "omitted" from
# "explicitly set to null" — the same distinction `store.update_issue` needs to
# clear a field versus leave it alone.
_UPDATE_FIELDS = (
    "title", "description", "status", "priority", "labels",
    "assignee_user_id", "assignee_email", "dependencies", "blocked_reason",
)


def _issue_not_found() -> ApiError:
    return ApiError(status_code=404, code=NOT_FOUND, message="No such issue.")


def _project_not_found() -> ApiError:
    return ApiError(status_code=404, code=NOT_FOUND, message="No such project.")


def _planning_error(exc: IssuePlanningError) -> ApiError:
    return ApiError(
        status_code=400,
        code=VALIDATION_FAILED,
        message=exc.message,
        details=[{"field": exc.field, "code": exc.code, "message": exc.message}],
    )


def _issue_dto(issue) -> dict:
    return {
        "id": issue.id,
        "projectId": issue.project_id,
        "epicId": issue.epic_id,
        "title": issue.title,
        "description": issue.description,
        "status": issue.status,
        "priority": issue.priority,
        "labels": json.loads(issue.labels_json or "[]"),
        "assigneeUserId": issue.assignee_user_id,
        "assigneeEmail": issue.assignee_email,
        "dependencies": json.loads(issue.dependencies_json or "[]"),
        "blockedReason": issue.blocked_reason,
        "revision": issue.revision,
        "createdAt": timestamps.utc_z(issue.created_at),
        "updatedAt": timestamps.utc_z(issue.updated_at),
        "createdBy": issue.created_by_email or issue.created_by_user_id,
        "updatedBy": (issue.updated_by_email or issue.updated_by_user_id) if issue.updated_by_user_id else None,
    }


class CreateIssueRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    project_id: str = Field(alias="projectId", min_length=1, max_length=128)
    epic_id: str | None = Field(default=None, alias="epicId", max_length=128)
    title: str = Field(min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=20000)
    status: str | None = Field(default=None, max_length=32)
    priority: str | None = Field(default=None, max_length=32)
    labels: list[str] | None = Field(default=None, max_length=64)
    assignee_user_id: str | None = Field(default=None, alias="assigneeUserId", max_length=255)
    assignee_email: str | None = Field(default=None, alias="assigneeEmail", max_length=255)
    dependencies: list[str] | None = Field(default=None, max_length=64)
    blocked_reason: str | None = Field(default=None, alias="blockedReason", max_length=20000)


class UpdateIssueRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    title: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=20000)
    status: str | None = Field(default=None, max_length=32)
    priority: str | None = Field(default=None, max_length=32)
    labels: list[str] | None = Field(default=None, max_length=64)
    assignee_user_id: str | None = Field(default=None, alias="assigneeUserId", max_length=255)
    assignee_email: str | None = Field(default=None, alias="assigneeEmail", max_length=255)
    dependencies: list[str] | None = Field(default=None, max_length=64)
    blocked_reason: str | None = Field(default=None, alias="blockedReason", max_length=20000)


@router.get("/projects/{project_id}/issues", tags=["issues"])
async def list_issues(
    project_id: str,
    response: Response,
    status: list[str] | None = Query(default=None),
    priority: list[str] | None = Query(default=None),
    epic_id: str | None = Query(default=None, alias="epicId"),
    assignee_user_id: str | None = Query(default=None, alias="assigneeUserId"),
    cursor: str | None = Query(default=None),
    limit: int | None = Query(default=None),
    principal: AuthenticatedPrincipal = Depends(require_action(permissions.ISSUES_READ)),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Issues in one project, newest first, optionally filtered."""
    projects = visible_projects(principal)
    if projects is not None and project_id not in projects:
        raise _project_not_found()

    size = pagination.parse_limit(limit)
    endpoint = f"{ISSUES_ENDPOINT}:{project_id}"
    scope = pagination.scope_digest(
        endpoint,
        {
            "projectId": project_id,
            "status": sorted(status) if status else None,
            "priority": sorted(priority) if priority else None,
            "epicId": epic_id,
            "assigneeUserId": assignee_user_id,
            "actor": principal.user_id,
        },
    )
    after = None
    if cursor:
        position = pagination.decode_cursor(scope, cursor, expect={"createdAt": str, "id": str})
        after = (position["createdAt"], position["id"])

    rows = await store.list_issues_page(
        session,
        project_id=project_id,
        status=status,
        priority=priority,
        epic_id=epic_id,
        assignee_user_id=assignee_user_id,
        after=after,
        limit=size,
    )
    page, info = pagination.paginate(
        rows,
        limit=size,
        scope=scope,
        position_of=lambda issue: {"createdAt": timestamps.cursor_z(issue.created_at), "id": issue.id},
    )
    response.headers["Cache-Control"] = "no-store"
    return {"items": [_issue_dto(issue) for issue in page], "page": info}


@router.get("/issues/{issue_id}", tags=["issues"])
async def get_issue_detail(
    issue_id: str,
    response: Response,
    principal: AuthenticatedPrincipal = Depends(require_action(permissions.ISSUES_READ)),
    session: AsyncSession = Depends(get_session),
) -> dict:
    issue = await store.get_issue_for_projects(session, issue_id, visible_projects(principal))
    if issue is None:
        raise _issue_not_found()
    response.headers[concurrency.ETAG_HEADER] = concurrency.etag_for(issue.revision)
    response.headers["Cache-Control"] = "no-store"
    return _issue_dto(issue)


@router.post("/issues", tags=["issues"], status_code=201)
async def create_issue(
    payload: CreateIssueRequest,
    response: Response,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    principal: AuthenticatedPrincipal = Depends(require_action(permissions.ISSUES_CREATE)),
    session: AsyncSession = Depends(get_session),
) -> dict:
    projects = visible_projects(principal)
    if projects is not None and payload.project_id not in projects:
        raise _project_not_found()

    fingerprint = idempotency.fingerprint(
        f"create-issue:{payload.project_id}:{payload.title}:{payload.epic_id}".encode()
    )
    claim = None
    if idempotency_key:
        outcome = await idempotency.reserve(
            session,
            key=idempotency_key,
            endpoint=ISSUES_ENDPOINT,
            actor_id=principal.user_id,
            request_fingerprint=fingerprint,
        )
        if isinstance(outcome, idempotency.ReplayedResponse):
            response.status_code = outcome.status_code
            response.headers["Idempotent-Replay"] = "true"
            return outcome.body
        claim = outcome

    try:
        issue = await store.create_issue(
            session,
            project_id=payload.project_id,
            epic_id=payload.epic_id,
            title=payload.title,
            description=payload.description,
            status=payload.status,
            priority=payload.priority,
            labels=payload.labels,
            assignee_user_id=payload.assignee_user_id,
            assignee_email=payload.assignee_email,
            dependencies=payload.dependencies,
            blocked_reason=payload.blocked_reason,
            actor_user_id=principal.user_id,
            actor_email=principal.email,
        )
    except IssuePlanningError as exc:
        if claim is not None:
            await idempotency.release(
                session, key=idempotency_key, endpoint=ISSUES_ENDPOINT, actor_id=principal.user_id, claim=claim
            )
        raise _planning_error(exc) from exc
    except Exception:
        if claim is not None:
            await idempotency.release(
                session, key=idempotency_key, endpoint=ISSUES_ENDPOINT, actor_id=principal.user_id, claim=claim
            )
        raise

    body = _issue_dto(issue)
    if claim is not None:
        await idempotency.complete(
            session,
            key=idempotency_key,
            endpoint=ISSUES_ENDPOINT,
            actor_id=principal.user_id,
            status_code=201,
            body=body,
            claim=claim,
            request_fingerprint=fingerprint,
        )
    response.headers[concurrency.ETAG_HEADER] = concurrency.etag_for(issue.revision)
    return body


@router.patch("/issues/{issue_id}", tags=["issues"])
async def update_issue(
    issue_id: str,
    payload: UpdateIssueRequest,
    response: Response,
    if_match: str | None = Header(default=None, alias="If-Match"),
    principal: AuthenticatedPrincipal = Depends(require_action(permissions.ISSUES_UPDATE)),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Change status, priority, labels, assignee, dependencies or blocked reason.

    Fields the caller does not mention are left untouched; a field explicitly
    sent as `null` is cleared. `epicId` is deliberately absent from this body —
    `POST /api/v1/epics/{epicId}/issues/{issueId}` is the one way to move an
    issue between epics, so there is exactly one mechanism to test and audit
    instead of two that can disagree.
    """
    projects = visible_projects(principal)
    issue = await store.get_issue_for_projects(session, issue_id, projects)
    if issue is None:
        raise _issue_not_found()
    concurrency.require_if_match(if_match, issue.revision)

    changes = payload.model_dump(exclude_unset=True)
    kwargs = {field: changes[field] for field in _UPDATE_FIELDS if field in changes}

    try:
        updated = await store.update_issue(
            session,
            issue_id,
            actor_user_id=principal.user_id,
            actor_email=principal.email,
            **kwargs,
        )
    except IssuePlanningError as exc:
        raise _planning_error(exc) from exc

    response.headers[concurrency.ETAG_HEADER] = concurrency.etag_for(updated.revision)
    return _issue_dto(updated)
