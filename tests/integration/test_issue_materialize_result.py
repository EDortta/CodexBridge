"""`issue.materialize_result` handling in the `/agent/ws` message loop --

issue #78, Commit 2. Exercised against `gateway.app.main.handle_issue_materialize_result`
directly, the same posture `tests/integration/test_agent_ack_handling.py` takes
for `task.ack` -- see that file's own docstring for why a direct call, not a
live websocket, is what actually proves the handler ran.
"""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from gateway.app.db.base import Base
from gateway.app.main import handle_issue_materialize_result
from gateway.app.models.entities import AuditEventModel
from gateway.app.services import store
from shared.protocol import AgentEnvelope, AgentMessageType, ExecutorRegistration, ProjectRegistration
from sqlalchemy import select


@pytest.fixture
async def factory():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with session_factory() as session:
        await store.upsert_registry(
            session,
            executors=[
                ExecutorRegistration(
                    executor_id="T1", display_name="T1", machine_token="t",
                    allowed_projects=["p1"], max_concurrent_tasks=1,
                )
            ],
            projects=[ProjectRegistration(project_id="p1", name="P1", path="/srv/p1", max_timeout_seconds=3600)],
        )
    try:
        yield session_factory
    finally:
        await engine.dispose()


async def _seed_epic_with_issue(factory) -> tuple[str, str]:
    async with factory() as session:
        epic = await store.create_epic(
            session, project_id="p1", title="Bridge epic", description=None, status=None,
            actor_user_id="alice", actor_email="alice@example.com",
        )
        issue = await store.create_issue(
            session, project_id="p1", epic_id=epic.id, title="First slice", description=None,
            status=None, priority=None, labels=None, assignee_user_id=None, assignee_email=None,
            dependencies=None, blocked_reason=None,
            actor_user_id="alice", actor_email="alice@example.com",
        )
        return epic.id, issue.id


def _envelope(payload: dict) -> AgentEnvelope:
    return AgentEnvelope(
        message_id=str(uuid4()), executor_id="T1", sent_at=datetime.now(timezone.utc),
        type=AgentMessageType.ISSUE_MATERIALIZE_RESULT, payload=payload,
    )


@pytest.mark.asyncio
async def test_a_successful_result_records_materialized_path_on_epic_and_issue(factory):
    """Positive control for the failure/unknown-epic tests below."""
    epic_id, issue_id = await _seed_epic_with_issue(factory)

    async with factory() as session:
        epic_before = await store.get_epic(session, epic_id)
        issue_before = await store.get_issue(session, issue_id)

        await handle_issue_materialize_result(session, _envelope({
            "epic_id": epic_id,
            "ok": True,
            "epic_path": "docs/issues/078-bridge-epic-[ready]",
            "epic_revision": epic_before.revision,
            "written_paths": {
                "README.md": "docs/issues/078-bridge-epic-[ready]/README.md",
                "epic.md": "docs/issues/078-bridge-epic-[ready]/epic.md",
                f"issues/{issue_id}/first-slice-[ready].md": "docs/issues/078-bridge-epic-[ready]/issues/079-first-slice-[ready].md",
            },
            "issue_revisions": {issue_id: issue_before.revision},
        }))

    async with factory() as session:
        epic_after = await store.get_epic(session, epic_id)
        issue_after = await store.get_issue(session, issue_id)

    assert epic_after.materialized_path == "docs/issues/078-bridge-epic-[ready]"
    assert epic_after.materialized_revision == epic_before.revision
    assert issue_after.materialized_path == "docs/issues/078-bridge-epic-[ready]/issues/079-first-slice-[ready].md"
    assert issue_after.materialized_revision == issue_before.revision


@pytest.mark.asyncio
async def test_a_failed_result_does_not_touch_materialized_path(factory):
    epic_id, issue_id = await _seed_epic_with_issue(factory)

    async with factory() as session:
        await handle_issue_materialize_result(session, _envelope({
            "epic_id": epic_id, "ok": False, "error": "existing_path_not_found",
        }))

    async with factory() as session:
        epic_after = await store.get_epic(session, epic_id)
        result = await session.execute(
            select(AuditEventModel).where(AuditEventModel.entity_id == epic_id)
        )
        events = [row.event_type for row in result.scalars()]

    # Negative control against the positive test above: a failed result never
    # sets materialized_path.
    assert epic_after.materialized_path is None
    assert epic_after.materialized_revision is None
    assert "epic.materialize_failed" in events


@pytest.mark.asyncio
async def test_a_result_for_an_unknown_epic_does_not_raise(factory):
    async with factory() as session:
        # Must not raise -- there is no caller waiting synchronously on this
        # (see the function's own docstring).
        await handle_issue_materialize_result(session, _envelope({
            "epic_id": "does-not-exist",
            "ok": True,
            "epic_path": "docs/issues/999-ghost-[ready]",
            "epic_revision": 1,
            "written_paths": {},
            "issue_revisions": {},
        }))


@pytest.mark.asyncio
async def test_a_result_with_no_epic_id_is_ignored_not_raised(factory):
    async with factory() as session:
        await handle_issue_materialize_result(session, _envelope({"ok": True}))


# --------------------------------------------------------------------------
# `store.apply_epic_materialization` directly -- correlation-token parsing.
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_apply_epic_materialization_ignores_non_issue_keys_and_unknown_issue_ids(factory):
    """Positive control: the real issue id updates; two adversarial-ish

    inputs (a non-`issues/`-prefixed key, and an `issues/`-prefixed key
    naming an issue that does not exist) are silently skipped rather than
    raising -- an executor report is data, not a query the caller can shape
    into a crash.
    """
    epic_id, issue_id = await _seed_epic_with_issue(factory)

    async with factory() as session:
        epic = await store.apply_epic_materialization(
            session,
            epic_id=epic_id,
            epic_path="docs/issues/078-bridge-epic-[ready]",
            epic_revision=1,
            written_paths={
                "README.md": "docs/issues/078-bridge-epic-[ready]/README.md",
                f"issues/{issue_id}/first-slice-[ready].md": "docs/issues/078-bridge-epic-[ready]/issues/079-first-slice-[ready].md",
                "issues/does-not-exist/ghost.md": "docs/issues/078-bridge-epic-[ready]/issues/080-ghost.md",
            },
            issue_revisions={issue_id: 1},
        )
    assert epic is not None
    assert epic.materialized_path == "docs/issues/078-bridge-epic-[ready]"

    async with factory() as session:
        issue = await store.get_issue(session, issue_id)
    assert issue.materialized_path == "docs/issues/078-bridge-epic-[ready]/issues/079-first-slice-[ready].md"
