"""Operator-issued, time-bounded Worker execution grants.

Separate from transport activation. No implicit privilege from GitHub or
Worker tokens, and this service never creates or dispatches a Task.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from gateway.app.models.entities import (
    WorkerExecutionGrantModel, WorkerIdentityModel, WorkerLeaseSerializationModel,
    WorkerProjectLeaseModel,
)
from gateway.app.services.worker_leases import MAX_WINDOW, lease_is_active
from shared.protocol import TaskMode

SAFE_MODES = frozenset({TaskMode.ANALYZE, TaskMode.TEST})


class ExecutionGrantDenied(ValueError):
    pass


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def grant_active(grant: WorkerExecutionGrantModel, *, now: datetime,
                 worker_id: str, project_id: str, node_id: str,
                 repository: str, mode: TaskMode) -> bool:
    """A grant never widens the Node's own capability decision."""
    try:
        return (
            grant.worker_id == worker_id and grant.project_id == project_id
            and grant.node_id == node_id and grant.repository.lower() == repository.lower()
            and grant.revoked_at is None
            and _utc(grant.enabled_at) <= _utc(now) < _utc(grant.expires_at)
            and mode.value in json.loads(grant.modes_json)
            and grant.authorized_by.startswith("operator:")
            and _utc(grant.expires_at) - _utc(grant.enabled_at) == MAX_WINDOW
        )
    except (AttributeError, TypeError, ValueError):
        return False


async def create_execution_grant(
    session: AsyncSession, *, worker_id: str, project_id: str, node_id: str,
    repository: str, modes: frozenset[TaskMode],
    authorized_by: str, operator_authorized: bool = False,
    now: datetime | None = None,
) -> tuple[WorkerExecutionGrantModel, bool]:
    """Issue exactly 8 hours without silently extending an active grant.

    All independent project, Node, workspace and capability checks MUST be
    completed by the trusted Gateway route before operator_authorized=True.
    """
    if not operator_authorized or not authorized_by.startswith("operator:"):
        raise ExecutionGrantDenied("explicit human operator authorization required")
    if not modes or not modes.issubset(SAFE_MODES):
        raise ExecutionGrantDenied("only analyze and test may be preauthorized")
    instant = _utc(now or datetime.now(timezone.utc))
    if not all((worker_id, project_id, node_id, repository)):
        raise ExecutionGrantDenied("missing binding")
    async with session.begin():
        guard = await session.execute(
            update(WorkerLeaseSerializationModel)
            .where(WorkerLeaseSerializationModel.id == 1)
            .values(generation=WorkerLeaseSerializationModel.generation + 1))
        if guard.rowcount != 1:
            raise ExecutionGrantDenied("authorization serialization unavailable")
        worker = await session.get(WorkerIdentityModel, worker_id)
        if worker is None or not worker.enabled or worker.revoked_at is not None:
            raise ExecutionGrantDenied("worker disabled or revoked")
        leases = (await session.execute(
            select(WorkerProjectLeaseModel).where(
                WorkerProjectLeaseModel.worker_id == worker_id,
                WorkerProjectLeaseModel.project_id == project_id,
                WorkerProjectLeaseModel.revoked_at.is_(None))
        )).scalars().all()
        if not any(lease_is_active(lease, worker_id=worker_id,
                                   project_id=project_id, repository=repository,
                                   control_branch=lease.control_branch, now=instant)
                   for lease in leases):
            raise ExecutionGrantDenied("active intake lease required")
        prior = (await session.execute(
            select(WorkerExecutionGrantModel).where(
                WorkerExecutionGrantModel.worker_id == worker_id,
                WorkerExecutionGrantModel.project_id == project_id,
                WorkerExecutionGrantModel.node_id == node_id,
                WorkerExecutionGrantModel.revoked_at.is_(None))
        )).scalars().all()
        for grant in prior:
            if _utc(grant.enabled_at) <= instant < _utc(grant.expires_at):
                if (grant.repository.lower() == repository.lower()
                        and set(json.loads(grant.modes_json)) == {x.value for x in modes}):
                    return grant, False
                raise ExecutionGrantDenied("active scope differs; revoke before replacing")
        grant = WorkerExecutionGrantModel(
            id=str(uuid4()), worker_id=worker_id, project_id=project_id,
            node_id=node_id, repository=repository,
            modes_json=json.dumps(sorted(x.value for x in modes)),
            authorized_by=authorized_by, enabled_at=instant,
            expires_at=instant + MAX_WINDOW, revoked_at=None)
        session.add(grant)
        await session.flush()
        return grant, True


async def revoke_execution_grant(
    session: AsyncSession, *, grant_id: str, now: datetime | None = None,
) -> bool:
    """Revocation blocks future starts; in-flight cancellation is future work."""
    instant = _utc(now or datetime.now(timezone.utc))
    async with session.begin():
        guard = await session.execute(
            update(WorkerLeaseSerializationModel)
            .where(WorkerLeaseSerializationModel.id == 1)
            .values(generation=WorkerLeaseSerializationModel.generation + 1))
        if guard.rowcount != 1:
            raise ExecutionGrantDenied("authorization serialization unavailable")
        row = await session.get(WorkerExecutionGrantModel, grant_id)
        if row is None or row.revoked_at is not None:
            return False
        row.revoked_at = instant
        await session.flush()
        return True
