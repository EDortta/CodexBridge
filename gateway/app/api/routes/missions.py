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
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Header, Query, Response
from sqlalchemy.ext.asyncio import AsyncSession

from gateway.app.api import concurrency, idempotency, pagination, permissions, timestamps
from gateway.app.api.auth import require_action, visible_projects
from gateway.app.api.errors import CONFLICT, NOT_FOUND, ApiError
from gateway.app.api.routes.sessions import redact
from gateway.app.core.users import AuthenticatedPrincipal
from gateway.app.db.session import get_session
from gateway.app.models.entities import AuditEventModel, TaskModel
from gateway.app.services import store
from gateway.app.services.audit import record_event
from gateway.app.services.agent_hub import AgentHub, hub_envelope
from shared.protocol import AgentMessageType, STOPPABLE_TASK_STATES, TaskState


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


def _mission_dto(task: TaskModel) -> dict:
    """Mobile representation of a mission.

    Omits `ProjectModel.path`, the command line and the stored result blob —
    the same fields Sessions omits, for the same reason (`docs/api/README.md`,
    "Fields that must never ship").
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
        return "Cancelled by an operator."
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
    principal: AuthenticatedPrincipal = Depends(require_action(permissions.MISSIONS_CANCEL)),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Cancel a mission that is queued, waiting, running or awaiting approval.

    `cancel` is the only lifecycle command this API offers, for the same
    protocol reason Sessions' `stop` is the only one there: see the module
    docstring. Requires `If-Match`. With `Idempotency-Key`, a retry replays
    the first response and cancels nothing twice.
    """
    from gateway.app.main import hub  # imported late: main includes this router

    projects = visible_projects(principal)
    task = await store.get_task_for_projects(session, mission_id, projects)
    if task is None:
        raise _not_found()

    fingerprint = idempotency.fingerprint(f"cancel:{mission_id}".encode())
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
