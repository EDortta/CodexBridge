"""Operational decisions: sensitive tasks AND sensitive forge writes held for

a human to resolve — issue #6, extended by #79/#80's WK-20260902-forge-
binding (PR B4) to a second source.

A "decision" is not a new domain object, and this PR does not change that —
it widens what "not a new domain object" is allowed to mean. A task decision
is still exactly what it always was: a `TaskModel` that needed approval
(`shared.policy.evaluate_task_policy` withheld it, `store.create_task`
recorded the risk level in `TaskModel.policy_level`, and
`store.decide_task_approval` resolves it). A FORGE decision is the same
shape over a different row: a `ForgeOperationModel` that needed approval
(`shared.policy.forge_operation_policy_level` withheld it,
`store.create_forge_operation` recorded it, `store.decide_forge_operation`
resolves it) — see that model's own docstring for why it is a separate
table from `TaskModel` rather than a variant of one.

## Why this endpoint projects two sources instead of staying task-only

Before this PR, a forge WRITE awaiting a human decision showed up nowhere an
operator already looks — `gateway/app/services/store.py`'s own forge-
operations section is explicit that PR B3 shipped with "no REST route or MCP
tool" for it at all. The operator's decision, made explicitly in this
session: ONE inbox, not two. A GitHub issue write and a coding-agent session
are not the same kind of thing, so this endpoint does not pretend they are —
`decisionType` on the `Decision` schema is the honest discriminator a client
uses to render (and to know what it is approving) — but they share the ONE
queue a human actually has to clear, so they share the one endpoint.

## What stays true for a task decision, unchanged

The existing `Decision` DTO shape for a task is preserved byte for byte: no
field removed or renamed, no existing field's `required`-ness narrowed. Every
addition this PR makes to the schema is either a new, optional field (always
`null` for a task) or a widening of an existing field's type from
non-nullable to nullable (`mode`, `deadline` — real for a task, `null` for a
forge decision, which has neither a mode nor an expiry). A client that never
learns about forge decisions keeps working exactly as it did before this PR;
it will now also start seeing forge rows in its list unless it filters them
out, since there was never a way to ask this endpoint for "tasks only".

## Id collision

Explicitly ruled out, not merely made unlikely: see
`gateway/app/services/store.py`'s own "Decisions" section comment
(`FORGE_DECISION_ID_PREFIX`) for the full reasoning. Short version: a forge
decision's `id` is always `f"forge:{operation_id}"`; a task decision's `id`
is always the bare `TaskModel.id`; a `uuid4()` string can never contain a
`:`, so the two id spaces this endpoint serves are disjoint by construction.

## Why every decision here is "critical"

`shared/policy.py:evaluate_task_policy` withholds approval — the only way a
task becomes `AWAITING_APPROVAL` — exactly when its level is `sensitive`, and
`shared/policy.py:forge_operation_policy_level` withholds it, unconditionally
and with no bypass field, for every forge WRITE kind. So `policy_level` (or
its forge equivalent) is `sensitive` for every row this router will ever
serve today. The `risk` filter and the confirmation requirement on `approve`
are still written generally, against `PolicyLevel`, rather than hardcoded to
today's one value, for both sources.

## Approving a forge decision dispatches — issue #20 does not get to happen twice

Issue #20 existed because `POST /api/v1/decisions/{id}/approve` once called
`store.decide_task_approval` and returned without ever nudging `AgentHub` —
an approved task sat `waiting_executor` until an unrelated event happened to
dispatch it (`docs/napkin-lessons.md`, 2026-08-21). The fix there was
`AgentHub.dispatch_available`, called from `_resolve()` right after a task
decision resolves `APPROVED`. `_resolve()` below calls its forge sibling,
`AgentHub.dispatch_forge_operation`, in exactly the same place, for exactly
the same reason: an approved forge write that never got told to dispatch
would be issue #20 again, on a different table. Both calls are followed by
`session.refresh(updated)` for the same reason #20's own round-2 council
fix added it there — a same-request dispatch bumps the row's `revision` a
second time, in the hub's own session, and the response's ETag has to
reflect that or a client's next `If-Match` gets a spurious `409`.

## request-revision is not a fourth state the task can leave

`ApprovalDecision.REVISION_REQUESTED` exists so a decision's outcome can be
told apart from a plain rejection, but the agent protocol has no message that
reopens a task (or a forge operation) for editing — the same gap
`routes/sessions.py` documents for `pause`/`resume`/`restart`. So
`request-revision`, like `reject`, cancels the underlying row; the two
differ only in the outcome recorded and reported, not in what happens next.
"""

from __future__ import annotations

import json
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
from gateway.app.models.entities import ForgeOperationModel
from gateway.app.services import store
from gateway.app.services.audit import record_event
from shared.protocol import ApprovalDecision, ForgeOperationKind, PolicyLevel, TaskState


router = APIRouter(prefix="/api/v1")

DECISIONS_ENDPOINT = "/api/v1/decisions"

# The one state a decision can be resolved from. A task that already left it —
# approved, rejected, revision requested, or moved on for any other reason
# (expired, cancelled independently) — answers `approve`/`reject`/
# `request-revision` with a conflict rather than acting again. Spelled out as
# the literal string here rather than imported from `store.
# FORGE_OPERATION_DECIDABLE_STATE`: the two enums happen to share this exact
# spelling (`TaskState.AWAITING_APPROVAL.value == "awaiting_approval" ==
# store.FORGE_OPERATION_DECIDABLE_STATE`), which is what lets `_resolve`
# below check `row.state not in DECIDABLE` uniformly for either source
# without an `isinstance` branch just for this one comparison.
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


def _decision_state(row) -> str:
    """The caller-facing state: `pending`, or the recorded outcome, for

    EITHER source. Delegates to `store.decision_state_of` rather than
    re-deriving it: `list_decisions_page`'s own `decision_states` filter
    reads that same function's mapping, and a route that computed this
    differently could report a state for a row the store-layer filter would
    not agree is in that state at all.
    """
    return store.decision_state_of(row)


def _forge_decision_request_summary(row: ForgeOperationModel) -> str:
    """A short, human-readable stand-in for `request` on a forge decision --

    the one existing field every client already renders, so a client that
    has not learned `decisionType` yet still shows something legible ("open
    an issue on acme/widgets: <title>") instead of nothing. Structured
    fields (`forgeKind`, `repoIdentity`, `issueNumber`) carry the same
    information for a client that HAS learned to read them; this is not
    their replacement, only a fallback.
    """
    payload = json.loads(row.payload_json) if row.payload_json else {}
    title = payload.get("title")
    body = payload.get("body")
    if row.kind == ForgeOperationKind.ISSUE_OPEN.value:
        return f"Open an issue on {row.repo_identity}: {title or ''}".strip()
    if row.kind == ForgeOperationKind.ISSUE_COMMENT.value:
        return f"Comment on {row.repo_identity}#{payload.get('issue_number')}: {body or ''}".strip()
    if row.kind == ForgeOperationKind.ISSUE_CLOSE.value:
        return f"Close {row.repo_identity}#{payload.get('issue_number')}"
    return f"{row.kind} on {row.repo_identity}"


def _decision_dto(row) -> dict:
    """Mobile representation of a decision -- a `TaskModel` row (unchanged

    shape) or a `ForgeOperationModel` row (issue #79/#80, PR B4). Every key
    is present for BOTH kinds; a key that names a concept the other kind
    does not have (`mode`/`urgency`/`deadline` for forge; `forgeKind`/
    `repoIdentity`/`issueNumber` for a task) is simply `null` there, rather
    than omitted -- a client branching on `decisionType` never has to also
    guard each field's mere presence.

    Omits `impact`, `evidence` and `recommendation`: nothing in this system
    populates them today (no submission path collects them — see
    `docs/api/README.md`'s rule against publishing an unreferenced promise), and
    a null-always field is indistinguishable from one the client can build
    against. `rationale` is different: it is `approval_reason`, which is real
    once a decision is made, and simply absent (null) before then.
    """
    if isinstance(row, ForgeOperationModel):
        payload = json.loads(row.payload_json) if row.payload_json else {}
        return {
            "id": store.forge_decision_public_id(row.id),
            "projectId": row.project_id,
            "executorId": row.executor_id,
            "request": redact(_forge_decision_request_summary(row)),
            "mode": None,
            "decisionType": "forge_operation",
            "forgeKind": row.kind,
            "repoIdentity": row.repo_identity,
            "issueNumber": payload.get("issue_number"),
            "state": _decision_state(row),
            "risk": PolicyLevel.SENSITIVE.value,
            "urgency": None,
            "revision": row.revision,
            "requestedBy": row.requested_by_email or row.requested_by_user_id,
            "rationale": redact(row.approval_reason),
            "createdAt": _iso(row.created_at),
            "deadline": None,
            "decidedAt": _iso(row.resolved_at),
        }
    return {
        "id": row.id,
        "projectId": row.project_id,
        "executorId": row.executor_id,
        "request": redact(row.instruction),
        "mode": row.mode,
        "decisionType": "task",
        "forgeKind": None,
        "repoIdentity": None,
        "issueNumber": None,
        "state": _decision_state(row),
        "risk": row.policy_level,
        "urgency": row.priority,
        "revision": row.revision,
        "requestedBy": row.requested_by_email or row.requested_by_user_id,
        "rationale": redact(row.approval_reason),
        "createdAt": _iso(row.created_at),
        "deadline": _iso(row.expires_at),
        "decidedAt": _iso(row.completed_at),
    }


def _decision_public_id(row) -> str:
    """The `id` this endpoint exposes for `row` -- `store.

    forge_decision_public_id` for a forge operation, the bare row id for a
    task. Used both by `_decision_dto` (via that same call inline) and by
    the pagination cursor below, so a page's cursor always names the same id
    the page's own items were rendered under.
    """
    if isinstance(row, ForgeOperationModel):
        return store.forge_decision_public_id(row.id)
    return row.id


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
        position_of=lambda row: {"createdAt": pagination.cursor_time(row.created_at), "id": _decision_public_id(row)},
    )
    response.headers["Cache-Control"] = "no-store"
    return {"items": [_decision_dto(row) for row in page], "page": info}


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
    row = await store.get_decision_for_projects(session, decision_id, projects)
    if row is None:
        raise _not_found()
    is_forge = isinstance(row, ForgeOperationModel)

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
            response_headers_row = await store.get_decision_for_projects(session, decision_id, projects)
            headers = {"Idempotent-Replay": "true"}
            if response_headers_row is not None:
                headers[concurrency.ETAG_HEADER] = concurrency.etag_for(response_headers_row.revision)
            return {"status_code": replay.status_code, "body": replay.body, "headers": headers}
        claim = replay

    try:
        concurrency.require_if_match(if_match, row.revision)

        if row.state not in DECIDABLE:
            raise ApiError(
                status_code=409,
                code=CONFLICT,
                message=f"A decision in state {_decision_state(row)!r} cannot be resolved again.",
                headers={concurrency.ETAG_HEADER: concurrency.etag_for(row.revision)},
            )

        # Every forge decision served here is a WRITE (`store.
        # _FORGE_DECISION_KIND_VALUES` -- a READ never reaches
        # `awaiting_approval`, so it never reaches this function at all), and
        # every forge write is unconditionally `SENSITIVE`
        # (`shared.policy.forge_operation_policy_level` has no bypass field,
        # by design). There is no `ForgeOperationModel.policy_level` column
        # to read the way `TaskModel.policy_level` is read below -- it does
        # not need one, because the answer is always the same one value.
        effective_policy_level = PolicyLevel.SENSITIVE.value if is_forge else row.policy_level
        if require_confirm and effective_policy_level in CRITICAL_POLICY_LEVELS:
            raise ApiError(
                status_code=400,
                code=VALIDATION_FAILED,
                message="This is a critical decision. Set confirm to true to approve it.",
                details=[{"field": "/confirm", "code": "required", "message": "Confirm the approval explicitly."}],
            )

        if is_forge:
            updated = await store.decide_forge_operation(session, row.id, outcome, reason)
        else:
            updated = await store.decide_task_approval(session, row.id, outcome, reason)

        if is_forge and updated.state == "approved":
            # The forge sibling of issue #20's fix below: an approved forge
            # write that this endpoint never told to dispatch would be #20
            # again, on `forge_operations` instead of `tasks` — see this
            # module's own docstring, "Approving a forge decision
            # dispatches". `dispatch_forge_operation` is the real gate
            # (`AgentHub`'s own docstring): it raises unless the row is
            # already `approved` (it is, we just set it) and returns `False`
            # rather than raising when the executor is offline — exactly the
            # same no-op-for-a-disconnected-executor posture
            # `dispatch_available` already has for a task, so no extra guard
            # is needed here either.
            from gateway.app.main import hub  # imported late: main includes this router

            await hub.dispatch_forge_operation(updated.id)
            # Same reason `restart_session`/the task branch below refresh:
            # `dispatch_forge_operation` runs in `AgentHub`'s OWN session and,
            # when it dispatches, bumps `revision` again via
            # `store.mark_forge_operation_dispatched`. Without this refresh
            # the response's ETag would report the pre-dispatch revision.
            await session.refresh(updated)
        elif not is_forge and updated.state == TaskState.WAITING_EXECUTOR.value:
            # Issue #20 (duplicate: #18): this was the only caller of
            # `decide_task_approval` that never nudged the queue afterward —
            # the MCP transport's `approve_codex_task` has done this since
            # before this REST API existed. `dispatch_available` is the
            # shared entry point both now use (`AgentHub.dispatch_available`);
            # it already no-ops for an offline or at-capacity executor, so no
            # extra guard is needed here. `reject`/`request-revision` never
            # reach this branch: `decide_task_approval` only sets
            # `WAITING_EXECUTOR` for an `APPROVED` outcome.
            from gateway.app.main import hub  # imported late: main includes this router

            await hub.dispatch_available(updated.executor_id)
            # `dispatch_available` runs in its own session (`AgentHub`'s
            # `session_factory`) and, when it dispatches, bumps `revision`
            # again via `store.update_task_state`. `updated` is still the
            # pre-dispatch row in this session's identity map, so without a
            # refresh the response below (`_decision_dto`/`etag_for`) would
            # hand the client a revision one behind the task's real state —
            # the same hazard `routes/sessions.py:restart_session` guards
            # against with the same call after its own dispatch.
            await session.refresh(updated)
        await record_event(
            session,
            "forge_operation" if is_forge else "task",
            row.id,
            "forge_operation.decision_resolved_by_actor" if is_forge else "task.decision_resolved_by_actor",
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
