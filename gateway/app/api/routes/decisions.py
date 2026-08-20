"""Operational decisions: sensitive tasks held for a human to resolve — issue #6.

A "decision" is not a new domain object. It is a `TaskModel` that needed
approval: `shared.policy.evaluate_task_policy` withheld it, `store.create_task`
recorded the risk level in `TaskModel.policy_level`, and `store.decide_task_approval`
already knows how to resolve one — the MCP transport's `approve_codex_task` tool
has called it since before this API existed. This module is the first REST
exposure of that existing mechanism, not a new one.

## Why every decision here is "critical"

`shared/policy.py:evaluate_task_policy` withholds approval — the only way a task
becomes `AWAITING_APPROVAL` — exactly when its level is `sensitive`. So
`policy_level` is `sensitive` for every row this router will ever serve today.
The `risk` filter and the confirmation requirement on `approve` are still
written generally, against `PolicyLevel`, rather than hardcoded to today's one
value: a future change to `evaluate_task_policy` that starts holding
`controlled_write` tasks for approval too must not have to touch this file to
be filtered or protected correctly.

## request-revision is not a fourth state the task can leave

`ApprovalDecision.REVISION_REQUESTED` exists so a decision's outcome can be
told apart from a plain rejection, but the agent protocol has no message that
reopens a task for editing — the same gap `routes/sessions.py` documents for
`pause`/`resume`/`restart`. So `request-revision`, like `reject`, cancels the
task; the two differ only in the outcome recorded and reported, not in what
happens to the run. Presenting anything else would be a control that reports
success and changes nothing.
"""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, Header, Query, Response
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from gateway.app.api import concurrency, idempotency, pagination, permissions
from gateway.app.api.auth import require_action, visible_projects
from gateway.app.api.errors import CONFLICT, NOT_FOUND, VALIDATION_FAILED, ApiError
from gateway.app.api.routes.sessions import redact
from gateway.app.api.timestamps import utc_z
from gateway.app.core.users import AuthenticatedPrincipal
from gateway.app.db.session import get_session
from gateway.app.services import store
from gateway.app.services.audit import record_event
from shared.protocol import ApprovalDecision, PolicyLevel, TaskState


router = APIRouter(prefix="/api/v1")

DECISIONS_ENDPOINT = "/api/v1/decisions"

# The one state a decision can be resolved from. A task that already left it —
# approved, rejected, revision requested, or moved on for any other reason
# (expired, cancelled independently) — answers `approve`/`reject`/
# `request-revision` with a conflict rather than acting again.
DECIDABLE = {TaskState.AWAITING_APPROVAL.value}

# See the module docstring: every decision served today is at this level, but
# the check is written against the enum rather than "always require it" so a
# future non-sensitive decision is not silently forced through the same gate.
CRITICAL_POLICY_LEVELS = {PolicyLevel.SENSITIVE.value}

_DECISION_OUTCOME_TO_ROUTE_SEGMENT = {
    ApprovalDecision.APPROVED: "approve",
    ApprovalDecision.REJECTED: "reject",
    ApprovalDecision.REVISION_REQUESTED: "request-revision",
}


class DecisionApproveRequest(BaseModel):
    reason: str | None = Field(default=None, max_length=4000)
    # The anti-accidental-action mechanism the issue asks for on a critical
    # decision: a bare `If-Match` proves the client saw the current state, not
    # that the operator meant to approve it, so a critical decision additionally
    # requires this explicit bit. See `CRITICAL_POLICY_LEVELS`.
    confirm: bool = False


class DecisionRejectRequest(BaseModel):
    # Non-empty is enforced by `min_length`, which FastAPI reports as the
    # standard `validation_failed` envelope — the acceptance criterion is met by
    # the request never reaching the handler rather than by a check inside it.
    reason: str = Field(min_length=1, max_length=4000)


class DecisionRevisionRequest(BaseModel):
    reason: str = Field(min_length=1, max_length=4000)


def _iso(value: datetime | None) -> str | None:
    return utc_z(value)


def _decision_state(task) -> str:
    """The caller-facing state: `pending`, or the recorded outcome.

    `pending` has no column value of its own — it is `state ==
    AWAITING_APPROVAL` — while the outcomes read `approval_state`, which
    `decide_task_approval` sets and never clears. A decision row with neither
    condition true cannot occur: `policy_level is not None` (the predicate
    `store.get_decision_for_projects`/`list_decisions_page` already applied) is
    set only alongside `AWAITING_APPROVAL`, and leaving that state only ever
    happens through `decide_task_approval`.
    """
    if task.state == TaskState.AWAITING_APPROVAL.value:
        return "pending"
    return task.approval_state or "unknown"


def _decision_dto(task) -> dict:
    """Mobile representation of a decision.

    Omits `impact`, `evidence` and `recommendation`: nothing in this system
    populates them today (no submission path collects them — see
    `docs/api/README.md`'s rule against publishing an unreferenced promise), and
    a null-always field is indistinguishable from one the client can build
    against. `rationale` is different: it is `approval_reason`, which is real
    once a decision is made, and simply absent (null) before then.
    """
    return {
        "id": task.id,
        "projectId": task.project_id,
        "executorId": task.executor_id,
        "request": redact(task.instruction),
        "mode": task.mode,
        "state": _decision_state(task),
        "risk": task.policy_level,
        "urgency": task.priority,
        "revision": task.revision,
        "requestedBy": task.requested_by_email or task.requested_by_user_id,
        "rationale": redact(task.approval_reason),
        "createdAt": _iso(task.created_at),
        "deadline": _iso(task.expires_at),
        "decidedAt": _iso(task.completed_at),
    }


def _not_found() -> ApiError:
    return ApiError(status_code=404, code=NOT_FOUND, message="No such decision.")


@router.get("/decisions", tags=["decisions"])
async def list_decisions(
    response: Response,
    project: list[str] | None = Query(default=None),
    state: list[str] | None = Query(default=None),
    urgency: list[str] | None = Query(default=None),
    risk: list[str] | None = Query(default=None),
    deadline_before: datetime | None = Query(default=None, alias="deadlineBefore"),
    deadline_after: datetime | None = Query(default=None, alias="deadlineAfter"),
    cursor: str | None = Query(default=None),
    limit: int | None = Query(default=None),
    principal: AuthenticatedPrincipal = Depends(require_action(permissions.DECISIONS_READ)),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Decisions the caller may see, newest first."""
    projects = visible_projects(principal)
    if project:
        # `project` only ever narrows: an admin's None stays unrestricted-minus-
        # the-request, and a restricted caller cannot use the query string to
        # widen past their own `allowed_projects`.
        projects = [p for p in project if projects is None or p in projects]
    size = pagination.parse_limit(limit)

    scope = pagination.scope_digest(
        DECISIONS_ENDPOINT,
        {
            "state": sorted(state) if state else None,
            "urgency": sorted(urgency) if urgency else None,
            "risk": sorted(risk) if risk else None,
            "deadlineBefore": deadline_before.isoformat() if deadline_before else None,
            "deadlineAfter": deadline_after.isoformat() if deadline_after else None,
            "actor": principal.user_id,
            "projects": sorted(projects) if projects is not None else "*",
        },
    )

    after = None
    if cursor:
        position = pagination.decode_cursor(scope, cursor, expect={"createdAt": str, "id": str})
        after = (position["createdAt"], position["id"])

    rows = await store.list_decisions_page(
        session,
        project_ids=projects,
        decision_states=state,
        urgencies=urgency,
        risks=risk,
        deadline_before=deadline_before,
        deadline_after=deadline_after,
        after=after,
        limit=size,
    )
    page, info = pagination.paginate(
        rows,
        limit=size,
        scope=scope,
        position_of=lambda task: {"createdAt": pagination.cursor_time(task.created_at), "id": task.id},
    )
    response.headers["Cache-Control"] = "no-store"
    return {"items": [_decision_dto(task) for task in page], "page": info}


@router.get("/decisions/{decision_id}", tags=["decisions"])
async def get_decision(
    decision_id: str,
    response: Response,
    principal: AuthenticatedPrincipal = Depends(require_action(permissions.DECISIONS_READ)),
    session: AsyncSession = Depends(get_session),
) -> dict:
    task = await store.get_decision_for_projects(session, decision_id, visible_projects(principal))
    if task is None:
        raise _not_found()
    response.headers[concurrency.ETAG_HEADER] = concurrency.etag_for(task.revision)
    response.headers["Cache-Control"] = "no-store"
    return _decision_dto(task)


async def _resolve(
    *,
    decision_id: str,
    outcome: ApprovalDecision,
    reason: str | None,
    if_match: str | None,
    idempotency_key: str | None,
    principal: AuthenticatedPrincipal,
    session: AsyncSession,
    require_confirm: bool = False,
) -> dict:
    """Shared body of approve/reject/request-revision.

    Same shape as `routes/sessions.py:stop_session`: replay before doing
    anything (a client that lost the network cannot know whether its tap
    landed), then `If-Match`, then the state check, in that order — a stale
    `If-Match` is reported as staleness even when the underlying state would
    also have conflicted, because that is the more specific and more actionable
    of the two.
    """
    segment = _DECISION_OUTCOME_TO_ROUTE_SEGMENT[outcome]
    endpoint = f"{DECISIONS_ENDPOINT}/{segment}"
    projects = visible_projects(principal)
    task = await store.get_decision_for_projects(session, decision_id, projects)
    if task is None:
        raise _not_found()

    fingerprint = idempotency.fingerprint(f"{segment}:{decision_id}:{reason or ''}".encode())
    claim = None
    if idempotency_key:
        replay = await idempotency.reserve(
            session,
            key=idempotency_key,
            endpoint=endpoint,
            actor_id=principal.user_id,
            request_fingerprint=fingerprint,
        )
        if isinstance(replay, idempotency.ReplayedResponse):
            response_headers_task = await store.get_decision_for_projects(session, decision_id, projects)
            headers = {"Idempotent-Replay": "true"}
            if response_headers_task is not None:
                headers[concurrency.ETAG_HEADER] = concurrency.etag_for(response_headers_task.revision)
            return {"status_code": replay.status_code, "body": replay.body, "headers": headers}
        claim = replay

    try:
        concurrency.require_if_match(if_match, task.revision)

        if task.state not in DECIDABLE:
            raise ApiError(
                status_code=409,
                code=CONFLICT,
                message=f"A decision in state {_decision_state(task)!r} cannot be resolved again.",
                headers={concurrency.ETAG_HEADER: concurrency.etag_for(task.revision)},
            )

        if require_confirm and task.policy_level in CRITICAL_POLICY_LEVELS:
            raise ApiError(
                status_code=400,
                code=VALIDATION_FAILED,
                message="This is a critical decision. Set confirm to true to approve it.",
                details=[{"field": "/confirm", "code": "required", "message": "Confirm the approval explicitly."}],
            )

        updated = await store.decide_task_approval(session, task.id, outcome, reason)
        await record_event(
            session,
            "task",
            task.id,
            "task.decision_resolved_by_actor",
            {
                "actor_id": principal.user_id,
                "actor_email": principal.email,
                "via": "http_api",
                "outcome": outcome.value,
            },
        )
        await session.commit()
    except Exception:
        if claim is not None:
            await idempotency.release(
                session, key=idempotency_key, endpoint=endpoint, actor_id=principal.user_id, claim=claim,
            )
        raise

    body = _decision_dto(updated)
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
    return {
        "status_code": 200,
        "body": body,
        "headers": {concurrency.ETAG_HEADER: concurrency.etag_for(updated.revision)},
    }


@router.post("/decisions/{decision_id}/approve", tags=["decisions"])
async def approve_decision(
    decision_id: str,
    body: DecisionApproveRequest,
    response: Response,
    if_match: str | None = Header(default=None, alias="If-Match"),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    principal: AuthenticatedPrincipal = Depends(require_action(permissions.DECISIONS_DECIDE)),
    session: AsyncSession = Depends(get_session),
) -> dict:
    result = await _resolve(
        decision_id=decision_id,
        outcome=ApprovalDecision.APPROVED,
        reason=body.reason,
        if_match=if_match,
        idempotency_key=idempotency_key,
        principal=principal,
        session=session,
        require_confirm=not body.confirm,
    )
    response.status_code = result["status_code"]
    for name, value in result["headers"].items():
        response.headers[name] = value
    return result["body"]


@router.post("/decisions/{decision_id}/reject", tags=["decisions"])
async def reject_decision(
    decision_id: str,
    body: DecisionRejectRequest,
    response: Response,
    if_match: str | None = Header(default=None, alias="If-Match"),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    principal: AuthenticatedPrincipal = Depends(require_action(permissions.DECISIONS_DECIDE)),
    session: AsyncSession = Depends(get_session),
) -> dict:
    result = await _resolve(
        decision_id=decision_id,
        outcome=ApprovalDecision.REJECTED,
        reason=body.reason,
        if_match=if_match,
        idempotency_key=idempotency_key,
        principal=principal,
        session=session,
    )
    response.status_code = result["status_code"]
    for name, value in result["headers"].items():
        response.headers[name] = value
    return result["body"]


@router.post("/decisions/{decision_id}/request-revision", tags=["decisions"])
async def request_decision_revision(
    decision_id: str,
    body: DecisionRevisionRequest,
    response: Response,
    if_match: str | None = Header(default=None, alias="If-Match"),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    principal: AuthenticatedPrincipal = Depends(require_action(permissions.DECISIONS_DECIDE)),
    session: AsyncSession = Depends(get_session),
) -> dict:
    result = await _resolve(
        decision_id=decision_id,
        outcome=ApprovalDecision.REVISION_REQUESTED,
        reason=body.reason,
        if_match=if_match,
        idempotency_key=idempotency_key,
        principal=principal,
        session=session,
    )
    response.status_code = result["status_code"]
    for name, value in result["headers"].items():
        response.headers[name] = value
    return result["body"]
