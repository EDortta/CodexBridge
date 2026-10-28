"""Database-backed Worker lease grant tests (not a mock of the capacity gate)."""
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from gateway.app.models.entities import (
    WorkerIdentityModel, WorkerLeaseSerializationModel, WorkerProjectLeaseModel,
)
from gateway.app.services.worker_lease_grants import LeaseGrantDenied, grant_worker_lease


@pytest.fixture
async def maker(tmp_path):
    engine = create_async_engine("sqlite+aiosqlite:///" + str(tmp_path / "leases.db"))
    async with engine.begin() as conn:
        await conn.run_sync(lambda c: WorkerIdentityModel.__table__.create(c))
        await conn.run_sync(lambda c: WorkerLeaseSerializationModel.__table__.create(c))
        await conn.run_sync(lambda c: WorkerProjectLeaseModel.__table__.create(c))
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as db:
        async with db.begin():
            db.add(WorkerLeaseSerializationModel(id=1, generation=0))
            db.add(WorkerIdentityModel(id="w1", token_hash="z" * 64,
                                       enabled=True, created_at=datetime.now(timezone.utc)))
    yield factory
    await engine.dispose()


async def grant(factory, project, **opts):
    async with factory() as db:
        return await grant_worker_lease(
            db, worker_id="w1", project_id=project, repository="owner/" + project,
            control_branch="codexbridge-control", authorized_by="operator:admin",
            binding_verified=True, now=datetime(2026, 10, 27, 12, tzinfo=timezone.utc),
            **opts
        )


@pytest.mark.asyncio
async def test_requires_independent_operator_authorization(maker):
    async with maker() as db:
        with pytest.raises(LeaseGrantDenied, match="authorization required"):
            await grant_worker_lease(db, worker_id="w1", project_id="a",
                                     repository="owner/a", control_branch="codexbridge-control",
                                     authorized_by="operator:admin")


@pytest.mark.asyncio
async def test_cap_is_global_for_distinct_projects(maker):
    for project in ("a", "b", "c"):
        lease, created = await grant(maker, project)
        assert created
        assert lease.expires_at - lease.enabled_at == timedelta(hours=8)
    with pytest.raises(LeaseGrantDenied, match="three projects"):
        await grant(maker, "d")


@pytest.mark.asyncio
async def test_rollback_does_not_consume_slot(maker):
    async with maker() as db:
        with pytest.raises(LeaseGrantDenied):
            await grant_worker_lease(
                db, worker_id="not-enrolled", project_id="bad",
                repository="owner/bad", control_branch="codexbridge-control",
                authorized_by="operator:admin", binding_verified=True,
            )
    for project in ("a", "b", "c"):
        await grant(maker, project)
