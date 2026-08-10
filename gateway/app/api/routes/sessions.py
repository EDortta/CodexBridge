"""Agent sessions, their logs, and the one control the protocol actually has.

A "session" here is a `TaskModel`: one `codex exec` run on an executor. The
mobile vocabulary and the internal one differ on purpose — the client should not
learn the word "task" from a URL and then meet it again meaning something else
in the issues API.

## What this issue does NOT deliver, and why

Issue #9 proposes `pause`, `resume` and `restart` alongside `stop`. The agent
protocol (`shared/protocol.py:AgentMessageType`) has `task.dispatch`, `task.ack`,
`task.log`, `task.result`, `task.cancel`, `task.cancelled` and `error`. There is
no pause, no resume, and no restart: the executor cannot be told to do any of
them, so an endpoint offering them would be a button that reports success and
changes nothing.

They need a protocol change and executor support, which is a different piece of
work. `stop` maps to `task.cancel`, which exists and is already exercised by the
MCP client, so it is the one control here.

## Redaction

`shared/security.py:sanitize_log_line` covers three credential patterns and
nothing else — not filesystem paths, not host:port pairs. Issue #15 is a live
example: the executor's own machine token reached the gateway log through a URL.
So the log endpoint redacts on the way out rather than trusting what was stored,
and `docs/api/README.md` states that any endpoint returning log content owes its
own redaction.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Header, Query, Response
from sqlalchemy.ext.asyncio import AsyncSession

from gateway.app.api import concurrency, idempotency, pagination
from gateway.app.api.auth import CANCEL_SCOPE, READ_SCOPE, require_scope, visible_projects
from gateway.app.api.errors import CONFLICT, NOT_FOUND, ApiError
from gateway.app.core.users import AuthenticatedPrincipal
from gateway.app.db.session import get_session
from gateway.app.services import store
from gateway.app.services.audit import record_event
from gateway.app.services.agent_hub import AgentHub, hub_envelope
from shared.protocol import AgentMessageType, TaskState
from shared.security import sanitize_log_line


router = APIRouter(prefix="/api/v1")

SESSIONS_ENDPOINT = "/api/v1/sessions"

# States from which a stop is meaningful. Cancelling an already-finished session
# is not an error the client caused, but it is not a no-op either: reporting
# success would tell the operator an action happened that did not.
STOPPABLE = {
    TaskState.QUEUED.value,
    TaskState.WAITING_EXECUTOR.value,
    TaskState.RUNNING.value,
    TaskState.AWAITING_APPROVAL.value,
}

# Redaction applied to every log line leaving this API, on top of whatever was
# applied on the way in. Each pattern is here because the value it matches has
# actually appeared in this system's logs or is one line of code away from it.
_REDACTIONS: tuple[tuple[re.Pattern[str], str], ...] = (
    # Credentials in URL userinfo — `redis://:pw@host`, `postgres://u:pw@host`.
    # Listed first: the host:port rule below would otherwise replace the host and
    # leave the password standing next to the placeholder.
    (re.compile(r"(?i)\b([a-z][a-z0-9+.-]*://)[^\s/@:]*(?::[^\s/@]*)?@"), r"\1[CREDENTIAL]@"),
    # Credentials in query strings — issue #15, observed in production.
    (re.compile(r"(?i)([?&](?:token|access_token|refresh_token|api_key|apikey|secret|password|passwd|pwd|sig|signature)=)[^\s&\"']+"), r"\1[REDACTED]"),
    # The same names as a bare assignment or a JSON/YAML field, which the
    # query-string form misses entirely.
    (re.compile(r"(?i)([\"']?\b(?:token|access_token|refresh_token|api[_-]?key|secret|password|passwd|pwd)\b[\"']?\s*[:=]\s*)[\"']?[^\s,;}\"']{4,}[\"']?"), r"\1[REDACTED]"),
    # Authorization headers of any scheme, not just Bearer.
    (re.compile(r"(?i)\b(authorization\s*:\s*)\S+\s+\S+"), r"\1[REDACTED]"),
    (re.compile(r"(?i)\b(x-api-key\s*:\s*)\S+"), r"\1[REDACTED]"),
    # Provider token shapes. `ghp_` is covered upstream; `github_pat_` is the
    # current GitHub format and was not.
    (re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}"), "[REDACTED]"),
    (re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b"), "[REDACTED]"),
    (re.compile(r"\bxox[abposr]-[A-Za-z0-9-]{10,}"), "[REDACTED]"),
    # JWTs: three base64url segments.
    (re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}"), "[REDACTED]"),
    # PEM blocks, from the header onward.
    (re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?(?:-----END [A-Z ]*PRIVATE KEY-----|$)"), "[REDACTED]"),
    # Absolute filesystem paths, POSIX and Windows. The Windows form also
    # discloses the OS account name.
    (re.compile(r"(?<![\w.])/(?:home|opt|etc|var|root|srv|usr|tmp|mnt|media)/[^\s\"']*"), "[PATH]"),
    (re.compile(r"\b[A-Za-z]:\\[^\s\"']*"), "[PATH]"),
    # Relative traversal, which the absolute rule cannot see.
    (re.compile(r"(?<![\w])\.{1,2}/[^\s\"']*"), "[PATH]"),
    # host:port and bare private addresses.
    (re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}:\d{2,5}\b"), "[ADDR]"),
    (re.compile(r"\b(?:10\.\d{1,3}|192\.168|172\.(?:1[6-9]|2\d|3[01])|127\.0)\.\d{1,3}\.\d{1,3}\b"), "[ADDR]"),
    # Internal hostnames.
    (re.compile(r"(?i)\b[a-z0-9][a-z0-9.-]*\.(?:internal|local|lan|intranet|corp)\b"), "[HOST]"),
    # Terminal control sequences. `\x1b]0;title\x07` retitles a CLI consumer's
    # window; CSI sequences let output rewrite what an operator already read.
    (re.compile(r"\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)"), ""),
    (re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]"), ""),
)


def redact(value: str | None) -> str | None:
    """Strip from any executor-influenced text what a response must never carry.

    Applied to **every** field carrying executor or operator free text — log
    lines, `lastError`, and the instruction — not only to logs. The instruction
    is written by a human who may paste a path or a token into it, and shipping
    it raw beside a redacted `lastError` was an inconsistency an audit caught.

    Order matters: URL userinfo is handled before host:port, or the host is
    replaced and the password is left standing next to the placeholder.
    """
    if value is None:
        return None
    out = sanitize_log_line(value)
    for pattern, replacement in _REDACTIONS:
        out = pattern.sub(replacement, out)
    return out


def _cursor_time(value: datetime) -> str:
    """Cursor form of a timestamp: ISO 8601, always carrying microseconds.

    `str(datetime)` omits the fractional part when it is zero, so a cursor built
    on a whole-second timestamp matched nothing and truncated the list with no
    error. `isoformat` round-trips through `datetime.fromisoformat`, which is
    what the store parses before comparing against the column.
    """
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.isoformat()


def _iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _session_dto(task) -> dict:
    """Mobile representation of a session.

    Deliberately omits `ProjectModel.path`, the command line and the stored
    result blob. The first is the canonical trap named in
    `docs/api/README.md`; the other two carry filesystem paths and arbitrary
    executor output that no redaction here has audited.
    """
    return {
        "id": task.id,
        "projectId": task.project_id,
        "executorId": task.executor_id,
        "instruction": redact(task.instruction),
        "mode": task.mode,
        "state": task.state,
        "priority": task.priority,
        "revision": task.revision,
        "createdAt": _iso(task.created_at),
        "startedAt": _iso(task.started_at),
        "completedAt": _iso(task.completed_at),
        "expiresAt": _iso(task.expires_at),
        "approvalState": task.approval_state,
        "requestedBy": task.requested_by_email or task.requested_by_user_id,
        "interventionRequired": task.state == TaskState.AWAITING_APPROVAL.value,
        "lastError": redact(task.last_error),
    }


def _not_found() -> ApiError:
    return ApiError(
        status_code=404,
        code=NOT_FOUND,
        message="No such session.",
    )


@router.get("/sessions", tags=["sessions"])
async def list_sessions(
    response: Response,
    state: list[str] | None = Query(default=None),
    cursor: str | None = Query(default=None),
    limit: int | None = Query(default=None),
    principal: AuthenticatedPrincipal = Depends(require_scope(READ_SCOPE)),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Sessions the caller may see, newest first."""
    projects = visible_projects(principal)
    size = pagination.parse_limit(limit)
    # The caller is part of the cursor's identity. Without it, a cursor issued
    # to one principal is accepted from another: the project filter still holds,
    # so no forbidden row is returned, but the second caller silently skips rows
    # it is entitled to see while `hasMore` asserts the page is authoritative.
    # The visible projects go in too, so a permission change invalidates cursors
    # rather than paging through a stale view.
    scope = pagination.scope_digest(
        SESSIONS_ENDPOINT,
        {
            "state": sorted(state) if state else None,
            "actor": principal.user_id,
            "projects": sorted(projects) if projects is not None else "*",
        },
    )

    after = None
    if cursor:
        position = pagination.decode_cursor(scope, cursor, expect={"createdAt": str, "id": str})
        after = (position["createdAt"], position["id"])

    rows = await store.list_tasks_page(
        session, project_ids=projects, states=state, after=after, limit=size
    )
    page, info = pagination.paginate(
        rows,
        limit=size,
        scope=scope,
        position_of=lambda task: {"createdAt": _cursor_time(task.created_at), "id": task.id},
    )
    response.headers["Cache-Control"] = "no-store"
    return {"items": [_session_dto(task) for task in page], "page": info}


@router.get("/sessions/{session_id}", tags=["sessions"])
async def get_session_detail(
    session_id: str,
    response: Response,
    principal: AuthenticatedPrincipal = Depends(require_scope(READ_SCOPE)),
    session: AsyncSession = Depends(get_session),
) -> dict:
    task = await store.get_task_for_projects(session, session_id, visible_projects(principal))
    if task is None:
        raise _not_found()
    response.headers[concurrency.ETAG_HEADER] = concurrency.etag_for(task.revision)
    response.headers["Cache-Control"] = "no-store"
    return _session_dto(task)


@router.get("/sessions/{session_id}/logs", tags=["sessions"])
async def get_session_logs(
    session_id: str,
    response: Response,
    offset: int = Query(default=0, ge=0),
    limit: int | None = Query(default=None),
    principal: AuthenticatedPrincipal = Depends(require_scope(READ_SCOPE)),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Log lines from `offset`, the append-only scheme the store already uses.

    Not cursor-paginated, and that is the contract's rule rather than an
    exception to it: log lines are addressed by a monotonic integer offset in
    `task_logs`, and the MCP client already reads the same rows that way. One
    table with two paging vocabularies would be a v1-breaking mistake to undo.
    """
    task = await store.get_task_for_projects(session, session_id, visible_projects(principal))
    if task is None:
        raise _not_found()

    size = pagination.parse_limit(limit, default=200, maximum=1000)
    rows = await store.get_logs(session, session_id, offset=offset, limit=size + 1)
    has_more = len(rows) > size
    rows = rows[:size]
    response.headers["Cache-Control"] = "no-store"
    return {
        "items": [
            {
                "offset": row.offset,
                "stream": row.stream,
                "line": redact(row.line),
                "at": _iso(row.created_at),
            }
            for row in rows
        ],
        "nextOffset": (rows[-1].offset + 1) if rows else offset,
        "hasMore": has_more,
    }


@router.post("/sessions/{session_id}/stop", tags=["sessions"])
async def stop_session(
    session_id: str,
    response: Response,
    if_match: str | None = Header(default=None, alias="If-Match"),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    principal: AuthenticatedPrincipal = Depends(require_scope(CANCEL_SCOPE)),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Cancel a running or queued session.

    `stop` is the only control here: `task.cancel` is the only lifecycle message
    the agent protocol defines. See the module docstring.
    """
    from gateway.app.main import hub  # imported late: main includes this router

    projects = visible_projects(principal)
    task = await store.get_task_for_projects(session, session_id, projects)
    if task is None:
        raise _not_found()

    # Replay before doing anything. A mobile client that lost the network after
    # sending this cannot know whether the session was stopped; without replay
    # its only options are to retry and risk acting twice, or not retry and
    # leave a session it believes is still running.
    fingerprint = idempotency.fingerprint(f"stop:{session_id}".encode())
    claim = None
    if idempotency_key:
        outcome = await idempotency.reserve(
            session,
            key=idempotency_key,
            endpoint=f"{SESSIONS_ENDPOINT}/stop",
            actor_id=principal.user_id,
            request_fingerprint=fingerprint,
        )
        if isinstance(outcome, idempotency.ReplayedResponse):
            response.status_code = outcome.status_code
            response.headers["Idempotent-Replay"] = "true"
            # The contract declares ETag on this 200, and a client replaying
            # after a lost network needs a validator for its next write — which
            # is the whole scenario replay exists for.
            fresh = await store.get_task_for_projects(session, session_id, projects)
            if fresh is not None:
                response.headers[concurrency.ETAG_HEADER] = concurrency.etag_for(fresh.revision)
            return outcome.body
        claim = outcome

    try:
        concurrency.require_if_match(if_match, task.revision)

        if task.state not in STOPPABLE:
            raise ApiError(
                status_code=409,
                code=CONFLICT,
                message=f"A session in state {task.state!r} cannot be stopped.",
                headers={concurrency.ETAG_HEADER: concurrency.etag_for(task.revision)},
            )

        notified = await _dispatch_cancel(hub, task)
        updated = await store.update_task_state(session, task.id, TaskState.CANCELLED)
        # Release the executor's concurrency slot. `task.result` and
        # `task.cancelled` both do this in main.py; the HTTP stop did not, so a
        # cancelled RUNNING task kept its slot for the life of the process and
        # an executor with max_concurrent_tasks=1 was never dispatched again.
        await hub.mark_task_finished(task.executor_id, task.id)
        # Who stopped it. `store.update_task_state` records `task.state_changed`
        # with no actor, and the idempotency record — the only other place the
        # user id appeared — is written only when the client sends a key, and
        # expires. Without this, "who cancelled this session" is unanswerable
        # from the audit trail, which is half of #9's own acceptance criterion.
        await record_event(
            session,
            "task",
            task.id,
            "task.stopped_by_actor",
            {
                "actor_id": principal.user_id,
                "actor_email": principal.email,
                "via": "http_api",
                "executor_notified": notified,
            },
        )
        await session.commit()
    except Exception:
        # The claim must not outlive a failed attempt, or every retry is told
        # "still in flight" until the window elapses.
        if claim is not None:
            await idempotency.release(
                session,
                key=idempotency_key,
                endpoint=f"{SESSIONS_ENDPOINT}/stop",
                actor_id=principal.user_id,
                claim=claim,
            )
        raise

    body = _session_dto(updated)
    body["executorNotified"] = notified
    if claim is not None:
        await idempotency.complete(
            session,
            key=idempotency_key,
            endpoint=f"{SESSIONS_ENDPOINT}/stop",
            actor_id=principal.user_id,
            status_code=200,
            body=body,
            claim=claim,
            request_fingerprint=fingerprint,
        )
    response.headers[concurrency.ETAG_HEADER] = concurrency.etag_for(updated.revision)
    return body


async def _dispatch_cancel(hub: AgentHub, task) -> bool:
    """Tell the executor, if it is listening. Returns whether it was told.

    A disconnected executor does not fail the request: refusing would leave the
    operator unable to stop a session exactly when the executor is unreachable.

    But the session being marked cancelled here is **not** the same as the run
    stopping. Nothing replays `task.cancel` on reconnect — `recover_tasks_after_startup`
    runs at gateway startup only, and skips already-cancelled tasks — so a
    disconnected executor keeps running its `codex exec` to completion. An
    earlier version of this docstring claimed a reconnect recovery that does not
    exist; the response now reports `executorNotified` instead, so the operator
    is told the difference rather than shown a stop that did not happen.
    Replaying the cancel is issue #17.
    """
    if not hub.is_connected(task.executor_id):
        return False
    await hub.send(
        task.executor_id,
        hub_envelope(task.executor_id, AgentMessageType.TASK_CANCEL.value, {"task_id": task.id}),
    )
    return True


@router.post("/sessions/{session_id}/explain-error", tags=["sessions"])
async def explain_session_error(
    session_id: str,
    principal: AuthenticatedPrincipal = Depends(require_scope(READ_SCOPE)),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """A structured account of why a session failed, assembled server-side.

    No model, no executor round trip: it reports the recorded state, the stored
    error and the last `stderr` lines, all redacted. Calling this an
    "explanation" would overstate it, so the response says what it is — the
    evidence, gathered in one place, instead of the client stitching together a
    detail call and a log call and guessing which lines mattered.
    """
    task = await store.get_task_for_projects(session, session_id, visible_projects(principal))
    if task is None:
        raise _not_found()

    # The TAIL of the stream. Reading `offset=0, limit=1000` and slicing the end
    # of that window returned the *oldest* stderr on any session with more than
    # a thousand lines — stale evidence presented as recent, and a way for
    # whoever produces output to push their own traces out of view by flooding
    # the first thousand lines.
    stderr = await store.get_recent_logs(session, session_id, stream="stderr", limit=20)

    reasons = []
    if task.state == TaskState.EXPIRED.value:
        reasons.append("The session passed its expiry time before completing.")
    if task.state == TaskState.LOST.value:
        reasons.append(
            "The gateway restarted while this session was running and the executor "
            "never reported a result."
        )
    if task.state == TaskState.CANCELLED.value:
        reasons.append("The session was cancelled.")
    if task.approval_state and task.state == TaskState.AWAITING_APPROVAL.value:
        reasons.append("The session is held for approval and has not started.")
    if task.last_error:
        reasons.append("The executor reported an error.")

    return {
        "sessionId": task.id,
        "state": task.state,
        "reasons": reasons or ["No failure recorded for this session."],
        "lastError": redact(task.last_error),
        "recentStderr": [
            {"offset": row.offset, "line": redact(row.line), "at": _iso(row.created_at)}
            for row in stderr
        ],
        "generatedAt": _iso(datetime.now(timezone.utc)),
    }
