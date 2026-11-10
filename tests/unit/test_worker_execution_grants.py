"""SQLite-backed authorization behavior, not mocked grant decisions."""
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from gateway.app.models.entities import (
    WorkerExecutionGrantModel, WorkerIdentityModel, WorkerLeaseSerializationModel,
    WorkerProjectLeaseModel,
)
from gateway.app.services.worker_execution_grants import (
    ExecutionGrantDenied, create_execution_grant, grant_active, revoke_execution_grant,
)
from shared.protocol import TaskMode

NOW = datetime(2026, 11, 10, 12, tzinfo=timezone.utc)


@pytest.fixture
async def maker(tmp_path):
    engine = create_async_engine("sqlite+aiosqlite:///" + str(tmp_path / "execution.db"))
    async with engine.begin() as conn:
        for cls in (WorkerIdentityModel, WorkerLeaseSerializationModel,
                    WorkerProjectLeaseModel, WorkerExecutionGrantModel):
            await conn.run_sync(lambda connection, cls=cls: cls.__table__.create(connection))
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as db:
        async with db.begin():
            db.add(WorkerLeaseSerializationModel(id=1, generation=0))
            db.add(WorkerIdentityModel(id="w1", token_hash="x" * 64, enabled=True,
                                       created_at=NOW))
            db.add(WorkerProjectLeaseModel(id="lease", worker_id="w1", project_id="p",
                     repository="owner/repo", control_branch="codexbridge-control",
                     authorized_by="operator:admin", enabled_at=NOW,
                     expires_at=NOW + timedelta(hours=8), revoked_at=None))
    yield maker
    await engine.dispose()


async def issue(maker, **changes):
    params = dict(worker_id="w1", project_id="p", node_id="node",
                  repository="owner/repo", modes=frozenset({TaskMode.TEST}),
                  authorized_by="operator:admin", operator_authorized=True, now=NOW)
    params.update(changes)
    async with maker() as db:
        return await create_execution_grant(db, **params)


@pytest.mark.asyncio
async def test_requires_independent_human_authorization(maker):
    with pytest.raises(ExecutionGrantDenied, match="human operator"):
        await issue(maker, operator_authorized=False)


@pytest.mark.asyncio
async def test_only_analyze_and_test(maker):
    with pytest.raises(ExecutionGrantDenied, match="only analyze"):
        await issue(maker, modes=frozenset({TaskMode.IMPLEMENT}))


@pytest.mark.asyncio
async def test_grant_eight_hours_and_idempotence(maker):
    grant, created = await issue(maker)
    assert created
    assert grant.expires_at - grant.enabled_at == timedelta(hours=8)
    other, created = await issue(maker)
    assert not created and grant.id == other.id
    assert grant_active(other, now=NOW + timedelta(hours=1),
                        worker_id="w1", project_id="p", node_id="node",
                        repository="owner/repo", mode=TaskMode.TEST)
    assert not grant_active(other, now=NOW + timedelta(hours=8),
                            worker_id="w1", project_id="p", node_id="node",
                            repository="owner/repo", mode=TaskMode.TEST)
    assert not grant_active(other, now=NOW, worker_id="w1", project_id="p",
                            node_id="frida", repository="owner/repo", mode=TaskMode.TEST)
    assert not grant_active(other, now=NOW, worker_id="w1", project_id="p",
                            node_id="node", repository="owner/repo", mode=TaskMode.IMPLEMENT)


@pytest.mark.asyncio
async def test_conflicting_scope_requires_revoke(maker):
    await issue(maker)
    with pytest.raises(ExecutionGrantDenied, match="revoke"):
        await issue(maker, modes=frozenset({TaskMode.ANALYZE}))


@pytest.mark.asyncio
async def test_revoke_blocks_future_starts(maker):
    grant, _ = await issue(maker)
    async with maker() as db:
        assert await revoke_execution_grant(db, grant_id=grant.id, now=NOW + timedelta(minutes=2))
    async with maker() as db:
        row = await db.get(WorkerExecutionGrantModel, grant.id)
        assert not grant_active(row, now=NOW + timedelta(minutes=3),
                                worker_id="w1", project_id="p", node_id="node",
                                repository="owner/repo", mode=TaskMode.TEST)


@pytest.mark.asyncio
async def test_requires_active_intake_lease(maker):
    with pytest.raises(ExecutionGrantDenied, match="intake lease"):
        await issue(maker, now=NOW + timedelta(hours=9))


@pytest.mark.asyncio
async def test_revoked_worker_cannot_issue(maker):
    async with maker() as db:
        async with db.begin():
            row = await db.get(WorkerIdentityModel, "w1")
            row.revoked_at = NOW
    with pytest.raises(ExecutionGrantDenied, match="worker disabled"):
        await issue(maker)
