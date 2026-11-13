"""Atomic, non-executing correlation of admitted Worker requests.

This service reserves one immutable correlation key. It deliberately does not
create Missions, Tasks, or dispatch messages. Source-forge verification,
binding checks, and task creation belong to the subsequent dispatch gate.
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from gateway.app.models.entities import (
    WorkerExecutionGrantModel, WorkerLeaseSerializationModel,
    WorkerMissionCorrelationModel, WorkerRequestModel,
)
from gateway.app.services.worker_execution_grants import grant_active
from shared.protocol import TaskMode


class CorrelationDenied(ValueError):
    pass


async def reserve_worker_correlation(
    session: AsyncSession, *, project_id: str, request_id: str,
    worker_id: str, payload_sha256: str, source_commit: str,
    grant_id: str, node_id: str, repository: str, mode: TaskMode,
    now: datetime | None = None,
) -> tuple[WorkerMissionCorrelationModel, bool]:
    """Return the original reservation on exact replay, never a new identity.

    This is a reservation, not a dispatch authorization. Replays remain
    readable after grant expiry/revocation but MUST NOT start execution.
    """
    if mode not in (TaskMode.ANALYZE, TaskMode.TEST):
        raise CorrelationDenied("unsupported operation")
    if not all((project_id, request_id, worker_id, payload_sha256,
                source_commit, grant_id, node_id, repository)):
        raise CorrelationDenied("incomplete correlation scope")
    if len(payload_sha256) != 64 or len(source_commit) != 40:
        raise CorrelationDenied("invalid immutable digest")
    instant = now or datetime.now(timezone.utc)
    async with session.begin():
        guard = await session.execute(
            update(WorkerLeaseSerializationModel)
            .where(WorkerLeaseSerializationModel.id == 1)
            .values(generation=WorkerLeaseSerializationModel.generation + 1)
        )
        if guard.rowcount != 1:
            raise CorrelationDenied("serialization unavailable")

        admission = await session.get(WorkerRequestModel, (project_id, request_id))
        if admission is None or admission.state != "admitted":
            raise CorrelationDenied("request not admitted")
        if (admission.worker_id != worker_id
                or admission.payload_sha256 != payload_sha256
                or admission.source_commit.lower() != source_commit.lower()
                or admission.operation != mode.value):
            raise CorrelationDenied("admission identity mismatch")

        existing = await session.get(
            WorkerMissionCorrelationModel, (project_id, request_id)
        )
        if existing is not None:
            if (existing.worker_id != worker_id
                    or existing.payload_sha256 != payload_sha256
                    or existing.source_commit.lower() != source_commit.lower()
                    or existing.grant_id != grant_id
                    or existing.node_id != node_id
                    or existing.repository.lower() != repository.lower()
                    or existing.mode != mode.value):
                raise CorrelationDenied("request already reserved for a different scope")
            return existing, False

        grant = await session.get(WorkerExecutionGrantModel, grant_id)
        if grant is None or not grant_active(
            grant, now=instant, worker_id=worker_id,
            project_id=project_id, node_id=node_id,
            repository=repository, mode=mode,
        ):
            raise CorrelationDenied("active execution grant required")

        reservation = WorkerMissionCorrelationModel(
            project_id=project_id, request_id=request_id, worker_id=worker_id,
            payload_sha256=payload_sha256, source_commit=source_commit.lower(),
            grant_id=grant_id, node_id=node_id, repository=repository,
            mode=mode.value, state="reserved", mission_id=None, task_id=None,
            created_at=instant,
        )
        session.add(reservation)
        await session.flush()
        return reservation, True
