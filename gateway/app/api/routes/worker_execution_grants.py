"""Human-only preauthorization for Worker dispatch, independent from intake."""
from __future__ import annotations

import json

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from gateway.app.api import permissions, timestamps
from gateway.app.api.auth import require_action
from gateway.app.api.errors import ApiError, PERMISSION_DENIED, NOT_FOUND, CONFLICT, VALIDATION_FAILED
from gateway.app.core.users import AuthenticatedPrincipal
from gateway.app.db.session import get_session
from gateway.app.models.entities import ExecutorModel, NodeModel, ProjectModel, WorkerExecutionGrantModel
from gateway.app.services import store
from gateway.app.services.worker_execution_grants import (
    ExecutionGrantDenied, SAFE_MODES, create_execution_grant, revoke_execution_grant,
)
from shared.protocol import TaskMode

router = APIRouter(prefix="/control/worker-execution-grants", tags=["worker-execution-grants"])


class ExecutionGrantRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)
    worker_id: str = Field(alias="workerId", min_length=1, max_length=128)
    project_id: str = Field(alias="projectId", min_length=1, max_length=128)
    node_id: str = Field(alias="nodeId", min_length=1, max_length=128)
    repository: str = Field(min_length=3, max_length=255)
    modes: list[TaskMode] = Field(min_length=1, max_length=2)


def _human_admin(principal: AuthenticatedPrincipal) -> None:
    if "admin" not in principal.roles:
        raise ApiError(status_code=403, code=PERMISSION_DENIED,
                       message="Human admin role required.")


def _dto(row: WorkerExecutionGrantModel, *, created: bool | None = None) -> dict:
    result = {
        "grantId": row.id, "workerId": row.worker_id,
        "projectId": row.project_id, "nodeId": row.node_id,
        "repository": row.repository, "modes": json.loads(row.modes_json),
        "authorizedBy": row.authorized_by,
        "enabledAt": timestamps.utc_z(row.enabled_at),
        "expiresAt": timestamps.utc_z(row.expires_at),
        "revokedAt": timestamps.utc_z(row.revoked_at),
    }
    if created is not None:
        result["created"] = created
    return result


@router.post("", status_code=201)
async def authorize_worker_execution(
    payload: ExecutionGrantRequest,
    principal: AuthenticatedPrincipal = Depends(require_action(permissions.NODES_AUTHORIZATIONS_MANAGE)),
    session: AsyncSession = Depends(get_session),
) -> dict:
    _human_admin(principal)
    requested = frozenset(payload.modes)
    if len(requested) != len(payload.modes) or not requested.issubset(SAFE_MODES):
        raise ApiError(status_code=422, code=VALIDATION_FAILED,
                       message="Only distinct analyze/test modes are supported.")
    project = await session.get(ProjectModel, payload.project_id)
    node = await session.get(NodeModel, payload.node_id)
    if project is None or not project.enabled or node is None or not node.enabled or node.admission_state != "enrolled":
        raise ApiError(status_code=404, code=NOT_FOUND, message="Enabled project and Node required.")
    try:
        project_config = json.loads(project.config_json or "{}")
    except (TypeError, ValueError):
        project_config = {}
    bound = project_config.get("worker_repository")
    if not isinstance(bound, str) or bound.lower() != payload.repository.lower():
        raise ApiError(status_code=403, code=PERMISSION_DENIED,
                       message="Repository is not bound by operator to this project.")

    executors = (await session.execute(select(ExecutorModel).where(
        ExecutorModel.node_id == payload.node_id, ExecutorModel.enabled.is_(True)))).scalars().all()
    if len(executors) != 1:
        raise ApiError(status_code=409, code=CONFLICT,
                       message="Node must have exactly one enabled Executor.")
    executor = executors[0]
    try:
        for mode in requested:
            await store.require_active_node_project_authorization(session, executor, project, mode)
            if mode not in await store.effective_task_modes(session, executor, project):
                raise ValueError("mode_exceeds_project_policy")
    except (ValueError, KeyError) as exc:
        raise ApiError(status_code=403, code=PERMISSION_DENIED,
                       message="Active workspace binding and permitted capability required.") from exc

    # Read-only checks above begin a transaction; the serialized service owns the write.
    await session.rollback()
    try:
        grant, created = await create_execution_grant(
            session, worker_id=payload.worker_id, project_id=payload.project_id,
            node_id=payload.node_id, repository=bound, modes=requested,
            authorized_by="operator:" + principal.user_id,
            operator_authorized=True)
    except ExecutionGrantDenied as exc:
        raise ApiError(status_code=409, code=CONFLICT, message=str(exc)) from exc
    return _dto(grant, created=created)


@router.post("/{grant_id}/revoke")
async def revoke_worker_execution(
    grant_id: str,
    principal: AuthenticatedPrincipal = Depends(require_action(permissions.NODES_AUTHORIZATIONS_MANAGE)),
    session: AsyncSession = Depends(get_session),
) -> dict:
    _human_admin(principal)
    # Revoke is intentionally idempotent; no Caller can extend a grant.
    try:
        revoked = await revoke_execution_grant(session, grant_id=grant_id)
    except ExecutionGrantDenied as exc:
        raise ApiError(status_code=409, code=CONFLICT, message=str(exc)) from exc
    return {"grantId": grant_id, "revoked": revoked}
