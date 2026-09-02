"""`store.ensure_node_for_executor` / `upsert_registry` / `record_node_announcement`
(issue #73 Stage 2).

Same in-memory-sqlite idiom `tests/integration/test_store_and_mcp.py` uses for
store-level tests: a real async engine, `Base.metadata.create_all`, no FastAPI
app. Kept under `tests/unit` per the task spec even though it drives a real
(in-memory) database, matching how `test_store_and_mcp.py` is itself
categorized as integration for the same shape of test — the distinction here
is "does this exercise the HTTP surface", and none of these do.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from gateway.app.db.base import Base
from gateway.app.models.entities import ExecutorModel, NodeModel, ProjectAuthorizationModel
from gateway.app.services import store
from shared.protocol import Capability, EngineAvailability, ExecutorRegistration, NodeAnnouncement


@pytest.fixture
async def db_session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        yield session
    await engine.dispose()


async def _add_bare_executor(session: AsyncSession, executor_id: str, *, enabled: bool = True) -> ExecutorModel:
    """An executor row with `node_id` left NULL, bypassing `upsert_registry`.

    Simulates a row written before issue #73's node concept existed —
    `ensure_node_for_executor` exists precisely to repair a row like this one.
    """
    executor = ExecutorModel(
        id=executor_id,
        display_name=f"Display {executor_id}",
        enabled=enabled,
        connected=False,
        metadata_json=json.dumps({"machine_token": "t", "allowed_projects": []}),
    )
    session.add(executor)
    await session.commit()
    await session.refresh(executor)
    return executor


# --------------------------------------------------------------------------
# ensure_node_for_executor
# --------------------------------------------------------------------------


async def test_ensure_node_for_executor_creates_and_binds_when_node_id_is_null(db_session) -> None:
    executor = await _add_bare_executor(db_session, "E1")
    assert executor.node_id is None

    node = await store.ensure_node_for_executor(db_session, executor)
    await db_session.commit()

    assert node.id == "E1"
    assert node.display_name == "Display E1"
    assert node.enabled is True
    assert executor.node_id == "E1"
    assert await db_session.get(NodeModel, "E1") is not None


async def test_ensure_node_for_executor_is_idempotent(db_session) -> None:
    executor = await _add_bare_executor(db_session, "E1")

    first = await store.ensure_node_for_executor(db_session, executor)
    await db_session.commit()
    second = await store.ensure_node_for_executor(db_session, executor)
    await db_session.commit()

    assert first.id == second.id
    rows = (await db_session.execute(select(NodeModel))).scalars().all()
    assert len(rows) == 1


# --------------------------------------------------------------------------
# upsert_registry
# --------------------------------------------------------------------------


async def test_upsert_registry_produces_a_node_for_a_newly_added_executor(db_session) -> None:
    await store.upsert_registry(
        db_session,
        executors=[
            ExecutorRegistration(
                executor_id="E1", display_name="E1", machine_token="t",
                allowed_projects=["p1"], enabled=True,
            )
        ],
        projects=[],
    )
    node = await db_session.get(NodeModel, "E1")
    assert node is not None
    assert node.display_name == "E1"

    # The scenario `ensure_node_for_executor`'s docstring names: a second
    # executor added on a later registry reload, after the migration that
    # seeded nodes 1:1 from executors has already run. Nothing but
    # `upsert_registry` calling `ensure_node_for_executor` itself can give it
    # a node.
    await store.upsert_registry(
        db_session,
        executors=[
            ExecutorRegistration(
                executor_id="E1", display_name="E1", machine_token="t",
                allowed_projects=["p1"], enabled=True,
            ),
            ExecutorRegistration(
                executor_id="E2", display_name="E2", machine_token="t2",
                allowed_projects=["p1"], enabled=True,
            ),
        ],
        projects=[],
    )
    node2 = await db_session.get(NodeModel, "E2")
    assert node2 is not None
    assert node2.display_name == "E2"
    executor2 = await db_session.get(ExecutorModel, "E2")
    assert executor2.node_id == "E2"


# --------------------------------------------------------------------------
# record_node_announcement
# --------------------------------------------------------------------------


async def test_record_node_announcement_writes_observation_fields(db_session) -> None:
    executor = await _add_bare_executor(db_session, "E1")
    await store.ensure_node_for_executor(db_session, executor)
    await db_session.commit()

    announcement = NodeAnnouncement(
        agent_version="1.2.3",
        os="Linux",
        arch="x86_64",
        engines=[EngineAvailability(engine="codex", implemented=True, available=True, version="0.9.0")],
        capabilities=[Capability.READ, Capability.TEST],
        max_concurrent_tasks=2,
        discovery_root_count=3,
    )
    now = datetime.now(timezone.utc)
    node = await store.record_node_announcement(db_session, executor, announcement, now=now)

    assert node.os == "Linux"
    assert node.arch == "x86_64"
    assert node.agent_version == "1.2.3"
    # SQLite hands the timestamp back naive even though it was written aware
    # (the same naive/aware split `store._as_utc` exists to paper over
    # elsewhere in this module) -- compare the instant, not the `tzinfo`.
    observed = node.capabilities_observed_at
    if observed.tzinfo is None:
        observed = observed.replace(tzinfo=timezone.utc)
    assert observed == now

    inventory = json.loads(node.capabilities_json)
    assert inventory["capabilities"] == ["read", "test"]
    assert inventory["max_concurrent_tasks"] == 2
    assert inventory["discovery_root_count"] == 3
    assert inventory["engines"] == [
        {"engine": "codex", "implemented": True, "available": True, "version": "0.9.0", "detail": None}
    ]


async def test_record_node_announcement_leaves_enabled_health_reason_and_authorizations_untouched(db_session) -> None:
    """An announcement is an observation, never a grant (issue #73)."""
    executor = await _add_bare_executor(db_session, "E1", enabled=True)
    node = await store.ensure_node_for_executor(db_session, executor)
    node.enabled = False
    node.health_reason = "operator paused this node"
    session_authorization = ProjectAuthorizationModel(
        id="auth-1",
        node_id="E1",
        project_id="p1",
        capabilities_json="[]",
        granted_by="operator:esteban",
        granted_at=datetime.now(timezone.utc),
    )
    db_session.add(session_authorization)
    await db_session.commit()

    announcement = NodeAnnouncement(
        agent_version="9.9.9",
        capabilities=[Capability.READ, Capability.MODIFY, Capability.DELIVER],
    )
    await store.record_node_announcement(db_session, executor, announcement)

    reloaded = await db_session.get(NodeModel, "E1")
    assert reloaded.enabled is False
    assert reloaded.health_reason == "operator paused this node"

    authorizations = (
        await db_session.execute(
            select(ProjectAuthorizationModel).where(ProjectAuthorizationModel.node_id == "E1")
        )
    ).scalars().all()
    assert len(authorizations) == 1
    assert authorizations[0].revoked_at is None
    assert json.loads(authorizations[0].capabilities_json) == []
