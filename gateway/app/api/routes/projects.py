"""Projects and the project operational dashboard — issue #5.

A **project** is a `ProjectModel` row: an entry in the gateway's registry
(`docs/project-onboarding.md`), never a filesystem path. `ProjectModel.path` is
the canonical trap named in `docs/api/README.md` ("Fields that must never
ship") and never appears in any response this module produces.

## What this issue does NOT deliver, and why

The acceptance criteria ask for counts of "pending decisions, missions, issues,
sessions and recent artifacts". Only three of those five have a backing entity
today:

- **sessions** and, under the vocabulary issue #6/#7 will eventually give their
  own endpoints, **decisions** and **missions** are all the same `TaskModel`
  row issue #9's `/api/v1/sessions` already serves. `pendingDecisions` and
  `activeMissions` below read that one table — they are not new entities.
- **issues** (issue #8) and **artifacts** (issue #11) have no backing model in
  this codebase at all — no `IssueModel`, no `ArtifactModel`. Reporting a count
  for either would mean inventing data or always answering zero, and an
  always-zero field is one a mobile client can build a UI around and never see
  populated — the same failure `probes.CAPABILITIES`'s doc comment already
  warns against. Both are omitted here; a future issue that adds the entity
  adds the field alongside it.

"Branch and latest-activity metadata when available" is served as
`lastActivityAt` (the most recent task's `createdAt` for the project) —
`ProjectModel` carries no branch column, and none of `docs/project-onboarding.md`
or `ProjectRegistration` records one either, so there is nothing to report.

## Health is derived, not stored

`ProjectModel` has no health column. `health` is computed at read time from
whether any executor allowed to run this project is live right now
(`store.executor_is_live`) — `ok` (enabled, at least one live executor),
`degraded` (enabled, executors assigned but none live), `unknown` (enabled, no
executor names this project at all) or `disabled` (the project itself is
turned off). See `store.executor_is_live`'s docstring for why staleness, not
the raw `connected` column, is what this reads: an abruptly killed executor
process runs no disconnect handler, and nothing else ever times the column out.

## Authorization

Same rule as sessions (issue #9): project scope is enforced on the query, not
the response, and a project the caller cannot see returns 404, never 403 —
confirming an identifier exists is what probing is for.

## The `attention` filter is computed in Python, not pushed to SQL

`health` and `pendingDecisions` are derived, not stored columns, so they
cannot be filtered in the database the way `search` and `status` can.
`store.list_projects_filtered` loads every matching project unpaginated when
`attention` is requested and this module paginates the filtered result in
memory. The registry this reads is operator-curated and expected to hold at
most a few hundred rows; see that function's docstring for why this is an
honest trade rather than a scalability promise.
"""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy.ext.asyncio import AsyncSession

from gateway.app.api import pagination, permissions, timestamps
from gateway.app.api.auth import require_action, visible_projects
from gateway.app.api.errors import NOT_FOUND, VALIDATION_FAILED, ApiError
from gateway.app.core.users import AuthenticatedPrincipal
from gateway.app.db.session import get_session
from gateway.app.models.entities import ExecutorModel, ProjectModel
from gateway.app.services import store


router = APIRouter(prefix="/api/v1")

PROJECTS_ENDPOINT = "/api/v1/projects"

# Values accepted by `?status=`. A project is either enabled or it is not —
# there is no third registry state to name.
_STATUS_VALUES = {"enabled": True, "disabled": False}


def _iso(value: datetime | None) -> str | None:
    return timestamps.utc_z(value)


def _not_found() -> ApiError:
    return ApiError(status_code=404, code=NOT_FOUND, message="No such project.")


def _invalid_status() -> ApiError:
    return ApiError(
        status_code=400,
        code=VALIDATION_FAILED,
        message="status must be 'enabled' or 'disabled'.",
        details=[{"field": "?status", "code": "invalid_enum", "message": "status must be 'enabled' or 'disabled'."}],
    )


def _project_health(project: ProjectModel, executors: list[ExecutorModel]) -> str:
    """`ok` / `degraded` / `unknown` / `disabled`. See the module docstring."""
    if not project.enabled:
        return "disabled"
    if not executors:
        return "unknown"
    if any(store.executor_is_live(executor) for executor in executors):
        return "ok"
    return "degraded"


def _status_dto(
    project: ProjectModel,
    *,
    counts: dict[str, int],
    executors: list[ExecutorModel],
    latest_activity_at: datetime | None,
) -> dict:
    """The condensed shape shared by the list and the single-project read.

    Deliberately excludes the executor breakdown and `generatedAt` that
    `/summary` carries — those exist so opening one project's dashboard is one
    call, not a shape every row of a list needs to repeat.
    """
    return {
        "id": project.id,
        "name": project.name,
        "enabled": project.enabled,
        "health": _project_health(project, executors),
        "pendingDecisions": counts.get("pendingDecisions", 0),
        "activeMissions": counts.get("activeMissions", 0),
        "totalSessions": counts.get("total", 0),
        "lastActivityAt": _iso(latest_activity_at),
    }


async def _batch_status_fields(
    session: AsyncSession, projects: list[ProjectModel]
) -> dict:
    """Counts, executors and last-activity for a batch of projects, in three queries.

    Independent of how many projects are in the batch: `project_task_counts`
    and `executors_by_project` are each one grouped query, and only
    `lastActivityAt` is one query per project — there is no grouped "latest
    per group" helper in `store` today and a batch this small (one page, or
    one filtered listing of an operator-curated registry) does not justify
    adding one.
    """
    ids = [project.id for project in projects]
    counts = await store.project_task_counts(session, ids)
    executors = await store.executors_by_project(session, ids)
    latest = {
        project.id: await store.latest_project_activity_at(session, project.id) for project in projects
    }
    return {
        project.id: _status_dto(
            project,
            counts=counts.get(project.id, {}),
            executors=executors.get(project.id, []),
            latest_activity_at=latest.get(project.id),
        )
        for project in projects
    }


def _needs_attention(dto: dict) -> bool:
    """Whether a project's condensed DTO should be surfaced by `?attention=true`.

    A project needs attention when it is not healthy (`degraded`/`unknown`,
    while still enabled — a `disabled` project was turned off on purpose and is
    not a surprise) or when it is holding a decision the operator has not
    resolved.
    """
    if dto["enabled"] and dto["health"] != "ok":
        return True
    return dto["pendingDecisions"] > 0


@router.get("/projects", tags=["projects"])
async def list_projects_endpoint(
    response: Response,
    q: str | None = Query(default=None, max_length=255),
    status: str | None = Query(default=None),
    attention: bool | None = Query(default=None),
    cursor: str | None = Query(default=None),
    limit: int | None = Query(default=None),
    principal: AuthenticatedPrincipal = Depends(require_action(permissions.PROJECTS_READ)),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Projects the caller may see, ordered by id, optimized for the mobile dashboard."""
    projects_scope = visible_projects(principal)
    size = pagination.parse_limit(limit)

    enabled_filter: bool | None = None
    if status is not None:
        if status not in _STATUS_VALUES:
            raise _invalid_status()
        enabled_filter = _STATUS_VALUES[status]

    # The caller and its visible-projects scope are part of the cursor's
    # identity, same reasoning as `list_sessions`: without them a cursor issued
    # to one principal pages a second one straight past rows the second one is
    # entitled to see, while `hasMore` still asserts the page is authoritative.
    scope = pagination.scope_digest(
        PROJECTS_ENDPOINT,
        {
            "q": q,
            "status": status,
            "attention": attention,
            "actor": principal.user_id,
            "projects": sorted(projects_scope) if projects_scope is not None else "*",
        },
    )

    if attention is not None:
        candidates = await store.list_projects_filtered(
            session, project_ids=projects_scope, search=q, enabled=enabled_filter
        )
        after_id = None
        if cursor:
            after_id = pagination.decode_cursor(scope, cursor, expect={"id": str})["id"]
            candidates = [project for project in candidates if project.id > after_id]
        fields = await _batch_status_fields(session, candidates)
        filtered = [project for project in candidates if _needs_attention(fields[project.id]) is attention]
        window = filtered[: size + 1]
        page, info = pagination.paginate(
            window, limit=size, scope=scope, position_of=lambda project: {"id": project.id}
        )
        items = [fields[project.id] for project in page]
    else:
        after_id = None
        if cursor:
            after_id = pagination.decode_cursor(scope, cursor, expect={"id": str})["id"]
        rows = await store.list_projects_page(
            session,
            project_ids=projects_scope,
            search=q,
            enabled=enabled_filter,
            after=after_id,
            limit=size,
        )
        page, info = pagination.paginate(
            rows, limit=size, scope=scope, position_of=lambda project: {"id": project.id}
        )
        fields = await _batch_status_fields(session, page)
        items = [fields[project.id] for project in page]

    return {"items": items, "page": info}


@router.get("/projects/{project_id}", tags=["projects"])
async def get_project_detail(
    project_id: str,
    principal: AuthenticatedPrincipal = Depends(require_action(permissions.PROJECTS_READ)),
    session: AsyncSession = Depends(get_session),
) -> dict:
    project = await store.get_project_for_caller(session, project_id, visible_projects(principal))
    if project is None:
        raise _not_found()
    fields = await _batch_status_fields(session, [project])
    return fields[project.id]


@router.get("/projects/{project_id}/summary", tags=["projects"])
async def get_project_summary(
    project_id: str,
    principal: AuthenticatedPrincipal = Depends(require_action(permissions.PROJECTS_READ)),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """The full dashboard payload for one project: status plus the executor breakdown.

    `executors` never reports a hostname, IP or port — `ExecutorId` and the same
    liveness/staleness fields `health` above is derived from, which is the
    boundary `docs/api/README.md` draws for this contract.
    """
    project = await store.get_project_for_caller(session, project_id, visible_projects(principal))
    if project is None:
        raise _not_found()

    counts = await store.project_task_counts(session, [project.id])
    executors = await store.executors_allowing_project(session, project.id)
    latest_activity_at = await store.latest_project_activity_at(session, project.id)

    body = _status_dto(
        project,
        counts=counts.get(project.id, {}),
        executors=executors,
        latest_activity_at=latest_activity_at,
    )
    body["executors"] = [
        {
            "executorId": executor.id,
            "connected": store.executor_is_live(executor),
            "lastSeenAt": _iso(executor.last_seen_at),
        }
        for executor in executors
    ]
    body["generatedAt"] = _iso(datetime.now(timezone.utc))
    return body
