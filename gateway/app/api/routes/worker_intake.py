"""Authenticated Worker transport intake. No execution or dispatch."""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Header
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from gateway.app.api.errors import ApiError, UNAUTHENTICATED, PERMISSION_DENIED, VALIDATION_FAILED, CONFLICT
from gateway.app.db.session import get_session
from gateway.app.models.entities import WorkerProjectLeaseModel
from gateway.app.services.worker_admission import (
    WorkerAdmissionError, authenticated_worker, record_admission,
)
from gateway.app.services.worker_leases import lease_is_active
from scripts.worker_request import InvalidControlRequest, validate_envelope

router = APIRouter(prefix="/control/worker-intake", tags=["worker-intake"])


class IntakeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    repository: str = Field(min_length=3, max_length=255)
    controlBranch: str = Field(min_length=1, max_length=128)
    envelope: dict


@router.post("/requests", status_code=202)
async def intake_request(
    body: IntakeRequest,
    x_worker_token: str | None = Header(default=None, alias="X-Worker-Token"),
    session: AsyncSession = Depends(get_session),
) -> dict:
    worker = await authenticated_worker(session, x_worker_token)
    if worker is None:
        raise ApiError(status_code=401, code=UNAUTHENTICATED, message="Worker authentication required.")
    try:
        envelope = validate_envelope(body.envelope, activated_project=body.envelope.get("project"))
    except (InvalidControlRequest, TypeError, ValueError) as exc:
        raise ApiError(status_code=422, code=VALIDATION_FAILED, message="Invalid control request envelope.") from exc

    # This is an authorization LOOKUP, never lease issuance. Every request
    # must find a currently valid, human-authorized Gateway lease.
    rows = await session.execute(
        select(WorkerProjectLeaseModel).where(
            WorkerProjectLeaseModel.worker_id == worker.id,
            WorkerProjectLeaseModel.project_id == envelope["project"],
            WorkerProjectLeaseModel.repository == body.repository,
            WorkerProjectLeaseModel.control_branch == body.controlBranch,
            WorkerProjectLeaseModel.revoked_at.is_(None),
        )
    )
    now = datetime.now(timezone.utc)
    allowed = any(
        lease_is_active(
            lease, worker_id=worker.id, project_id=envelope["project"],
            repository=body.repository, control_branch=body.controlBranch, now=now,
        ) for lease in rows.scalars()
    )
    worker_id = worker.id
    # SQLAlchemy session.get/execute starts an implicit transaction; the
    # admission service owns its own transaction.
    await session.rollback()
    if not allowed:
        raise ApiError(status_code=403, code=PERMISSION_DENIED,
                       message="No active Gateway-approved Worker project lease.")
    try:
        # The DB identity was verified before the rollback. Pass its ID in a
        # transport-only object to avoid accessing expired ORM attributes.
        from types import SimpleNamespace
        row, created = await record_admission(
            session, worker=SimpleNamespace(id=worker_id), envelope=envelope,
            project_allowed=True,
        )
    except WorkerAdmissionError as exc:
        raise ApiError(status_code=409, code=CONFLICT, message="Request ID collision or admission conflict.") from exc
    return {"requestId": row.request_id, "projectId": row.project_id,
            "state": row.state, "created": created}
