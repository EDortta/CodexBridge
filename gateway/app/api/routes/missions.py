"""Missions: the mission-control view of the same run Sessions exposes — issue #7.

A **mission** is a `TaskModel`, the same row `/api/v1/sessions` (issue #9)
serves. There is no separate mission entity in this codebase's domain model —
no dependency graph, no "related entities" table, no execution-progress
percentage — so this router does not invent one. It reframes the fields that
already exist (`instruction`, `executor_id`, `mode`, `state`, `approval_state`,
the `audit_events` rows `record_event` already writes) in mission-control
vocabulary, and adds only what is derivable from them:

- `stage` is a three-phase grouping over `TaskState`
  (`store.mission_stage`) — coarser than `state`, which is exposed unchanged
  and remains its own filter.
- `risk` is `shared/policy.py:policy_level_for_mode`, overridden to
  `sensitive` when `approval_state` recorded that escalation at creation
  (`store.mission_risk`). It is not a new scoring model.
- `blocked` / `blockedReason` is `state == awaiting_approval`, the same
  condition Sessions already reports as `interventionRequired`, given a
  machine code and a human summary.
- The timeline is `audit_events` filtered to this task, oldest first — the
  same rows `task.stopped_by_actor` and friends already write, not a new log.

`dependencies` and `relatedEntities`, named in the issue's Scope section, are
**not implemented**: no schema in this codebase links one task to another or
to any other entity, and shipping an always-empty array would be a field a
mobile client can build UI around and never see populated. See
`docs/api/README.md` "Missions (issue #7)".

`pause` and `resume` are **not implemented**, for the same reason issue #9
did not implement them for Sessions: `shared/protocol.py:AgentMessageType`
has `task.dispatch`, `task.ack`, `task.log`, `task.result`, `task.cancel`,
`task.cancelled` and `error` — no pause, no resume. `cancel` maps to
`task.cancel`, exactly as Sessions' `stop` does.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Body, Depends, Header, Query, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from gateway.app.api import concurrency, idempotency, pagination, permissions, timestamps
from gateway.app.api.auth import require_action, visible_projects
from gateway.app.api.errors import CONFLICT, NOT_FOUND, PERMISSION_DENIED, VALIDATION_FAILED, ApiError
from gateway.app.api.routes.sessions import redact
from gateway.app.core.users import AuthenticatedPrincipal
from gateway.app.db.session import get_session
from gateway.app.models.entities import AuditEventModel, ExecutorModel, IssueModel, ProjectModel, TaskModel
from gateway.app.services import store
from gateway.app.services.audit import record_event
from gateway.app.services.agent_hub import AgentHub, hub_envelope
from shared.protocol import (
    AgentEngine,
    AgentMessageType,
    DeliveryRequest,
    IMPLEMENTED_ENGINES,
    ISSUE_REF_PATTERN,
    PUSHABLE_BRANCH_PATTERN,
    STOPPABLE_TASK_STATES,
    SubmitTaskRequest,
    TaskMode,
    TaskPriority,
    TaskState,
)


router = APIRouter(prefix="/api/v1")

MISSIONS_ENDPOINT = "/api/v1/missions"

# States from which a cancel is meaningful. `shared.protocol.STOPPABLE_TASK_STATES`
# itself, not a second copy of it: that constant exists specifically because
# `cancel_codex_task` once silently no-op'd on paused/pausing/resuming/restarting
# while `/stop` already covered them (issue #17's review). A mission is the same
# `TaskModel` Sessions cancels, so a local literal here would be exactly the
# duplicate-that-drifts the shared constant was built to prevent.
CANCELLABLE = STOPPABLE_TASK_STATES

BLOCKED_REASON_AWAITING_APPROVAL = "awaiting_approval"


class MissionCancelRequest(BaseModel):
    """Issue #36: an operator-typed reason has nowhere to go without this.

    Optional and defaults to no body at all (`Body(default=None)` on the
    handler), the same shape `routes/auth.py:revoke`'s `RevokeRequest` uses —
    an existing client that cancels with no body must keep working exactly as
    before.
    """

    reason: str | None = Field(default=None, max_length=4000)


class CreateMissionDelivery(BaseModel):
    """Wire shape of `shared.protocol.DeliveryRequest` — issue #68/#66.

    Field-for-field the same envelope `start_development_task` (MCP,
    `gateway/app/mcp/server.py`) already accepts, camelCase for this
    transport. `to_protocol()` is the only place this becomes the real
    `DeliveryRequest` `store.create_task` understands, so the two shapes
    cannot drift silently: a field added to one and not translated here
    fails at that call, not at runtime months later.
    """

    model_config = ConfigDict(populate_by_name=True)

    branch: str = Field(min_length=1, max_length=200)
    allow_push: bool = Field(default=False, alias="allowPush")
    base_branch: str = Field(default="development", alias="baseBranch", max_length=200)
    remote: str = Field(default="origin", max_length=200)
    commit_subject: str | None = Field(default=None, alias="commitSubject", max_length=200)

    def to_protocol(self) -> DeliveryRequest:
        return DeliveryRequest(
            branch=self.branch,
            allow_push=self.allow_push,
            base_branch=self.base_branch,
            remote=self.remote,
            commit_subject=self.commit_subject,
        )


class CreateMissionRequest(BaseModel):
    """`POST /api/v1/missions` — issue #68.

    The first HTTP exposure of `codexbridge.task.submit`
    (`gateway/app/api/permissions.py:MISSIONS_CREATE`). Deliberately close to
    `SubmitTaskRequest`/`start_development_task`'s own shape rather than a
    new vocabulary: `objective`/`mode`/`priority`/`engine`/`issueRef`/
    `delivery` are the same fields those already validate, so this route can
    hand them to `store.create_task` — the exact function every other task
    creator in this codebase already goes through — instead of re-deriving
    what a valid task looks like a second time.

    `executorId` is optional and, when omitted, resolved the same way
    `start_development_task` resolves it: the project's onboarded executors,
    preferring one that is connected right now. It has to be optional —
    `nodes.read`/`executors` listing is an administrative action
    (`permissions.NODES_READ`, `ADMIN_SCOPE`), so a non-admin caller — the
    only caller this endpoint exists for — has no HTTP way to learn a raw
    executor id at all.
    """

    model_config = ConfigDict(populate_by_name=True)

    project_id: str = Field(alias="projectId", min_length=1, max_length=128)
    executor_id: str | None = Field(default=None, alias="executorId", max_length=128)
    objective: str = Field(min_length=1, max_length=12000)
    mode: TaskMode = TaskMode.IMPLEMENT
    priority: TaskPriority = TaskPriority.NORMAL
    engine: AgentEngine = AgentEngine.CODEX
    issue_ref: str | None = Field(default=None, alias="issueRef", max_length=512)
    timeout_seconds: int = Field(default=3600, ge=30, le=86400, alias="timeoutSeconds")
    run_when_available: bool = Field(default=True, alias="runWhenAvailable")
    expires_at: datetime | None = Field(default=None, alias="expiresAt")
    delivery: CreateMissionDelivery | None = None


def _iso(value: datetime | None) -> str | None:
    return timestamps.utc_z(value)


def _cursor_time(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.isoformat()


def _blocked_reason(task: TaskModel) -> dict | None:
    """Machine-readable code plus human summary — the acceptance criterion verbatim.

    `awaiting_approval` is the only reason this build can report: it is the
    only state a mission is held in without the agent protocol having a way to
    move it forward on its own.
    """
    if task.state != TaskState.AWAITING_APPROVAL.value:
        return None
    summary = redact(task.approval_reason) or "Held for approval before it may proceed."
    return {"code": BLOCKED_REASON_AWAITING_APPROVAL, "summary": summary}


def _delivery_dto(raw_json: str | None) -> dict | None:
    """`TaskModel.delivery_json` (snake_case `DeliveryRequest.model_dump_json()`)
    reshaped to the contract's camelCase, or `None` when no delivery was
    requested. Never carries the *result* of a delivery
    (`delivery_result_json`) — that is issue #69's `GET .../delivery`, kept
    deliberately separate (`docs/api/README.md`, "Missions (issue #7)").
    """
    if not raw_json:
        return None
    data = json.loads(raw_json)
    return {
        "branch": data.get("branch"),
        "allowPush": data.get("allow_push", False),
        "baseBranch": data.get("base_branch"),
        "remote": data.get("remote"),
        "commitSubject": data.get("commit_subject"),
    }


def _mission_dto(task: TaskModel) -> dict:
    """Mobile representation of a mission.

    Omits `ProjectModel.path`, the command line and the stored result blob —
    the same fields Sessions omits, for the same reason (`docs/api/README.md`,
    "Fields that must never ship").

    `engine`/`issueRef`/`delivery` (issue #68) are additive: every mission
    endpoint shares this function, so a client reading `GET /api/v1/missions`
    or `.../{id}` sees them too, exactly as `docs/api/README.md` describes for
    the create response — there is no second, narrower DTO for create alone.
    """
    return {
        "id": task.id,
        "projectId": task.project_id,
        "assignedAgent": task.executor_id,
        "objective": redact(task.instruction),
        "mode": task.mode,
        "state": task.state,
        "stage": store.mission_stage(task),
        "risk": store.mission_risk(task),
        "blocked": task.state == TaskState.AWAITING_APPROVAL.value,
        "blockedReason": _blocked_reason(task),
        "priority": task.priority,
        "revision": task.revision,
        "createdAt": _iso(task.created_at),
        "startedAt": _iso(task.started_at),
        "completedAt": _iso(task.completed_at),
        "expiresAt": _iso(task.expires_at),
        "approvalState": task.approval_state,
        "requestedBy": task.requested_by_email or task.requested_by_user_id,
        "lastError": redact(task.last_error),
        "engine": task.engine,
        "issueRef": task.issue_ref,
        "delivery": _delivery_dto(task.delivery_json),
    }


def _not_found() -> ApiError:
    return ApiError(status_code=404, code=NOT_FOUND, message="No such mission.")


def _effective_project_ids(
    principal: AuthenticatedPrincipal, requested: list[str] | None
) -> list[str] | None:
    """`visible_projects`, narrowed by an explicit `projectId` filter.

    A requested project outside the caller's visibility is dropped rather than
    surfaced as an error: `visible_projects` already treats "invisible" as
    "absent", and a filter naming a project the caller cannot see must not
    become a way to probe which ids exist.
    """
    visible = visible_projects(principal)
    if requested is None:
        return visible
    if visible is None:
        return requested
    allowed = set(visible)
    return [project_id for project_id in requested if project_id in allowed]


def _resolve_states(state: list[str] | None, stage: list[str] | None) -> list[str] | None:
    """`state` and `stage` combined into the one filter the store understands.

    Returns None for "no filter", a non-empty list for "match these states",
    or an empty list when both were given and their intersection is empty —
    the caller must treat that last case as "no rows", not as "no filter",
    since `list_missions_page` treats an empty list as falsy and skips it.
    """
    if not state and not stage:
        return None
    from_state = set(state) if state else None
    from_stage: set[str] | None = None
    if stage:
        from_stage = set()
        for value in stage:
            from_stage |= set(store.MISSION_STAGE_STATES.get(value, ()))
    if from_state is not None and from_stage is not None:
        return sorted(from_state & from_stage)
    return sorted(from_state if from_state is not None else from_stage)


@router.get("/missions", tags=["missions"])
async def list_missions(
    response: Response,
    project_id: list[str] | None = Query(default=None, alias="projectId"),
    stage: list[str] | None = Query(default=None),
    state: list[str] | None = Query(default=None),
    risk: list[str] | None = Query(default=None),
    blocked: bool | None = Query(default=None),
    cursor: str | None = Query(default=None),
    limit: int | None = Query(default=None),
    principal: AuthenticatedPrincipal = Depends(require_action(permissions.MISSIONS_READ)),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Missions the caller may see, newest first."""
    projects = visible_projects(principal)
    effective_projects = _effective_project_ids(principal, project_id)
    effective_states = _resolve_states(state, stage)
    size = pagination.parse_limit(limit)

    scope = pagination.scope_digest(
        MISSIONS_ENDPOINT,
        {
            "projectId": sorted(project_id) if project_id else None,
            "stage": sorted(stage) if stage else None,
            "state": sorted(state) if state else None,
            "risk": sorted(risk) if risk else None,
            "blocked": blocked,
            "actor": principal.user_id,
            "projects": sorted(projects) if projects is not None else "*",
        },
    )

    response.headers["Cache-Control"] = "no-store"

    if effective_states == []:
        # `state` and `stage` were both given and share no state: no query can
        # match, and passing [] to the store would be indistinguishable from
        # "no filter" there.
        return {"items": [], "page": pagination.page_info(has_more=False, next_cursor=None)}

    after = None
    if cursor:
        position = pagination.decode_cursor(scope, cursor, expect={"createdAt": str, "id": str})
        after = (position["createdAt"], position["id"])

    rows = await store.list_missions_page(
        session,
        project_ids=effective_projects,
        states=effective_states,
        risk=risk,
        blocked=blocked,
        after=after,
        limit=size,
    )
    page, info = pagination.paginate(
        rows,
        limit=size,
        scope=scope,
        position_of=lambda task: {"createdAt": _cursor_time(task.created_at), "id": task.id},
    )
    return {"items": [_mission_dto(task) for task in page], "page": info}


@router.get("/missions/{mission_id}", tags=["missions"])
async def get_mission(
    mission_id: str,
    response: Response,
    principal: AuthenticatedPrincipal = Depends(require_action(permissions.MISSIONS_READ)),
    session: AsyncSession = Depends(get_session),
) -> dict:
    task = await store.get_task_for_projects(session, mission_id, visible_projects(principal))
    if task is None:
        raise _not_found()
    response.headers[concurrency.ETAG_HEADER] = concurrency.etag_for(task.revision)
    response.headers["Cache-Control"] = "no-store"
    return _mission_dto(task)


def _validation_error(field: str, code: str, message: str) -> ApiError:
    return ApiError(
        status_code=400,
        code=VALIDATION_FAILED,
        message=message,
        details=[{"field": f"/{field}", "code": code, "message": message}],
    )


# `store.create_task`'s own vocabulary (a bare `ValueError` with one of these
# messages — see its docstring-free `raise ValueError(...)` call sites) mapped
# to this contract's codes. Not exhaustive of every ValueError Python could
# raise, only of the ones that function is documented to: an unmapped message
# still becomes a 500 `internal_error`, the fail-closed default, rather than
# silently turning into a 400 for a failure this table does not actually know.
_TASK_CREATION_ERRORS: dict[str, tuple[int, str]] = {
    "unknown_or_disabled_executor": (404, NOT_FOUND),
    "unknown_or_disabled_project": (404, NOT_FOUND),
    "project_not_allowed_for_executor": (409, CONFLICT),
    "mode_not_allowed_for_project": (400, VALIDATION_FAILED),
    "timeout_exceeds_project_limit": (400, VALIDATION_FAILED),
    "executor_offline": (409, CONFLICT),
    "task_already_expired": (400, VALIDATION_FAILED),
}


def _task_creation_error(exc: ValueError) -> ApiError:
    reason = str(exc)
    status_code, code = _TASK_CREATION_ERRORS.get(reason, (500, "internal_error"))
    return ApiError(status_code=status_code, code=code, message=reason)


async def _resolve_executor(
    session: AsyncSession, hub: AgentHub, project_id: str, requested_executor_id: str | None
) -> ExecutorModel:
    """The executor a mission dispatches to.

    Explicit `executorId` is validated against the project's own allowlist —
    `store.create_task` re-checks this itself, but failing here gives a
    precise `404`/`409` instead of letting an unmapped internal message
    through. Omitted, it is resolved exactly the way `start_development_task`
    (MCP) resolves it: the project's onboarded executors, preferring one that
    is connected right now — see `CreateMissionRequest.executor_id`'s
    docstring for why this cannot simply be a required field on this surface.
    """
    if requested_executor_id:
        executor = await session.get(ExecutorModel, requested_executor_id)
        if executor is None or not executor.enabled:
            raise ApiError(status_code=404, code=NOT_FOUND, message="No such executor.")
        allowed = json.loads(executor.metadata_json).get("allowed_projects", [])
        if project_id not in allowed:
            raise ApiError(
                status_code=409,
                code=CONFLICT,
                message=(
                    f"Executor {requested_executor_id!r} does not allow project {project_id!r}."
                ),
            )
        return executor

    onboarded = await store.executors_allowing_project(session, project_id)
    if not onboarded:
        raise ApiError(
            status_code=409,
            code=CONFLICT,
            message=f"No executor allows project {project_id!r}.",
        )
    connected = [item for item in onboarded if hub.is_connected(item.id)]
    return connected[0] if connected else onboarded[0]


async def _validate_issue_ref(session: AsyncSession, project_id: str, issue_ref: str | None) -> None:
    """Same shape check `start_development_task` applies, so an `issueRef`
    this endpoint accepts is never one the MCP transport would have refused.

    `gh:` is syntactically valid but always rejected: GitHub issue ingestion
    has no owner in this codebase yet (council finding F18). `docs:NNN`/bare
    `NNN` resolve on the executor, which never learns a project's real path
    (`docs/architecture.md`), so there is nothing to check here beyond shape.
    Only `local:` — an `IssueModel` row this gateway owns — can be, and is,
    verified to exist and belong to `project_id`.
    """
    if issue_ref is None:
        return
    if not ISSUE_REF_PATTERN.match(issue_ref):
        raise _validation_error("issueRef", "invalid", "issueRef is not a recognized shape.")
    if issue_ref.startswith("gh:"):
        raise _validation_error(
            "issueRef", "issue_source_unsupported", "GitHub issue ingestion is not supported yet."
        )
    if issue_ref.startswith("local:"):
        local_id = issue_ref.split(":", 1)[1]
        issue_row = await session.get(IssueModel, local_id)
        if issue_row is None or issue_row.project_id != project_id:
            raise ApiError(status_code=404, code=NOT_FOUND, message="No such issue.")


def _require_push_authority(principal: AuthenticatedPrincipal, delivery: CreateMissionDelivery) -> None:
    """The same pre-authorization-as-approval path `start_development_task`
    (MCP) enforces before `allow_push` reaches `store.create_task` — issue
    #68's own requirement: "no separate, weaker authorization path for the
    HTTP surface." A caller who fails either check never reaches
    `store.create_task` with `allow_push=True` at all, so `can_approve_push`
    below (always the caller's own authority, not a body field) is the only
    thing that can turn a pre-authorized push into an actual approval.
    """
    if not principal.has_scope(permissions.APPROVE_SCOPE):
        raise ApiError(
            status_code=403,
            code=PERMISSION_DENIED,
            message="delivery.allowPush requires the codexbridge.task.approve scope.",
        )
    if not (principal.can_approve_sensitive or principal.is_admin()):
        raise ApiError(
            status_code=403,
            code=PERMISSION_DENIED,
            message="delivery.allowPush requires sensitive-approval authority.",
        )
    if not PUSHABLE_BRANCH_PATTERN.match(delivery.branch):
        raise _validation_error(
            "delivery/branch", "branch_not_pushable", "delivery.branch is not a pushable branch."
        )


@router.post("/missions", tags=["missions"], status_code=201)
async def create_mission(
    payload: CreateMissionRequest,
    response: Response,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    principal: AuthenticatedPrincipal = Depends(require_action(permissions.MISSIONS_CREATE)),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Create a mission — the first HTTP exposure of `codexbridge.task.submit`.

    Today this is the same `TaskModel` row `submit_codex_task`/
    `start_development_task` (MCP) create; it does not introduce a new id
    space, a new `TaskState`, or a new meaning for any `_mission_dto` field —
    council finding F01 (mission/session/decision are one row) is
    deliberately not re-opened here (issue #68's own ARO).
    """
    from gateway.app.main import hub  # imported late: main includes this router

    projects = visible_projects(principal)
    if projects is not None and payload.project_id not in projects:
        # Same probing-prevention rule every other create endpoint in this
        # contract applies (`docs/api/README.md`): a project the caller
        # cannot see answers 404, never 403.
        raise ApiError(status_code=404, code=NOT_FOUND, message="No such project.")
    project = await session.get(ProjectModel, payload.project_id)
    if project is None or not project.enabled:
        raise ApiError(status_code=404, code=NOT_FOUND, message="No such project.")

    if payload.engine.value not in IMPLEMENTED_ENGINES:
        raise _validation_error(
            "engine", "engine_not_implemented", f"engine {payload.engine.value!r} is not implemented."
        )

    await _validate_issue_ref(session, payload.project_id, payload.issue_ref)

    delivery: DeliveryRequest | None = None
    if payload.delivery is not None:
        if payload.delivery.allow_push:
            _require_push_authority(principal, payload.delivery)
        delivery = payload.delivery.to_protocol()

    executor = await _resolve_executor(session, hub, payload.project_id, payload.executor_id)

    expires_at = payload.expires_at
    if expires_at is None:
        # Same generous formula `start_development_task` computes when a
        # caller does not hand-build an RFC-3339 timestamp: bounds queueing,
        # not execution — `timeout_seconds` already bounds that.
        expires_at = datetime.now(timezone.utc) + timedelta(seconds=max(7200, 2 * payload.timeout_seconds))

    request = SubmitTaskRequest(
        executor_id=executor.id,
        project_id=payload.project_id,
        instruction=payload.objective,
        mode=payload.mode,
        timeout_seconds=payload.timeout_seconds,
        priority=payload.priority,
        run_when_available=payload.run_when_available,
        expires_at=expires_at,
        engine=payload.engine,
        issue_ref=payload.issue_ref,
        delivery=delivery,
    )

    fingerprint = idempotency.fingerprint(
        payload.model_dump_json(by_alias=True).encode()
    )
    claim = None
    if idempotency_key:
        outcome = await idempotency.reserve(
            session,
            key=idempotency_key,
            endpoint=MISSIONS_ENDPOINT,
            actor_id=principal.user_id,
            request_fingerprint=fingerprint,
        )
        if isinstance(outcome, idempotency.ReplayedResponse):
            response.status_code = outcome.status_code
            response.headers["Idempotent-Replay"] = "true"
            return outcome.body
        claim = outcome

    try:
        task = await store.create_task(
            session,
            request,
            hub.is_connected(executor.id),
            requested_by_user_id=principal.user_id,
            requested_by_email=principal.email,
            can_approve_push=bool(principal.can_approve_sensitive or principal.is_admin()),
        )
    except ValueError as exc:
        if claim is not None:
            await idempotency.release(
                session, key=idempotency_key, endpoint=MISSIONS_ENDPOINT, actor_id=principal.user_id, claim=claim
            )
        raise _task_creation_error(exc) from exc
    except Exception:
        if claim is not None:
            await idempotency.release(
                session, key=idempotency_key, endpoint=MISSIONS_ENDPOINT, actor_id=principal.user_id, claim=claim
            )
        raise

    # `dispatch_available` is the shared entry point `continue_codex_session`
    # (MCP) already uses for this same follow-up — nudges the queue in this
    # turn rather than leaving a connected, idle executor waiting for an
    # unrelated event, without this route hand-rolling the
    # is_connected/dispatch_next/send sequence issues #18/#20 found
    # duplicated elsewhere.
    await hub.dispatch_available(task.executor_id)
    await session.refresh(task)

    body = _mission_dto(task)
    if claim is not None:
        await idempotency.complete(
            session,
            key=idempotency_key,
            endpoint=MISSIONS_ENDPOINT,
            actor_id=principal.user_id,
            status_code=201,
            body=body,
            claim=claim,
            request_fingerprint=fingerprint,
        )
    response.headers[concurrency.ETAG_HEADER] = concurrency.etag_for(task.revision)
    return body


def _safe_payload(raw: str) -> dict:
    try:
        data = json.loads(raw)
    except (TypeError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _timeline_summary(event_type: str, payload: dict) -> str:
    """A short, redacted, human-readable line for one timeline entry.

    Built from an explicit per-event allowlist rather than dumping
    `payload_json` verbatim: the payload carries fields (`policy_level`,
    `via`, `requested_by_user_id`) never audited for what they may contain,
    and this endpoint is public API surface.
    """
    if event_type == "task.created":
        return "Mission created."
    if event_type == "task.state_changed":
        state = payload.get("state") or "unknown"
        error = redact(payload.get("error")) if payload.get("error") else None
        return f"State changed to {state}." + (f" {error}" if error else "")
    if event_type == "task.approval_decision":
        decision = payload.get("decision") or "unknown"
        reason = redact(payload.get("reason")) if payload.get("reason") else None
        return f"Approval decision: {decision}." + (f" {reason}" if reason else "")
    if event_type == "task.result":
        return "Execution finished."
    if event_type == "task.stopped_by_actor":
        reason = redact(payload.get("reason")) if payload.get("reason") else None
        return "Cancelled by an operator." + (f" {reason}" if reason else "")
    if event_type == "task.recovered":
        state = payload.get("state") or "unknown"
        return f"Recovered after a gateway restart; marked {state}."
    return "Mission event recorded."


def _timeline_dto(event: AuditEventModel) -> dict:
    payload = _safe_payload(event.payload_json)
    return {
        "type": event.event_type,
        "at": _iso(event.created_at),
        "state": payload.get("state"),
        "actor": payload.get("actor_id"),
        "summary": _timeline_summary(event.event_type, payload),
    }


@router.get("/missions/{mission_id}/timeline", tags=["missions"])
async def get_mission_timeline(
    mission_id: str,
    response: Response,
    cursor: str | None = Query(default=None),
    limit: int | None = Query(default=None),
    principal: AuthenticatedPrincipal = Depends(require_action(permissions.MISSIONS_READ_TIMELINE)),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """The mission's recorded events, oldest first — the order a narrative reads in."""
    task = await store.get_task_for_projects(session, mission_id, visible_projects(principal))
    if task is None:
        raise _not_found()

    size = pagination.parse_limit(limit)
    endpoint = f"{MISSIONS_ENDPOINT}/{{missionId}}/timeline"
    scope = pagination.scope_digest(endpoint, {"missionId": mission_id})

    after = None
    if cursor:
        position = pagination.decode_cursor(scope, cursor, expect={"createdAt": str, "id": int})
        after = (position["createdAt"], position["id"])

    rows = await store.list_task_events_page(session, mission_id, after=after, limit=size)
    page, info = pagination.paginate(
        rows,
        limit=size,
        scope=scope,
        position_of=lambda event: {"createdAt": _cursor_time(event.created_at), "id": event.id},
    )
    response.headers["Cache-Control"] = "no-store"
    return {"items": [_timeline_dto(event) for event in page], "page": info}


async def _dispatch_cancel(hub: AgentHub, task: TaskModel) -> bool:
    """Tell the executor, if it is listening. Returns whether it was told.

    Same shape and the same caveat as Sessions' `_dispatch_cancel`: a
    disconnected executor does not fail the request, but nothing replays
    `task.cancel` on reconnect (issue #17), so the run may still be going.
    """
    if not hub.is_connected(task.executor_id):
        return False
    await hub.send(
        task.executor_id,
        hub_envelope(task.executor_id, AgentMessageType.TASK_CANCEL.value, {"task_id": task.id}),
    )
    return True


@router.post("/missions/{mission_id}/cancel", tags=["missions"])
async def cancel_mission(
    mission_id: str,
    response: Response,
    if_match: str | None = Header(default=None, alias="If-Match"),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    body: MissionCancelRequest | None = Body(default=None),
    principal: AuthenticatedPrincipal = Depends(require_action(permissions.MISSIONS_CANCEL)),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Cancel a mission that is queued, waiting, running or awaiting approval.

    `cancel` is the only lifecycle command this API offers, for the same
    protocol reason Sessions' `stop` is the only one there: see the module
    docstring. Requires `If-Match`. With `Idempotency-Key`, a retry replays
    the first response and cancels nothing twice.

    `reason` (issue #36) is optional and free text, recorded on the mission's
    timeline the same way `task.decision_resolved_by_actor` already records
    why a decision was resolved — there is no dedicated column for it, only
    the audit event, which is enough for an operator to see why on the
    timeline without inventing a new piece of mission state.
    """
    from gateway.app.main import hub  # imported late: main includes this router

    reason = body.reason if body else None

    projects = visible_projects(principal)
    task = await store.get_task_for_projects(session, mission_id, projects)
    if task is None:
        raise _not_found()

    # `reason` folds into the fingerprint, same as `routes/decisions.py`'s
    # `_resolve`: a retry with the *same* key and the *same* reason is the
    # replay this mechanism exists for, but a caller that reuses a key with a
    # different reason gets the `409` `idempotency.reserve` already gives a
    # body mismatch, rather than the first reason silently winning.
    fingerprint = idempotency.fingerprint(f"cancel:{mission_id}:{reason or ''}".encode())
    claim = None
    if idempotency_key:
        outcome = await idempotency.reserve(
            session,
            key=idempotency_key,
            endpoint=f"{MISSIONS_ENDPOINT}/cancel",
            actor_id=principal.user_id,
            request_fingerprint=fingerprint,
        )
        if isinstance(outcome, idempotency.ReplayedResponse):
            response.status_code = outcome.status_code
            response.headers["Idempotent-Replay"] = "true"
            fresh = await store.get_task_for_projects(session, mission_id, projects)
            if fresh is not None:
                response.headers[concurrency.ETAG_HEADER] = concurrency.etag_for(fresh.revision)
            return outcome.body
        claim = outcome

    try:
        concurrency.require_if_match(if_match, task.revision)

        if task.state not in CANCELLABLE:
            raise ApiError(
                status_code=409,
                code=CONFLICT,
                message=f"A mission in state {task.state!r} cannot be cancelled.",
                headers={concurrency.ETAG_HEADER: concurrency.etag_for(task.revision)},
            )

        notified = await _dispatch_cancel(hub, task)
        updated = await store.update_task_state(session, task.id, TaskState.CANCELLED)
        await hub.mark_task_finished(task.executor_id, task.id)
        # Destructive-command audit: who cancelled it, and how. Same event
        # type Sessions' stop writes — one action, two doors — distinguished
        # by `via` so the timeline still says which one was used.
        await record_event(
            session,
            "task",
            task.id,
            "task.stopped_by_actor",
            {
                "actor_id": principal.user_id,
                "actor_email": principal.email,
                "via": "missions_api",
                "executor_notified": notified,
                "reason": reason,
            },
        )
        await session.commit()
    except Exception:
        if claim is not None:
            await idempotency.release(
                session,
                key=idempotency_key,
                endpoint=f"{MISSIONS_ENDPOINT}/cancel",
                actor_id=principal.user_id,
                claim=claim,
            )
        raise

    body = _mission_dto(updated)
    body["executorNotified"] = notified
    if claim is not None:
        await idempotency.complete(
            session,
            key=idempotency_key,
            endpoint=f"{MISSIONS_ENDPOINT}/cancel",
            actor_id=principal.user_id,
            status_code=200,
            body=body,
            claim=claim,
            request_fingerprint=fingerprint,
        )
    response.headers[concurrency.ETAG_HEADER] = concurrency.etag_for(updated.revision)
    return body


@router.post("/missions/{mission_id}/explain", tags=["missions"])
async def explain_mission(
    mission_id: str,
    principal: AuthenticatedPrincipal = Depends(require_action(permissions.MISSIONS_EXPLAIN)),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """A structured account of a mission's current state, assembled server-side.

    Same evidence Sessions' `explain-error` gathers — recorded state, stored
    error, recent `stderr` — plus the mission-control fields (`stage`, `risk`,
    `blocked`) so a client does not need a second call to explain a block.
    No model, no executor round trip.
    """
    task = await store.get_task_for_projects(session, mission_id, visible_projects(principal))
    if task is None:
        raise _not_found()

    stderr = await store.get_recent_logs(session, mission_id, stream="stderr", limit=20)

    reasons = []
    if task.state == TaskState.EXPIRED.value:
        reasons.append("The mission passed its expiry time before completing.")
    if task.state == TaskState.LOST.value:
        reasons.append(
            "The gateway restarted while this mission was running and the executor "
            "never reported a result."
        )
    if task.state == TaskState.CANCELLED.value:
        reasons.append("The mission was cancelled.")
    if task.approval_state and task.state == TaskState.AWAITING_APPROVAL.value:
        reasons.append("The mission is held for approval and has not started.")
    if task.last_error:
        reasons.append("The executor reported an error.")

    return {
        "missionId": task.id,
        "state": task.state,
        "stage": store.mission_stage(task),
        "risk": store.mission_risk(task),
        "blocked": task.state == TaskState.AWAITING_APPROVAL.value,
        "blockedReason": _blocked_reason(task),
        "reasons": reasons or ["No failure recorded for this mission."],
        "lastError": redact(task.last_error),
        "recentStderr": [
            {"offset": row.offset, "line": redact(row.line), "at": _iso(row.created_at)}
            for row in stderr
        ],
        "generatedAt": _iso(datetime.now(timezone.utc)),
    }
