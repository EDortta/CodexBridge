from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from gateway.app.api import idempotency, permissions
from gateway.app.api.errors import ApiError
from gateway.app.models.entities import ExecutorModel, IssueModel
from gateway.app.services import store
from gateway.app.services.agent_hub import AgentHub, hub_envelope
from gateway.app.services.audit import record_event
from gateway.app.services.issue_types import IssuePlanningError
from gateway.app.mcp.tools import tool_definitions
from gateway.app.core.users import AuthenticatedPrincipal
from gateway.app.version import APP_VERSION
from shared.protocol import (
    AgentEngine,
    AgentEnvelope,
    AgentMessageType,
    ApprovalDecision,
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


def _text_result(message: str, data: dict) -> dict:
    return {
        "structuredContent": data,
        "content": [{"type": "text", "text": message}],
    }


async def handle_mcp_call(
    body: dict,
    session: AsyncSession,
    hub: AgentHub,
    principal: AuthenticatedPrincipal | None = None,
) -> dict:
    method = body.get("method")
    rpc_id = body.get("id")
    if method == "initialize":
        return {
            "jsonrpc": "2.0",
            "id": rpc_id,
            "result": {
                "protocolVersion": "2025-06-18",
                "serverInfo": {"name": "codex-bridge", "version": APP_VERSION},
                "instructions": (
                    "Use apenas project_id e executor_id retornados por este servidor. "
                    "Nao presuma caminhos e trate tarefas sensiveis como aprovacao pendente."
                ),
                "capabilities": {"tools": {}},
            },
        }
    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": rpc_id, "result": {"tools": tool_definitions()}}
    if method != "tools/call":
        raise HTTPException(status_code=400, detail=f"unsupported_method:{method}")

    params = body.get("params", {})
    tool_name = params.get("name")
    arguments = params.get("arguments", {})

    def require_scope(scope: str) -> None:
        if principal is None:
            raise HTTPException(status_code=401, detail="oauth_required")
        if not principal.has_scope(scope):
            raise HTTPException(status_code=403, detail=f"missing_scope:{scope}")

    def require_action(action: permissions.Action) -> None:
        # Epics/issues reuse the REST catalogue in gateway/app/api/permissions.py
        # instead of a hand-copied scope string: that catalogue is the one
        # `GET /api/v1/auth/me` and the REST routes both read, so a scope
        # rename or a re-classification (issue #8's ISSUES_WRITE_SCOPE) shows
        # up here for free instead of silently diverging on the next change.
        if principal is None:
            raise HTTPException(status_code=401, detail="oauth_required")
        if not permissions.is_allowed(principal, action):
            raise HTTPException(status_code=403, detail=f"missing_scope:{action.scope}")

    async def resolve_project_or_404(text: str) -> "store.ProjectModel":
        try:
            project = await store.resolve_project_reference(session, str(text))
        except store.AmbiguousProjectReference as exc:
            candidates = ", ".join(f"{c.id} ({c.name})" for c in exc.candidates)
            raise HTTPException(status_code=409, detail=f"ambiguous_project: {candidates}")
        except ValueError:
            raise HTTPException(status_code=404, detail="unknown_project")
        # require_action already ensured `principal` is not None for every
        # caller of this helper.
        if not principal.can_access_project(project.id):
            raise HTTPException(status_code=403, detail="project_access_denied")
        return project

    def require_task_access(task) -> None:
        if principal is None:
            return
        if principal.is_admin():
            return
        if task.requested_by_user_id != principal.user_id:
            raise HTTPException(status_code=403, detail="task_access_denied")

    if tool_name == "list_executors":
        require_scope("codexbridge.read")
        items = await store.list_executors(session)
        payload = {
            "executors": [
                {
                    "executor_id": item.id,
                    "display_name": item.display_name,
                    "connected": item.connected,
                    "last_seen_at": item.last_seen_at.isoformat() if item.last_seen_at else None,
                }
                for item in items
            ]
        }
        result = _text_result(f"Found {len(payload['executors'])} executors.", payload)
    elif tool_name == "executor_status":
        require_scope("codexbridge.read")
        executor = await session.get(ExecutorModel, arguments["executor_id"])
        if executor is None:
            raise HTTPException(status_code=404, detail="unknown_executor")
        payload = {
            "executor_id": executor.id,
            "connected": executor.connected,
            "last_seen_at": executor.last_seen_at.isoformat() if executor.last_seen_at else None,
        }
        result = _text_result(f"Executor {executor.id} is {'online' if executor.connected else 'offline'}.", payload)
    elif tool_name == "list_projects":
        require_scope("codexbridge.read")
        items = await store.list_projects_for_executor(session, arguments["executor_id"])
        if principal is not None and not principal.is_admin():
            items = [item for item in items if principal.can_access_project(item.id)]
        payload = {
            "projects": [
                {"project_id": item.id, "name": item.name, "enabled": item.enabled}
                for item in items
            ]
        }
        result = _text_result(f"Found {len(payload['projects'])} projects.", payload)
    elif tool_name == "submit_codex_task":
        require_scope("codexbridge.task.submit")
        request = SubmitTaskRequest.model_validate(arguments)
        if principal is not None and not principal.can_access_project(request.project_id):
            raise HTTPException(status_code=403, detail="project_access_denied")
        task = await store.create_task(
            session,
            request,
            hub.is_connected(request.executor_id),
            requested_by_user_id=principal.user_id if principal else None,
            requested_by_email=principal.email if principal else None,
            # WK-20260830: `submit_codex_task`'s own JSON Schema still names no
            # `delivery` field, so this is inert today -- included so the one
            # call site that DOES set `delivery` (`start_development_task`,
            # issue TBD) is not the only place this authority check exists.
            can_approve_push=bool(principal is not None and (principal.can_approve_sensitive or principal.is_admin())),
        )
        task = await store.get_task(session, task.id)
        if task.state == TaskState.QUEUED.value:
            dispatch_payload = await hub.dispatch_next(task.executor_id)
            if dispatch_payload is not None:
                await hub.send(
                    task.executor_id,
                    hub_envelope(task.executor_id, "task.dispatch", dispatch_payload),
                )
        payload = {"task_id": task.id, "state": task.state, "expires_at": task.expires_at.isoformat()}
        result = _text_result(f"Task {task.id} created with state {task.state}.", payload)
    elif tool_name == "get_task_status":
        require_scope("codexbridge.read")
        task = await store.get_task(session, arguments["task_id"])
        if task is None:
            raise HTTPException(status_code=404, detail="unknown_task")
        require_task_access(task)
        payload = {
            "task_id": task.id,
            "state": task.state,
            "executor_id": task.executor_id,
            "project_id": task.project_id,
            "started_at": task.started_at.isoformat() if task.started_at else None,
            "completed_at": task.completed_at.isoformat() if task.completed_at else None,
            "last_error": task.last_error,
            "session_id": task.session_id,
            # Additive, WK-20260830-chatgpt-entry-provider-and-delivery: none
            # of the fields above changed shape or meaning -- this is what
            # keeps the four Codex-named tools answering unchanged for an
            # existing caller (57a surface inventory's coexistence rule),
            # while giving the ChatGPT scheduled-Task poll surface (the other
            # half of council finding F27) something to read.
            "engine": task.engine,
            "issue_ref": task.issue_ref,
            "delivery": json.loads(task.delivery_json) if task.delivery_json else None,
            "delivery_result": json.loads(task.delivery_result_json) if task.delivery_result_json else None,
        }
        result = _text_result(f"Task {task.id} is {task.state}.", payload)
    elif tool_name == "get_task_logs":
        require_scope("codexbridge.read")
        task = await store.get_task(session, arguments["task_id"])
        if task is None:
            raise HTTPException(status_code=404, detail="unknown_task")
        require_task_access(task)
        logs = await store.get_logs(session, arguments["task_id"], arguments.get("offset", 0))
        payload = {
            "task_id": arguments["task_id"],
            "logs": [
                {"offset": item.offset, "stream": item.stream, "line": item.line, "created_at": item.created_at.isoformat()}
                for item in logs
            ],
        }
        result = _text_result(f"Returned {len(payload['logs'])} log lines.", payload)
    elif tool_name == "get_task_result":
        require_scope("codexbridge.read")
        task = await store.get_task(session, arguments["task_id"])
        if task is None:
            raise HTTPException(status_code=404, detail="unknown_task")
        require_task_access(task)
        payload = json.loads(task.result_json or "{}")
        payload["task_id"] = task.id
        payload["state"] = task.state
        result = _text_result(f"Loaded result for task {task.id}.", payload)
    elif tool_name == "continue_codex_session":
        require_scope("codexbridge.task.submit")
        parent = await store.get_task(session, arguments["task_id"])
        if parent is None:
            raise HTTPException(status_code=404, detail="unknown_task")
        require_task_access(parent)
        request = SubmitTaskRequest(
            executor_id=parent.executor_id,
            project_id=parent.project_id,
            instruction=arguments["instruction"],
            mode=TaskMode(parent.mode),
            timeout_seconds=arguments["timeout_seconds"],
            priority=TaskPriority(parent.priority),
            run_when_available=True,
            expires_at=parent.expires_at,
            # WK-20260830-chatgpt-entry-provider-and-delivery / council round 1,
            # "the sweep skeptic": without this, every continuation silently
            # defaulted to AgentEngine.CODEX regardless of which engine the
            # parent task actually ran on. A parent dispatched with
            # engine="claude" captures a Claude session id in
            # parent.session_id (store_result's provider_run_ref); a
            # continuation that then defaults to "codex" would try
            # `codex exec resume <claude-session-uuid>` on the wrong CLI.
            # Before this migration every task was implicitly "codex", so
            # there was nothing to lose -- this session's own engine
            # plumbing is what made the gap reachable.
            engine=AgentEngine(parent.engine),
        )
        task = await store.create_task(
            session,
            request,
            hub.is_connected(parent.executor_id),
            continue_session_id=parent.session_id,
            requested_by_user_id=parent.requested_by_user_id,
            requested_by_email=parent.requested_by_email,
        )
        if task.state == TaskState.QUEUED.value:
            # Issue #24: unlike `submit_codex_task` (hand-rolled dispatch just
            # above), this branch had no dispatch at all — a continuation to a
            # connected, idle executor landed QUEUED and sat until an
            # unrelated event nudged the queue. `dispatch_available` is the
            # shared mechanism PR #21 introduced for the REST approve path
            # (`gateway/app/api/routes/decisions.py`'s `_resolve`); it already
            # no-ops for an offline/at-capacity executor, so this mirrors
            # `submit_codex_task`'s outcome without hand-rolling another inline
            # is_connected/dispatch_next/send sequence.
            await hub.dispatch_available(task.executor_id)
            # `dispatch_available` runs in its own session (`AgentHub`'s
            # `session_factory`) and, when it dispatches, bumps the task's
            # state (and revision) via `store.update_task_state` on that other
            # session. `task` is still the pre-dispatch row in this session's
            # identity map; `_resolve`'s same-shaped fix (`decisions.py`,
            # issue #20) refreshes for exactly this reason, so this does too —
            # otherwise the payload below would report `queued` even after a
            # successful dispatch.
            await session.refresh(task)
        payload = {"task_id": task.id, "state": task.state, "continued_from_task_id": parent.id}
        result = _text_result(f"Continuation task {task.id} created.", payload)
    elif tool_name == "cancel_codex_task":
        require_scope("codexbridge.task.cancel")
        task = await store.get_task(session, arguments["task_id"])
        if task is None:
            raise HTTPException(status_code=404, detail="unknown_task")
        require_task_access(task)
        if task.state in {TaskState.QUEUED.value, TaskState.WAITING_EXECUTOR.value, TaskState.AWAITING_APPROVAL.value}:
            task = await store.update_task_state(session, task.id, TaskState.CANCELLED)
            await record_event(
                session,
                "task",
                task.id,
                "task.stopped_by_actor",
                {
                    "actor_id": principal.user_id,
                    "actor_email": principal.email,
                    "via": "mcp",
                    "executor_notified": False,
                },
            )
            await session.commit()
        elif task.state in STOPPABLE_TASK_STATES:
            # Covers RUNNING and the four control-transitional states
            # (PAUSING/PAUSED/RESUMING/RESTARTING), all of which hold an
            # executor concurrency slot the same way RUNNING does. Issue #17's
            # own premise is that a disconnected executor still gets a durable
            # CANCELLED write, so a later reconnect replays `task.cancel` via
            # `AgentHub.register`. Sending only fired inside
            # `hub.is_connected(...)`; when the executor was offline this
            # branch matched nothing at all — no state write, no cancel sent,
            # and (state never becoming CANCELLED) nothing for the replay
            # query to ever find. The HTTP `/stop` endpoint's `STOPPABLE` set
            # (`gateway/app/api/routes/sessions.py`, shared via
            # `shared.protocol.STOPPABLE_TASK_STATES`) already wrote CANCELLED
            # unconditionally for all eight of these states; this branch used
            # to mirror only RUNNING, so a paused session survived a cancel
            # through MCP untouched — the review that closed out #17 caught
            # the gap and this branch was widened to match.
            notified = hub.is_connected(task.executor_id)
            if notified:
                await hub.send(task.executor_id, hub_envelope(task.executor_id, "task.cancel", {"task_id": task.id}))
            task = await store.update_task_state(session, task.id, TaskState.CANCELLED)
            await hub.mark_task_finished(task.executor_id, task.id)
            # HTTP `/stop` records who stopped a session
            # (`gateway/app/api/routes/sessions.py`, `task.stopped_by_actor`);
            # this branch wrote only `task.state_changed`, with no actor, so
            # "who cancelled this session" depended on which door was used —
            # unanswerable from the audit trail for the MCP one (issue #17
            # council, "the second caller").
            await record_event(
                session,
                "task",
                task.id,
                "task.stopped_by_actor",
                {
                    "actor_id": principal.user_id,
                    "actor_email": principal.email,
                    "via": "mcp",
                    "executor_notified": notified,
                },
            )
            await session.commit()
        payload = {"task_id": task.id, "state": task.state}
        result = _text_result(f"Cancellation requested for task {task.id}.", payload)
    elif tool_name == "approve_codex_task":
        require_scope("codexbridge.task.approve")
        if principal is not None and not (principal.can_approve_sensitive or principal.is_admin()):
            raise HTTPException(status_code=403, detail="approval_not_allowed")
        decision = ApprovalDecision(arguments["decision"])
        task = await store.decide_task_approval(
            session,
            arguments["task_id"],
            decision,
            arguments.get("reason"),
        )
        if task.state == TaskState.WAITING_EXECUTOR.value:
            # Issue #20: was `is_connected(...)` + `dispatch_next` + `send`
            # hand-rolled here — the REST `POST /api/v1/decisions/{id}/approve`
            # (`gateway/app/api/routes/decisions.py`) never had an equivalent
            # and left an approved task stranded in `waiting_executor` (#18,
            # duplicate). Both now call the same `AgentHub.dispatch_available`,
            # which already no-ops for an offline/at-capacity executor.
            await hub.dispatch_available(task.executor_id)
        # Issue #19: the REST path's `_resolve()` (`routes/decisions.py`)
        # already records this actor-attributed event alongside the generic
        # `task.approval_decision` `decide_task_approval` itself writes; this
        # transport never did, so an approval via MCP/ChatGPT could be seen in
        # `audit_events` but never attributed to who approved it. Mirrors
        # `cancel_codex_task`'s own `task.stopped_by_actor` fix for the same
        # gap (issue #17 council).
        await record_event(
            session,
            "task",
            task.id,
            "task.decision_resolved_by_actor",
            {
                "actor_id": principal.user_id,
                "actor_email": principal.email,
                "via": "mcp",
                "outcome": decision.value,
            },
        )
        await session.commit()
        payload = {"task_id": task.id, "state": task.state, "approval_state": task.approval_state}
        result = _text_result(f"Approval decision recorded for task {task.id}.", payload)
    elif tool_name == "start_development_task":
        # WK-20260830-chatgpt-entry-provider-and-delivery, issue #65: the
        # conversational entry point -- "resolve issue X of project Y" --
        # resolved to a real SubmitTaskRequest without the caller having to
        # invent an executor_id or an RFC-3339 expires_at.
        require_scope("codexbridge.task.submit")

        project_text = str(arguments["project"])
        try:
            project = await store.resolve_project_reference(session, project_text)
        except store.AmbiguousProjectReference as exc:
            candidates = ", ".join(f"{c.id} ({c.name})" for c in exc.candidates)
            raise HTTPException(status_code=409, detail=f"ambiguous_project: {candidates}")
        except ValueError:
            raise HTTPException(status_code=404, detail="unknown_project")

        if principal is not None and not principal.can_access_project(project.id):
            raise HTTPException(status_code=403, detail="project_access_denied")

        executor_id = arguments.get("executor_id")
        if executor_id:
            executor = await session.get(ExecutorModel, executor_id)
            if executor is None:
                raise HTTPException(status_code=404, detail="unknown_executor")
            allowed_projects = json.loads(executor.metadata_json).get("allowed_projects", [])
            if project.id not in allowed_projects:
                raise HTTPException(
                    status_code=409,
                    detail=(
                        f"project_not_onboarded: executor {executor_id!r} does not allow project "
                        f"{project.id!r}. Register it in both /etc/codex-bridge/registry.json (on "
                        "the gateway host) and the executor's allowed-projects.json, then restart "
                        "both processes."
                    ),
                )
        else:
            onboarded = await store.executors_allowing_project(session, project.id)
            if not onboarded:
                raise HTTPException(
                    status_code=409,
                    detail=(
                        f"project_not_onboarded: no executor allows project {project.id!r}. "
                        "Register it in both /etc/codex-bridge/registry.json (on the gateway host) "
                        "and the executor's allowed-projects.json, then restart both processes."
                    ),
                )
            connected = [item for item in onboarded if hub.is_connected(item.id)]
            executor_id = (connected[0] if connected else onboarded[0]).id

        engine_value = arguments.get("engine", "claude")
        if engine_value not in IMPLEMENTED_ENGINES:
            # Council round 1, "the second caller": without this, the gateway
            # accepted any of the six candidate engines in the tool's own
            # JSON Schema, created the task, and dispatched it -- only for
            # the executor's RunnerPool.for_engine to reject it with
            # engine_not_implemented, after already spending a dispatch
            # cycle and the executor's one concurrency slot. Refuse before
            # any of that happens.
            raise HTTPException(status_code=400, detail=f"engine_not_implemented:{engine_value}")
        mode_value = arguments.get("mode", "implement")
        allow_push = bool(arguments.get("allow_push", False))
        branch = arguments.get("branch")

        if allow_push:
            require_scope("codexbridge.task.approve")
            if principal is not None and not (principal.can_approve_sensitive or principal.is_admin()):
                raise HTTPException(status_code=403, detail="approval_not_allowed")
            if not branch:
                raise HTTPException(status_code=400, detail="branch_required_for_push")
            if not PUSHABLE_BRANCH_PATTERN.match(branch):
                raise HTTPException(status_code=400, detail="branch_not_pushable")

        issue_arg = arguments.get("issue")
        issue_ref: str | None = None
        operator_request = arguments.get("request")
        if issue_arg is not None:
            issue_ref = str(issue_arg)
            if not ISSUE_REF_PATTERN.match(issue_ref):
                raise HTTPException(status_code=400, detail="issue_ref_invalid")
            if issue_ref.startswith("gh:"):
                # GitHub issue ingestion has no owner in this codebase yet
                # (council finding F18) -- say so rather than improvising a
                # second id space.
                raise HTTPException(status_code=400, detail="issue_source_unsupported")
            if issue_ref.startswith("local:"):
                local_id = issue_ref.split(":", 1)[1]
                issue_row = await session.get(IssueModel, local_id)
                if issue_row is None or issue_row.project_id != project.id:
                    raise HTTPException(status_code=404, detail="unknown_issue")
                if not operator_request:
                    operator_request = f"Resolve issue: {issue_row.title}"
            elif not operator_request:
                # "docs:NNN"/bare NNN forms are resolved on the EXECUTOR, not
                # here -- the gateway never learns a project's real path
                # (docs/architecture.md). Only local: issues can supply a
                # title for the default objective below.
                operator_request = f"Resolve issue {issue_ref} in project {project.id}."
        if not operator_request:
            raise HTTPException(status_code=400, detail="request_or_issue_required")

        timeout_seconds = int(arguments.get("timeout_seconds", 3600))
        # Computed, never invented by the caller: submit_codex_task requires
        # an RFC-3339 expires_at the caller has to build by hand, which is
        # the single most error-prone field for an LLM caller. Generous on
        # purpose -- this bounds queueing, not execution (timeout_seconds
        # already bounds that).
        expires_at = datetime.now(timezone.utc) + timedelta(seconds=max(7200, 2 * timeout_seconds))

        delivery = (
            DeliveryRequest(branch=branch, allow_push=allow_push, base_branch=arguments.get("base_branch", "development"))
            if branch
            else None
        )

        request = SubmitTaskRequest(
            executor_id=executor_id,
            project_id=project.id,
            instruction=operator_request,
            mode=TaskMode(mode_value),
            timeout_seconds=timeout_seconds,
            priority=TaskPriority(arguments.get("priority", "normal")),
            run_when_available=bool(arguments.get("run_when_available", True)),
            expires_at=expires_at,
            engine=AgentEngine(engine_value),
            issue_ref=issue_ref,
            delivery=delivery,
        )
        task = await store.create_task(
            session,
            request,
            hub.is_connected(executor_id),
            requested_by_user_id=principal.user_id if principal else None,
            requested_by_email=principal.email if principal else None,
            can_approve_push=bool(principal is not None and (principal.can_approve_sensitive or principal.is_admin())),
        )
        task = await store.get_task(session, task.id)
        if task.state == TaskState.QUEUED.value:
            dispatch_payload = await hub.dispatch_next(task.executor_id)
            if dispatch_payload is not None:
                await hub.send(
                    task.executor_id,
                    hub_envelope(task.executor_id, "task.dispatch", dispatch_payload),
                )

        eta = await store.estimate_task_duration_seconds(
            session, project_id=project.id, mode=mode_value, engine=engine_value
        )
        payload = {
            "task_id": task.id,
            "state": task.state,
            "engine": task.engine,
            "project_id": task.project_id,
            "executor_id": task.executor_id,
            "issue_ref": task.issue_ref,
            "branch": branch,
            "allow_push": allow_push,
            "expires_at": task.expires_at.isoformat(),
            **eta,
        }
        result = _text_result(
            f"Task {task.id} created with state {task.state}, running on engine {task.engine}.", payload
        )
    elif tool_name == "list_recent_tasks":
        require_scope("codexbridge.read")
        tasks = await store.list_recent_tasks(
            session, arguments.get("limit", 20), states=arguments.get("states")
        )
        if principal is not None and not principal.is_admin():
            tasks = [task for task in tasks if task.requested_by_user_id == principal.user_id]
        payload = {
            "tasks": [
                {
                    "task_id": item.id,
                    "executor_id": item.executor_id,
                    "project_id": item.project_id,
                    "state": item.state,
                    "approval_state": item.approval_state,
                    "created_at": item.created_at.isoformat(),
                    # Additive, WK-20260830-chatgpt-entry-provider-and-delivery.
                    "engine": item.engine,
                    "branch": (json.loads(item.delivery_result_json).get("branch") if item.delivery_result_json else None),
                    "pushed": (json.loads(item.delivery_result_json).get("pushed") if item.delivery_result_json else None),
                }
                for item in tasks
            ]
        }
        result = _text_result(f"Returned {len(payload['tasks'])} tasks.", payload)
    elif tool_name == "create_epic":
        # Issue #78: exposes the same store.create_epic REST already tests
        # (gateway/app/api/routes/epics.py) over the MCP/ChatGPT transport, for
        # a project that may have no forge at all -- planning entities live in
        # this gateway's own tables, not in GitHub.
        require_action(permissions.EPICS_CREATE)
        project = await resolve_project_or_404(arguments["project"])

        idempotency_key = arguments.get("idempotency_key")
        endpoint = "mcp:create_epic"
        request_fingerprint = idempotency.fingerprint(
            json.dumps(
                {k: v for k, v in arguments.items() if k != "idempotency_key"},
                sort_keys=True, default=str,
            ).encode()
        )
        claim = None
        if idempotency_key:
            # ApiError is idempotency.py's native failure (a reused key with a
            # different body, or one still in flight) -- gateway/app/api/scope.py
            # exempts `/mcp` from the app-wide ApiError handler, so left
            # uncaught this becomes a raw 500 that breaks the JSON-RPC envelope.
            try:
                outcome = await idempotency.reserve(
                    session, key=idempotency_key, endpoint=endpoint, actor_id=principal.user_id,
                    request_fingerprint=request_fingerprint,
                )
            except ApiError as exc:
                raise HTTPException(status_code=exc.status_code, detail=exc.code) from exc
            if isinstance(outcome, idempotency.ReplayedResponse):
                result = _text_result(f"Epic {outcome.body['epic_id']} already existed.", outcome.body)
                return {"jsonrpc": "2.0", "id": rpc_id, "result": result}
            claim = outcome

        try:
            epic = await store.create_epic(
                session,
                project_id=project.id,
                title=str(arguments["title"]),
                description=arguments.get("description"),
                status=arguments.get("status"),
                actor_user_id=principal.user_id,
                actor_email=principal.email,
            )
        except IssuePlanningError as exc:
            if claim is not None:
                await idempotency.release(
                    session, key=idempotency_key, endpoint=endpoint, actor_id=principal.user_id, claim=claim
                )
            raise HTTPException(status_code=400, detail=f"validation_failed:{exc.field}:{exc.code}") from exc
        except Exception:
            if claim is not None:
                await idempotency.release(
                    session, key=idempotency_key, endpoint=endpoint, actor_id=principal.user_id, claim=claim
                )
            raise

        payload = {
            "epic_id": epic.id,
            "project_id": epic.project_id,
            "title": epic.title,
            "description": epic.description,
            "status": epic.status,
        }
        if claim is not None:
            try:
                await idempotency.complete(
                    session, key=idempotency_key, endpoint=endpoint, actor_id=principal.user_id,
                    status_code=201, body=payload, claim=claim, request_fingerprint=request_fingerprint,
                )
            except ApiError as exc:
                raise HTTPException(status_code=exc.status_code, detail=exc.code) from exc
        result = _text_result(f"Epic {epic.id} created.", payload)
    elif tool_name == "list_epics":
        require_action(permissions.EPICS_READ)
        project = await resolve_project_or_404(arguments["project"])
        limit = int(arguments.get("limit", 20))
        rows = await store.list_epics_page(
            session, project_id=project.id, status=arguments.get("status"), limit=limit + 1
        )
        has_more = len(rows) > limit
        rows = rows[:limit]
        payload = {
            "epics": [
                {
                    "epic_id": epic.id,
                    "project_id": epic.project_id,
                    "title": epic.title,
                    "description": epic.description,
                    "status": epic.status,
                }
                for epic in rows
            ],
            "has_more": has_more,
        }
        result = _text_result(f"Found {len(payload['epics'])} epics.", payload)
    elif tool_name == "create_issue":
        require_action(permissions.ISSUES_CREATE)
        project = await resolve_project_or_404(arguments["project"])

        epic_id = arguments.get("epic_id")
        if epic_id is not None:
            # Pre-checked here, distinct from the IssuePlanningError store.create_issue
            # would otherwise raise for the same condition: this is a reference the
            # caller should have gotten right by listing epics first (like an
            # unknown project or issue), not a malformed field on this request's own
            # body -- so it gets its own typed detail instead of validation_failed's
            # generic shape.
            epic_row = await store.get_epic_for_projects(session, str(epic_id), [project.id])
            if epic_row is None:
                raise HTTPException(status_code=404, detail="unknown_epic")

        idempotency_key = arguments.get("idempotency_key")
        endpoint = "mcp:create_issue"
        request_fingerprint = idempotency.fingerprint(
            json.dumps(
                {k: v for k, v in arguments.items() if k != "idempotency_key"},
                sort_keys=True, default=str,
            ).encode()
        )
        claim = None
        if idempotency_key:
            try:
                outcome = await idempotency.reserve(
                    session, key=idempotency_key, endpoint=endpoint, actor_id=principal.user_id,
                    request_fingerprint=request_fingerprint,
                )
            except ApiError as exc:
                raise HTTPException(status_code=exc.status_code, detail=exc.code) from exc
            if isinstance(outcome, idempotency.ReplayedResponse):
                result = _text_result(f"Issue {outcome.body['issue_id']} already existed.", outcome.body)
                return {"jsonrpc": "2.0", "id": rpc_id, "result": result}
            claim = outcome

        try:
            issue = await store.create_issue(
                session,
                project_id=project.id,
                epic_id=str(epic_id) if epic_id is not None else None,
                title=str(arguments["title"]),
                description=arguments.get("description"),
                status=arguments.get("status"),
                priority=arguments.get("priority"),
                labels=arguments.get("labels"),
                assignee_user_id=arguments.get("assignee_user_id"),
                assignee_email=arguments.get("assignee_email"),
                dependencies=arguments.get("dependencies"),
                blocked_reason=arguments.get("blocked_reason"),
                actor_user_id=principal.user_id,
                actor_email=principal.email,
            )
        except IssuePlanningError as exc:
            if claim is not None:
                await idempotency.release(
                    session, key=idempotency_key, endpoint=endpoint, actor_id=principal.user_id, claim=claim
                )
            raise HTTPException(status_code=400, detail=f"validation_failed:{exc.field}:{exc.code}") from exc
        except Exception:
            if claim is not None:
                await idempotency.release(
                    session, key=idempotency_key, endpoint=endpoint, actor_id=principal.user_id, claim=claim
                )
            raise

        payload = {
            "issue_id": issue.id,
            # Same shape ISSUE_REF_PATTERN (shared/protocol.py) already accepts
            # and start_development_task already resolves -- an issue created
            # in chat goes straight to execution without a second id space.
            "issue_ref": f"local:{issue.id}",
            "project_id": issue.project_id,
            "epic_id": issue.epic_id,
            "title": issue.title,
            "description": issue.description,
            "status": issue.status,
            "priority": issue.priority,
            "labels": json.loads(issue.labels_json or "[]"),
            "assignee_user_id": issue.assignee_user_id,
            "assignee_email": issue.assignee_email,
            "dependencies": json.loads(issue.dependencies_json or "[]"),
            "blocked_reason": issue.blocked_reason,
        }
        if claim is not None:
            try:
                await idempotency.complete(
                    session, key=idempotency_key, endpoint=endpoint, actor_id=principal.user_id,
                    status_code=201, body=payload, claim=claim, request_fingerprint=request_fingerprint,
                )
            except ApiError as exc:
                raise HTTPException(status_code=exc.status_code, detail=exc.code) from exc
        result = _text_result(f"Issue {issue.id} created.", payload)
    elif tool_name == "list_issues":
        require_action(permissions.ISSUES_READ)
        project = await resolve_project_or_404(arguments["project"])
        limit = int(arguments.get("limit", 20))
        rows = await store.list_issues_page(
            session,
            project_id=project.id,
            status=arguments.get("status"),
            priority=arguments.get("priority"),
            epic_id=arguments.get("epic_id"),
            assignee_user_id=arguments.get("assignee_user_id"),
            limit=limit + 1,
        )
        has_more = len(rows) > limit
        rows = rows[:limit]
        payload = {
            "issues": [
                {
                    "issue_id": issue.id,
                    "issue_ref": f"local:{issue.id}",
                    "project_id": issue.project_id,
                    "epic_id": issue.epic_id,
                    "title": issue.title,
                    "description": issue.description,
                    "status": issue.status,
                    "priority": issue.priority,
                    "labels": json.loads(issue.labels_json or "[]"),
                    "assignee_user_id": issue.assignee_user_id,
                    "assignee_email": issue.assignee_email,
                    "dependencies": json.loads(issue.dependencies_json or "[]"),
                    "blocked_reason": issue.blocked_reason,
                }
                for issue in rows
            ],
            "has_more": has_more,
        }
        result = _text_result(f"Found {len(payload['issues'])} issues.", payload)
    elif tool_name == "create_reminder":
        # WK-20260830-chatgpt-entry-provider-and-delivery, issue #71. Runs on
        # the gateway, not the executor -- see google_calendar.py's module
        # docstring for why (a reminder's whole value is a synchronous reply
        # in the same conversation, and devel3 being asleep must not mean a
        # silently queued reminder).
        require_scope("codexbridge.reminders.write")
        import httpx as _httpx

        from gateway.app.core.config import settings as _settings
        from gateway.app.services import google_calendar as _calendar

        calendar_config = _calendar.CalendarConfig(
            credentials_file=_settings.google_calendar_credentials_file or "",
            calendar_id=_settings.google_calendar_id or "",
        )
        actor = principal.email or principal.user_id if principal is not None else "unknown"
        try:
            async with _httpx.AsyncClient() as _client:
                reminder = await _calendar.create_reminder(
                    config=calendar_config,
                    client=_client,
                    user_id=actor,
                    text=arguments["text"],
                    when=arguments["when"],
                    notes=arguments.get("notes"),
                    lead_minutes=int(arguments.get("lead_minutes", 0)),
                    idempotency_key=arguments.get("idempotency_key"),
                )
        except (_calendar.CalendarConfigError, _calendar.CalendarAccessError) as exc:
            raise HTTPException(status_code=409, detail=str(exc))
        verb = "criado" if reminder["created"] else "ja existia"
        result = _text_result(
            f"Lembrete {verb} para {reminder['scheduled_for']} ({reminder['timezone']}).",
            reminder,
        )
    elif tool_name == "cancel_reminder":
        require_scope("codexbridge.reminders.write")
        import httpx as _httpx

        from gateway.app.core.config import settings as _settings
        from gateway.app.services import google_calendar as _calendar

        calendar_config = _calendar.CalendarConfig(
            credentials_file=_settings.google_calendar_credentials_file or "",
            calendar_id=_settings.google_calendar_id or "",
        )
        try:
            async with _httpx.AsyncClient() as _client:
                cancelled = await _calendar.cancel_reminder(
                    config=calendar_config, client=_client, reminder_id=arguments["reminder_id"]
                )
        except (_calendar.CalendarConfigError, _calendar.CalendarAccessError) as exc:
            raise HTTPException(status_code=409, detail=str(exc))
        result = _text_result(f"Lembrete {cancelled['reminder_id']} cancelado.", cancelled)
    else:
        raise HTTPException(status_code=404, detail=f"unknown_tool:{tool_name}")
    return {"jsonrpc": "2.0", "id": rpc_id, "result": result}
