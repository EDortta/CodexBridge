"""SQLite regression tests for non-executing Worker correlation reservations."""
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from gateway.app.models.entities import (
    WorkerExecutionGrantModel, WorkerLeaseSerializationModel,
    WorkerMissionCorrelationModel, WorkerRequestModel,
)
from gateway.app.services.worker_mission_correlations import (
    CorrelationDenied, reserve_worker_correlation,
)
from shared.protocol import TaskMode

NOW = datetime(2026, 11, 10, 14, tzinfo=timezone.utc)
PARAMS = dict(
    project_id="p", request_id="r", worker_id="w",
    payload_sha256="a" * 64, source_commit="b" * 40,
    grant_id="grant", node_id="node", repository="owner/repo",
    mode=TaskMode.TEST,
)


@pytest.fixture
async def maker(tmp_path):
    engine = create_async_engine("sqlite+aiosqlite:///" + str(tmp_path / "correlations.db"))
    async with engine.begin() as connection:
        for model in (
            WorkerLeaseSerializationModel, WorkerRequestModel,
            WorkerExecutionGrantModel, WorkerMissionCorrelationModel,
        ):
            await connection.run_sync(lambda conn, m=model: m.__table__.create(conn))
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    async with sessions() as session:
        async with session.begin():
            session.add(WorkerLeaseSerializationModel(id=1, generation=0))
            session.add(WorkerRequestModel(
                project_id="p", request_id="r", worker_id="w",
                payload_sha256="a" * 64, source_commit="b" * 40,
                operation="test", state="admitted", received_at=NOW,
            ))
            session.add(WorkerExecutionGrantModel(
                id="grant", worker_id="w", project_id="p", node_id="node",
                repository="owner/repo", modes_json='["test"]',
                authorized_by="operator:admin", enabled_at=NOW,
                expires_at=NOW + timedelta(hours=8), revoked_at=None,
            ))
    yield sessions
    await engine.dispose()


@pytest.mark.asyncio
async def test_reserve_then_replay_returns_same_row(maker):
    async with maker() as session:
        original, created = await reserve_worker_correlation(session, **PARAMS, now=NOW)
        assert created and original.state == "reserved"
        assert original.mission_id is None and original.task_id is None
    async with maker() as session:
        replay, created = await reserve_worker_correlation(
            session, **PARAMS, now=NOW + timedelta(hours=9)
        )
        assert not created
        assert replay.request_id == original.request_id


@pytest.mark.asyncio
async def test_scope_change_refused(maker):
    async with maker() as session:
        await reserve_worker_correlation(session, **PARAMS, now=NOW)
    async with maker() as session:
        with pytest.raises(CorrelationDenied, match="different scope"):
            await reserve_worker_correlation(
                session, **{**PARAMS, "node_id": "other"}, now=NOW
            )


@pytest.mark.asyncio
async def test_expired_grant_cannot_reserve(maker):
    async with maker() as session:
        with pytest.raises(CorrelationDenied, match="active execution grant"):
            await reserve_worker_correlation(
                session, **PARAMS, now=NOW + timedelta(hours=8)
            )


@pytest.mark.asyncio
async def test_revoked_grant_cannot_reserve(maker):
    async with maker() as session:
        async with session.begin():
            grant = await session.get(WorkerExecutionGrantModel, "grant")
            grant.revoked_at = NOW + timedelta(minutes=1)
    async with maker() as session:
        with pytest.raises(CorrelationDenied, match="active execution grant"):
            await reserve_worker_correlation(
                session, **PARAMS, now=NOW + timedelta(minutes=2)
            )


@pytest.mark.asyncio
async def test_admission_digest_mismatch_is_rejected(maker):
    async with maker() as session:
        with pytest.raises(CorrelationDenied, match="admission identity mismatch"):
            await reserve_worker_correlation(
                session, **{**PARAMS, "payload_sha256": "f" * 64}, now=NOW
            )


@pytest.mark.asyncio
async def test_no_admission_cannot_reserve(maker):
    async with maker() as session:
        with pytest.raises(CorrelationDenied, match="request not admitted"):
            await reserve_worker_correlation(
                session, **{**PARAMS, "request_id": "missing"}, now=NOW
            )


@pytest.mark.asyncio
async def test_unsupported_mode_does_not_query_database():
    with pytest.raises(CorrelationDenied, match="unsupported operation"):
        await reserve_worker_correlation(
            None, **{**PARAMS, "mode": TaskMode.BUILD}, now=NOW
        )
