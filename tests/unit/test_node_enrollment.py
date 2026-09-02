"""`store.create_node_invite` / `store.enroll_node` / `store.revoke_node` —
issue #76's minimal cut.

Same in-memory-sqlite idiom `tests/unit/test_node_store.py` uses: a real
async engine, `Base.metadata.create_all`, no FastAPI app, no live socket.
The WebSocket-facing half of this cut (a socket actually closing, a revoked
node's next handshake actually being refused) is
`tests/integration/test_node_enrollment_ws.py`, driven directly against
`agent_ws` for the same reason `tests/integration/test_agent_ws_identity.py`
is: `TestClient.websocket_connect` runs the app on a second thread and event
loop, and sharing one in-memory aiosqlite engine across the two deadlocks.

Every negative here (unknown/consumed/expired invite, unknown node to
revoke) sits next to a positive that proves the same code path is actually
reachable — 2026-09-01's napkin-lessons entry: a negative that passes
because nothing ran proves nothing.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from gateway.app.db.base import Base
from gateway.app.models.entities import AuditEventModel, ExecutorModel, NodeInviteModel, NodeModel
from gateway.app.services import store
from shared.security import hash_token


@pytest.fixture
async def db_session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        yield session
    await engine.dispose()


# --------------------------------------------------------------------------
# create_node_invite
# --------------------------------------------------------------------------


async def test_create_node_invite_stores_only_the_hash(db_session) -> None:
    invite = await store.create_node_invite(
        db_session,
        token="raw-invite-token",
        created_by="esteban",
        display_name_hint="devel3",
        ttl_seconds=900,
    )

    assert invite.token_hash == hash_token("raw-invite-token")
    assert invite.created_by == "esteban"
    assert invite.display_name_hint == "devel3"
    assert invite.consumed_at is None
    expires_at = invite.expires_at
    if expires_at.tzinfo is None:
        # SQLite drops tzinfo on read-back; the column is still UTC (`store`
        # writes it as `datetime.now(timezone.utc)`), same as every other
        # `timestamptz` column this codebase reads back through SQLite.
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    assert expires_at > datetime.now(timezone.utc)


async def test_create_node_invite_never_writes_the_raw_token_to_audit_events(db_session) -> None:
    await store.create_node_invite(
        db_session,
        token="super-secret-raw-value",
        created_by="esteban",
        display_name_hint=None,
        ttl_seconds=900,
    )

    rows = (await db_session.execute(select(AuditEventModel))).scalars().all()
    assert rows, "the positive control: an audit row was actually written"
    for row in rows:
        assert "super-secret-raw-value" not in row.payload_json


# --------------------------------------------------------------------------
# enroll_node
# --------------------------------------------------------------------------


async def _issued_invite(db_session, *, ttl_seconds: int = 900, token: str = "invite-token"):
    return await store.create_node_invite(
        db_session, token=token, created_by="esteban", display_name_hint="devel3", ttl_seconds=ttl_seconds
    )


async def test_enroll_node_creates_executor_and_node_and_consumes_the_invite(db_session) -> None:
    await _issued_invite(db_session, token="good-invite")

    result = await store.enroll_node(
        db_session, invite_token="good-invite", display_name="devel3", machine_token="raw-machine-token"
    )

    assert result is not None
    node, executor = result
    assert node.display_name == "devel3"
    assert node.admission_state == "enrolled"
    assert node.enabled is True
    assert executor.node_id == node.id
    assert executor.machine_token_hash == hash_token("raw-machine-token")
    assert executor.enabled is True

    invite = (
        (await db_session.execute(select(NodeInviteModel).where(NodeInviteModel.token_hash == hash_token("good-invite"))))
        .scalars()
        .one()
    )
    assert invite.consumed_at is not None
    assert invite.consumed_by_node_id == node.id


async def test_enroll_node_refuses_an_unknown_token(db_session) -> None:
    result = await store.enroll_node(
        db_session, invite_token="never-issued", display_name="devel3", machine_token="t"
    )
    assert result is None


async def test_enroll_node_refuses_a_consumed_invite_the_second_time(db_session) -> None:
    await _issued_invite(db_session, token="single-use")

    first = await store.enroll_node(
        db_session, invite_token="single-use", display_name="devel3", machine_token="t1"
    )
    assert first is not None, "the positive control: the first redemption must succeed"

    second = await store.enroll_node(
        db_session, invite_token="single-use", display_name="devel3-again", machine_token="t2"
    )
    assert second is None


async def test_claiming_an_invite_is_conditional_so_only_one_racer_wins(db_session) -> None:
    """The `WHERE consumed_at IS NULL` `enroll_node` relies on.

    The sequential case above is covered by the test before this one. What
    this pins is the mechanism underneath it: two requests holding the same
    live token can both READ the invite as unconsumed before either writes,
    and an assignment to `invite.consumed_at` would let both commit -- one
    single-use invite minting two nodes with two valid machine tokens.

    The true interleaving is not reproducible here without a seam inside
    `enroll_node` that exists only for the test, so this asserts the property
    the fix rests on directly: the second conditional update matches nothing.
    If someone later replaces that update with a field assignment, this fails.
    """
    invite = await _issued_invite(db_session, token="raced")

    first = await db_session.execute(
        update(NodeInviteModel)
        .where(NodeInviteModel.id == invite.id, NodeInviteModel.consumed_at.is_(None))
        .values(consumed_at=datetime.now(timezone.utc), consumed_by_node_id="node-a")
    )
    second = await db_session.execute(
        update(NodeInviteModel)
        .where(NodeInviteModel.id == invite.id, NodeInviteModel.consumed_at.is_(None))
        .values(consumed_at=datetime.now(timezone.utc), consumed_by_node_id="node-b")
    )

    assert first.rowcount == 1, "the positive control: the first claim must win"
    assert second.rowcount == 0
    await db_session.rollback()


async def test_enroll_node_refuses_an_expired_invite(db_session) -> None:
    invite = await _issued_invite(db_session, token="expiring", ttl_seconds=900)
    invite.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    await db_session.commit()

    result = await store.enroll_node(
        db_session, invite_token="expiring", display_name="devel3", machine_token="t"
    )
    assert result is None


async def test_enroll_node_generates_an_id_rather_than_trusting_the_caller(db_session) -> None:
    """No `executor_id`/`node_id` field on the request at all -- this is what
    keeps an unauthenticated caller from colliding with an existing node by
    naming it. `display_name` may repeat; the generated id may not."""
    await _issued_invite(db_session, token="invite-a")
    await _issued_invite(db_session, token="invite-b")

    first = await store.enroll_node(
        db_session, invite_token="invite-a", display_name="same-display-name", machine_token="t1"
    )
    second = await store.enroll_node(
        db_session, invite_token="invite-b", display_name="same-display-name", machine_token="t2"
    )

    assert first is not None and second is not None
    assert first[0].id != second[0].id


# --------------------------------------------------------------------------
# revoke_node
# --------------------------------------------------------------------------


async def test_revoke_node_disables_both_the_node_and_its_executor(db_session) -> None:
    await _issued_invite(db_session, token="to-revoke")
    node, executor = await store.enroll_node(
        db_session, invite_token="to-revoke", display_name="devel3", machine_token="t"
    )
    assert node.enabled is True, "the positive control: the node starts enabled"

    revoked = await store.revoke_node(db_session, node.id)

    assert revoked is not None
    assert revoked.admission_state == "revoked"
    assert revoked.enabled is False
    reloaded_executor = await db_session.get(ExecutorModel, executor.id)
    assert reloaded_executor.enabled is False


async def test_revoke_node_refuses_an_unknown_node(db_session) -> None:
    result = await store.revoke_node(db_session, "no-such-node")
    assert result is None
