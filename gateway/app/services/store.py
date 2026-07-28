from __future__ import annotations

import json
from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from gateway.app.models.entities import (
    ExecutorModel,
    MessageReceiptModel,
    ProjectModel,
    TaskLogModel,
    TaskModel,
)
from gateway.app.services.audit import record_event
from shared.policy import evaluate_task_policy
from shared.protocol import (
    ExecutorRegistration,
    ProjectRegistration,
    SubmitTaskRequest,
    TaskState,
)


async def upsert_registry(
    session: AsyncSession,
    executors: list[ExecutorRegistration],
    projects: list[ProjectRegistration],
) -> None:
    for executor in executors:
        current = await session.get(ExecutorModel, executor.executor_id)
        metadata_json = json.dumps(executor.model_dump(mode="json"), ensure_ascii=True)
        if current is None:
            session.add(
                ExecutorModel(
                    id=executor.executor_id,
                    display_name=executor.display_name,
                    enabled=executor.enabled,
                    connected=False,
                    metadata_json=metadata_json,
                )
            )
        else:
            current.display_name = executor.display_name
            current.enabled = executor.enabled
            current.metadata_json = metadata_json
    for project in projects:
        current = await session.get(ProjectModel, project.project_id)
        config_json = json.dumps(project.model_dump(mode="json"), ensure_ascii=True)
        if current is None:
            session.add(
                ProjectModel(
                    id=project.project_id,
                    name=project.name,
                    path=project.path,
                    enabled=project.enabled,
                    config_json=config_json,
                )
            )
        else:
            current.name = project.name
            current.path = project.path
            current.enabled = project.enabled
            current.config_json = config_json
    await session.commit()


async def list_executors(session: AsyncSession) -> list[ExecutorModel]:
    result = await session.execute(select(ExecutorModel).order_by(ExecutorModel.id))
    return list(result.scalars())


async def list_projects(session: AsyncSession) -> list[ProjectModel]:
    result = await session.execute(select(ProjectModel).order_by(ProjectModel.id))
    return list(result.scalars())


async def list_projects_for_executor(session: AsyncSession, executor_id: str) -> list[ProjectModel]:
    executor = await session.get(ExecutorModel, executor_id)
    if executor is None:
        raise ValueError("unknown_executor")
    metadata = json.loads(executor.metadata_json)
    allowed = metadata.get("allowed_projects", [])
    if not allowed:
        return []
    result = await session.execute(select(ProjectModel).where(ProjectModel.id.in_(allowed)).order_by(ProjectModel.id))
    return list(result.scalars())


async def get_task(session: AsyncSession, task_id: str) -> TaskModel | None:
    return await session.get(TaskModel, task_id)


async def list_recent_tasks(session: AsyncSession, limit: int = 20) -> list[TaskModel]:
    result = await session.execute(select(TaskModel).order_by(TaskModel.created_at.desc()).limit(limit))
    return list(result.scalars())


async def create_task(
    session: AsyncSession,
    request: SubmitTaskRequest,
    executor_online: bool,
    continue_session_id: str | None = None,
) -> TaskModel:
    executor = await session.get(ExecutorModel, request.executor_id)
    if executor is None or not executor.enabled:
        raise ValueError("unknown_or_disabled_executor")
    project = await session.get(ProjectModel, request.project_id)
    if project is None or not project.enabled:
        raise ValueError("unknown_or_disabled_project")
    executor_metadata = json.loads(executor.metadata_json)
    if request.project_id not in executor_metadata.get("allowed_projects", []):
        raise ValueError("project_not_allowed_for_executor")
    project_config = json.loads(project.config_json)
    if request.mode.value not in project_config.get("allowed_modes", []):
        raise ValueError("mode_not_allowed_for_project")
    if request.timeout_seconds > int(project_config.get("max_timeout_seconds", request.timeout_seconds)):
        raise ValueError("timeout_exceeds_project_limit")
    policy = evaluate_task_policy(request)
    state = TaskState.QUEUED if executor_online else TaskState.WAITING_EXECUTOR
    if not executor_online and not request.run_when_available:
        raise ValueError("executor_offline")
    if request.expires_at <= datetime.now(timezone.utc):
        raise ValueError("task_already_expired")
    if not policy.approved:
        state = TaskState.AWAITING_APPROVAL
    task = TaskModel(
        id=str(uuid4()),
        executor_id=request.executor_id,
        project_id=request.project_id,
        instruction=request.instruction,
        mode=request.mode.value,
        state=state.value,
        priority=request.priority.value,
        run_when_available=request.run_when_available,
        expires_at=request.expires_at,
        timeout_seconds=request.timeout_seconds,
        created_at=datetime.now(timezone.utc),
        correlation_id=str(uuid4()),
        session_id=continue_session_id,
    )
    session.add(task)
    await record_event(session, "task", task.id, "task.created", {"state": task.state, "policy_level": policy.level.value})
    await session.commit()
    await session.refresh(task)
    return task


async def mark_executor_connected(session: AsyncSession, executor_id: str, connected: bool) -> None:
    executor = await session.get(ExecutorModel, executor_id)
    if executor is None:
        raise ValueError("unknown_executor")
    executor.connected = connected
    executor.last_seen_at = datetime.now(timezone.utc)
    await session.commit()


async def next_dispatchable_task(session: AsyncSession, executor_id: str) -> TaskModel | None:
    now = datetime.now(timezone.utc)
    result = await session.execute(
        select(TaskModel)
        .where(TaskModel.executor_id == executor_id)
        .where(TaskModel.state.in_([TaskState.QUEUED.value, TaskState.WAITING_EXECUTOR.value]))
        .where(TaskModel.expires_at > now)
        .order_by(TaskModel.created_at.asc())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def update_task_state(session: AsyncSession, task_id: str, state: TaskState, error: str | None = None) -> TaskModel:
    task = await session.get(TaskModel, task_id)
    if task is None:
        raise ValueError("unknown_task")
    task.state = state.value
    if state == TaskState.RUNNING:
        task.started_at = datetime.now(timezone.utc)
    if state in {TaskState.COMPLETED, TaskState.FAILED, TaskState.CANCELLED, TaskState.EXPIRED, TaskState.LOST}:
        task.completed_at = datetime.now(timezone.utc)
    if error:
        task.last_error = error
    await record_event(session, "task", task.id, "task.state_changed", {"state": task.state, "error": error})
    await session.commit()
    await session.refresh(task)
    return task


async def append_log(session: AsyncSession, task_id: str, offset: int, stream: str, line: str) -> None:
    session.add(
        TaskLogModel(
            task_id=task_id,
            offset=offset,
            stream=stream,
            line=line,
            created_at=datetime.now(timezone.utc),
        )
    )
    await session.commit()


async def get_logs(session: AsyncSession, task_id: str, offset: int = 0, limit: int = 500) -> list[TaskLogModel]:
    result = await session.execute(
        select(TaskLogModel)
        .where(TaskLogModel.task_id == task_id)
        .where(TaskLogModel.offset >= offset)
        .order_by(TaskLogModel.offset.asc())
        .limit(limit)
    )
    return list(result.scalars())


async def store_result(session: AsyncSession, task_id: str, result: dict, final_state: TaskState) -> TaskModel:
    task = await session.get(TaskModel, task_id)
    if task is None:
        raise ValueError("unknown_task")
    task.result_json = json.dumps(result, ensure_ascii=True)
    task.command_json = json.dumps(result.get("command", []), ensure_ascii=True)
    task.session_id = result.get("codex_session_id")
    task.state = final_state.value
    task.completed_at = datetime.now(timezone.utc)
    await record_event(session, "task", task.id, "task.result", {"state": task.state})
    await session.commit()
    await session.refresh(task)
    return task


async def store_message_receipt(session: AsyncSession, message_id: str, executor_id: str, message_type: str) -> bool:
    current = await session.get(MessageReceiptModel, message_id)
    if current is not None:
        return False
    session.add(
        MessageReceiptModel(
            message_id=message_id,
            executor_id=executor_id,
            message_type=message_type,
            created_at=datetime.now(timezone.utc),
        )
    )
    await session.commit()
    return True
