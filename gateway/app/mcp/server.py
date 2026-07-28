from __future__ import annotations

import json
from datetime import datetime, timezone
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from gateway.app.models.entities import ExecutorModel
from gateway.app.services import store
from gateway.app.services.agent_hub import AgentHub
from gateway.app.mcp.tools import tool_definitions
from shared.protocol import (
    AgentEnvelope,
    AgentMessageType,
    ApprovalDecision,
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


async def handle_mcp_call(body: dict, session: AsyncSession, hub: AgentHub) -> dict:
    method = body.get("method")
    rpc_id = body.get("id")
    if method == "initialize":
        return {
            "jsonrpc": "2.0",
            "id": rpc_id,
            "result": {
                "protocolVersion": "2025-06-18",
                "serverInfo": {"name": "codex-bridge", "version": "0.1.0"},
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

    if tool_name == "list_executors":
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
        items = await store.list_projects_for_executor(session, arguments["executor_id"])
        payload = {
            "projects": [
                {"project_id": item.id, "name": item.name, "enabled": item.enabled}
                for item in items
            ]
        }
        result = _text_result(f"Found {len(payload['projects'])} projects.", payload)
    elif tool_name == "submit_codex_task":
        request = SubmitTaskRequest.model_validate(arguments)
        task = await store.create_task(session, request, hub.is_connected(request.executor_id))
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
        task = await store.get_task(session, arguments["task_id"])
        if task is None:
            raise HTTPException(status_code=404, detail="unknown_task")
        payload = {
            "task_id": task.id,
            "state": task.state,
            "executor_id": task.executor_id,
            "project_id": task.project_id,
            "started_at": task.started_at.isoformat() if task.started_at else None,
            "completed_at": task.completed_at.isoformat() if task.completed_at else None,
            "last_error": task.last_error,
            "session_id": task.session_id,
        }
        result = _text_result(f"Task {task.id} is {task.state}.", payload)
    elif tool_name == "get_task_logs":
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
        task = await store.get_task(session, arguments["task_id"])
        if task is None:
            raise HTTPException(status_code=404, detail="unknown_task")
        payload = json.loads(task.result_json or "{}")
        payload["task_id"] = task.id
        payload["state"] = task.state
        result = _text_result(f"Loaded result for task {task.id}.", payload)
    elif tool_name == "continue_codex_session":
        parent = await store.get_task(session, arguments["task_id"])
        if parent is None:
            raise HTTPException(status_code=404, detail="unknown_task")
        request = SubmitTaskRequest(
            executor_id=parent.executor_id,
            project_id=parent.project_id,
            instruction=arguments["instruction"],
            mode=TaskMode(parent.mode),
            timeout_seconds=arguments["timeout_seconds"],
            priority=TaskPriority(parent.priority),
            run_when_available=True,
            expires_at=parent.expires_at,
        )
        task = await store.create_task(
            session,
            request,
            hub.is_connected(parent.executor_id),
            continue_session_id=parent.session_id,
        )
        payload = {"task_id": task.id, "state": task.state, "continued_from_task_id": parent.id}
        result = _text_result(f"Continuation task {task.id} created.", payload)
    elif tool_name == "cancel_codex_task":
        task = await store.get_task(session, arguments["task_id"])
        if task is None:
            raise HTTPException(status_code=404, detail="unknown_task")
        if task.state in {TaskState.QUEUED.value, TaskState.WAITING_EXECUTOR.value, TaskState.AWAITING_APPROVAL.value}:
            task = await store.update_task_state(session, task.id, TaskState.CANCELLED)
        elif task.state == TaskState.RUNNING.value and hub.is_connected(task.executor_id):
            await hub.send(task.executor_id, hub_envelope(task.executor_id, "task.cancel", {"task_id": task.id}))
        payload = {"task_id": task.id, "state": task.state}
        result = _text_result(f"Cancellation requested for task {task.id}.", payload)
    elif tool_name == "approve_codex_task":
        task = await store.decide_task_approval(
            session,
            arguments["task_id"],
            ApprovalDecision(arguments["decision"]),
            arguments.get("reason"),
        )
        if task.state in {TaskState.QUEUED.value, TaskState.WAITING_EXECUTOR.value} and hub.is_connected(task.executor_id):
            dispatch_payload = await hub.dispatch_next(task.executor_id)
            if dispatch_payload is not None:
                await hub.send(task.executor_id, hub_envelope(task.executor_id, "task.dispatch", dispatch_payload))
        payload = {"task_id": task.id, "state": task.state, "approval_state": task.approval_state}
        result = _text_result(f"Approval decision recorded for task {task.id}.", payload)
    elif tool_name == "list_recent_tasks":
        tasks = await store.list_recent_tasks(session, arguments.get("limit", 20))
        payload = {
            "tasks": [
                {
                    "task_id": item.id,
                    "executor_id": item.executor_id,
                    "project_id": item.project_id,
                    "state": item.state,
                    "approval_state": item.approval_state,
                    "created_at": item.created_at.isoformat(),
                }
                for item in tasks
            ]
        }
        result = _text_result(f"Returned {len(payload['tasks'])} tasks.", payload)
    else:
        raise HTTPException(status_code=404, detail=f"unknown_tool:{tool_name}")
    return {"jsonrpc": "2.0", "id": rpc_id, "result": result}


def hub_envelope(executor_id: str, message_type: str, payload: dict) -> AgentEnvelope:
    return AgentEnvelope(
        message_id=str(uuid4()),
        executor_id=executor_id,
        sent_at=datetime.now(timezone.utc),
        type=AgentMessageType(message_type),
        payload=payload,
    )
