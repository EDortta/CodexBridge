"""Operator-only Worker activation API, separate from the mobile API.

The GitHub repository identity MUST be preconfigured on ProjectModel and
must match the requested repository. A Worker cannot invoke this with its
machine token.
"""
from __future__ import annotations

import json
import re

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from gateway.app.api import permissions, timestamps
from gateway.app.api.auth import require_action
from gateway.app.api.errors import NOT_FOUND, PERMISSION_DENIED, VALIDATION_FAILED, ApiError
from gateway.app.core.users import AuthenticatedPrincipal
from gateway.app.db.session import get_session
from gateway.app.models.entities import ProjectModel
from gateway.app.services.worker_lease_grants import LeaseGrantDenied, grant_worker_lease

router = APIRouter(prefix="/control/workers", tags=["worker-activation"])
_REPO = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,99}/[A-Za-z0-9][A-Za-z0-9._-]{0,99}\Z")
_BRANCH = re.compile(r"[A-Za-z0-9][A-Za-z0-9._/-]{0,127}\Z")


class ActivateWorkerProject(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)
    project_id: str = Field(alias="projectId", min_length=1, max_length=128)
    repository: str = Field(min_length=3, max_length=201)
    control_branch: str = Field(default="codexbridge-control", alias="controlBranch")


@router.post("/{worker_id}/activate")
async def activate(
    worker_id: str,
    payload: ActivateWorkerProject,
    principal: AuthenticatedPrincipal = Depends(require_action(permissions.NODES_AUTHORIZATIONS_MANAGE)),
    session: AsyncSession = Depends(get_session),
) -> dict:
    # A machine credential is not a human admin. Require an actual admin
    # role, not just a bearer token carrying a wide administrative scope.
    if "admin" not in principal.roles:
        raise ApiError(status_code=403, code=PERMISSION_DENIED, message="Admin role required.")
    if not _REPO.fullmatch(payload.repository) or not _BRANCH.fullmatch(payload.control_branch):
        raise ApiError(status_code=422, code=VALIDATION_FAILED, message="Invalid repository or branch.")
    project = await session.get(ProjectModel, payload.project_id)
    if project is None or not project.enabled:
        raise ApiError(status_code=404, code=NOT_FOUND, message="Project is not registered and enabled.")
    try:
        config = json.loads(project.config_json or "{}")
    except (TypeError, ValueError):
        config = {}
    # Explicit operator-created forge binding required: do not infer repository
    # from the submitted payload or a local checkout path.
    bound_repository = config.get("worker_repository") if isinstance(config, dict) else None
    if not isinstance(bound_repository, str) or bound_repository.lower() != payload.repository.lower():
        raise ApiError(status_code=403, code=PERMISSION_DENIED,
                       message="Project has no matching Gateway-side worker repository binding.")
    # session.get opened an implicit read transaction. The grant service owns
    # its write transaction and serialization lock; close the read first.
    await session.rollback()
    try:
        lease, created = await grant_worker_lease(
            session, worker_id=worker_id, project_id=project.id,
            repository=bound_repository, control_branch=payload.control_branch,
            authorized_by="operator:" + principal.user_id, binding_verified=True,
        )
    except LeaseGrantDenied as exc:
        raise ApiError(status_code=409, code="conflict", message=str(exc)) from exc
    return {"leaseId": lease.id, "workerId": lease.worker_id,
            "projectId": lease.project_id, "repository": lease.repository,
            "controlBranch": lease.control_branch,
            "enabledAt": timestamps.utc_z(lease.enabled_at),
            "expiresAt": timestamps.utc_z(lease.expires_at), "created": created}
