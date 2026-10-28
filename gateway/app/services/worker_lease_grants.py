"""Transactional Worker lease grants. Callable by an authenticated operator only.

Not an HTTP API and never usable by a Worker. Every issuance transaction
takes a database write lock on the one guard row before inspecting capacity.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import uuid4

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from gateway.app.models.entities import (
    WorkerIdentityModel, WorkerLeaseSerializationModel, WorkerProjectLeaseModel,
)
from gateway.app.services.worker_leases import MAX_WINDOW, lease_is_active

MAX_PROJECTS = 3


class LeaseGrantDenied(ValueError):
    pass


async def grant_worker_lease(
    session: AsyncSession, *, worker_id: str, project_id: str, repository: str,
    control_branch: str, authorized_by: str, binding_verified: bool = False,
    now: datetime | None = None,
) -> tuple[WorkerProjectLeaseModel, bool]:
    """Issue one eight-hour lease or return an already-active one, never extend.

    binding_verified MUST come from Gateway operator authorization and
    project/repository verification. This flag is deliberately false by
    default: transport credentials cannot authorize their own leases.
    """
    if not binding_verified or not authorized_by or not authorized_by.startswith("operator:"):
        raise LeaseGrantDenied("operator and project binding authorization required")
    if not all(isinstance(v, str) and v.strip() for v in (worker_id, project_id, repository, control_branch)):
        raise LeaseGrantDenied("invalid identity or binding")
    if control_branch in {"main", "master", "development"}:
        raise LeaseGrantDenied("code branch cannot be the control branch")
    instant = now or datetime.now(timezone.utc)
    if instant.tzinfo is None or instant.utcoffset() is None:
        raise LeaseGrantDenied("clock must be timezone aware")
    instant = instant.astimezone(timezone.utc)

    # The guard UPDATE is an actual write even if no leases exist. SQLite
    # serializes writers and InnoDB/Postgres hold a row lock until commit.
    # Do not replace it with SELECT FOR UPDATE (ignored by SQLite).
    async with session.begin():
        guard = await session.execute(
            update(WorkerLeaseSerializationModel)
            .where(WorkerLeaseSerializationModel.id == 1)
            .values(generation=WorkerLeaseSerializationModel.generation + 1)
        )
        if guard.rowcount != 1:
            raise LeaseGrantDenied("lease serialization migration not applied")
        worker = await session.get(WorkerIdentityModel, worker_id)
        if worker is None or not worker.enabled or worker.revoked_at is not None:
            raise LeaseGrantDenied("worker not enabled")
        result = await session.execute(
            select(WorkerProjectLeaseModel).where(
                WorkerProjectLeaseModel.revoked_at.is_(None),
                WorkerProjectLeaseModel.expires_at > instant,
                WorkerProjectLeaseModel.enabled_at <= instant,
            )
        )
        active = result.scalars().all()
        # Any project already leased to another worker is not available.
        for lease in active:
            if lease.project_id == project_id:
                if lease_is_active(
                    lease, worker_id=worker_id, project_id=project_id,
                    repository=repository, control_branch=control_branch, now=instant,
                ):
                    return lease, False
                raise LeaseGrantDenied("project already active with another binding")
        if len({lease.project_id for lease in active}) >= MAX_PROJECTS:
            raise LeaseGrantDenied("three projects already active across Gateway")
        lease = WorkerProjectLeaseModel(
            id=str(uuid4()), worker_id=worker_id, project_id=project_id,
            repository=repository, control_branch=control_branch,
            authorized_by=authorized_by, enabled_at=instant,
            expires_at=instant + MAX_WINDOW, revoked_at=None,
        )
        session.add(lease)
        await session.flush()
        return lease, True
