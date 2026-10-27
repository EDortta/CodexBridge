"""Worker credential verification and atomic transport admission.

A transport admission is NOT a task dispatch or an authorization grant.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from gateway.app.models.entities import WorkerIdentityModel, WorkerRequestModel
from shared.security import hash_token


class WorkerAdmissionError(ValueError):
    pass


async def authenticated_worker(session: AsyncSession, token: str | None) -> WorkerIdentityModel | None:
    """Disabled/revoked/unknown credentials are indistinguishable."""
    if not token or len(token) < 32 or len(token) > 4096:
        return None
    result = await session.execute(
        select(WorkerIdentityModel).where(WorkerIdentityModel.token_hash == hash_token(token))
    )
    worker = result.scalar_one_or_none()
    if worker is None or not worker.enabled or worker.revoked_at is not None:
        return None
    return worker


def canonical_digest(envelope: dict) -> str:
    return hashlib.sha256(
        json.dumps(envelope, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    ).hexdigest()


async def record_admission(
    session: AsyncSession, *, worker: WorkerIdentityModel, envelope: dict,
    project_allowed: bool = False,
) -> tuple[WorkerRequestModel, bool]:
    """Fail closed without an independent Gateway project/lease decision.

    A unique database PK controls races between multiple pollers. A replay
    with an altered payload is an error, never a second attempt.
    """
    if not project_allowed:
        raise WorkerAdmissionError("Gateway project and lease authorization required")
    project, request_id = envelope["project"], envelope["requestId"]
    digest = canonical_digest(envelope)
    existing = await session.get(WorkerRequestModel, (project, request_id))
    if existing is not None:
        if existing.payload_sha256 != digest:
            raise WorkerAdmissionError("request ID reused with different content")
        return existing, False
    row = WorkerRequestModel(
        project_id=project, request_id=request_id, worker_id=worker.id,
        payload_sha256=digest, source_commit=envelope["source"]["commit"],
        operation=envelope["operation"], state="admitted",
        received_at=datetime.now(timezone.utc),
    )
    try:
        async with session.begin_nested():
            session.add(row)
            await session.flush()
    except IntegrityError:
        # Raced with another transaction. Never dispatch on this path.
        other = await session.get(WorkerRequestModel, (project, request_id))
        if other is None or other.payload_sha256 != digest:
            raise WorkerAdmissionError("concurrent admission conflict")
        return other, False
    await session.commit()
    return row, True
