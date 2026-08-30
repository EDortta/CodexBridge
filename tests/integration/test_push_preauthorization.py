"""Push pre-authorization is resolved as a recorded approval, never a bypass.

WK-20260830-chatgpt-entry-provider-and-delivery, plan §1C. A request whose
own `delivery` block asks for `allow_push=True` on a pushable branch still
goes through `AWAITING_APPROVAL` and `decide_task_approval` -- it just gets
resolved automatically when the caller already holds approval authority
(`can_approve_push`), producing the exact same `task.approval_decision` audit
trail and `/api/v1/decisions` visibility a human's `approve_codex_task` call
would. Without that authority, it waits for a real human decision like any
other SENSITIVE task.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from gateway.app.db.base import Base
from gateway.app.models.entities import AuditEventModel
from gateway.app.services import store
from shared.protocol import (
    DeliveryRequest,
    ExecutorRegistration,
    ProjectRegistration,
    SubmitTaskRequest,
    TaskMode,
    TaskPriority,
    TaskState,
)


@pytest.fixture
async def db_session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with session_factory() as session:
        await store.upsert_registry(
            session,
            executors=[
                ExecutorRegistration(
                    executor_id="T610",
                    display_name="T610",
                    machine_token="token-1",
                    allowed_projects=["p1"],
                    max_concurrent_tasks=1,
                )
            ],
            projects=[
                ProjectRegistration(project_id="p1", name="Projeto 1", path="/srv/p1", max_timeout_seconds=600),
            ],
        )
        yield session
    await engine.dispose()


def _submit_with_delivery(*, allow_push: bool = True, branch: str = "feature/uc-1") -> SubmitTaskRequest:
    return SubmitTaskRequest(
        executor_id="T610",
        project_id="p1",
        instruction="implementar a issue",
        mode=TaskMode.IMPLEMENT,
        timeout_seconds=300,
        priority=TaskPriority.NORMAL,
        run_when_available=True,
        expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
        delivery=DeliveryRequest(branch=branch, allow_push=allow_push),
    )


async def _audit_events(session: AsyncSession, task_id: str) -> list[AuditEventModel]:
    result = await session.execute(select(AuditEventModel).where(AuditEventModel.entity_id == task_id))
    return list(result.scalars().all())


@pytest.mark.asyncio
async def test_preauthorized_push_resolves_automatically_when_caller_may_approve(db_session: AsyncSession):
    task = await store.create_task(
        db_session,
        _submit_with_delivery(),
        executor_online=True,
        requested_by_user_id="alice",
        requested_by_email="alice@example.com",
        can_approve_push=True,
    )

    # Resolved past AWAITING_APPROVAL in the same call via the same
    # `decide_task_approval` path a human's `approve_codex_task` call uses --
    # which always lands an APPROVED task at WAITING_EXECUTOR, whether or not
    # the executor happens to be connected right now (mirroring
    # `approve_codex_task`'s own handler, which re-dispatches via
    # `hub.dispatch_available` immediately after). Not left pending for a human.
    assert task.state == TaskState.WAITING_EXECUTOR.value
    assert task.approval_state == "approved"
    assert task.policy_level == "sensitive"
    assert task.delivery_json is not None
    assert "feature/uc-1" in task.delivery_json

    events = await _audit_events(db_session, task.id)
    event_types = [e.event_type for e in events]
    assert "task.approval_decision" in event_types
    assert "task.push_preauthorized" in event_types
    preauth_event = next(e for e in events if e.event_type == "task.push_preauthorized")
    assert '"branch": "feature/uc-1"' in preauth_event.payload_json
    assert '"actor_email": "alice@example.com"' in preauth_event.payload_json


@pytest.mark.asyncio
async def test_preauthorized_push_waits_for_a_human_without_approval_authority(db_session: AsyncSession):
    task = await store.create_task(
        db_session,
        _submit_with_delivery(),
        executor_online=True,
        requested_by_user_id="alice",
        requested_by_email="alice@example.com",
        can_approve_push=False,
    )

    assert task.state == TaskState.AWAITING_APPROVAL.value
    assert task.approval_state == "sensitive"
    assert task.policy_level == "sensitive"

    events = await _audit_events(db_session, task.id)
    event_types = [e.event_type for e in events]
    assert "task.push_preauthorized" not in event_types
    assert "task.approval_decision" not in event_types


@pytest.mark.asyncio
async def test_push_to_main_is_never_created_pending_or_otherwise(db_session: AsyncSession):
    """`main` fails `PUSHABLE_BRANCH_PATTERN`, so this is an ordinary

    unauthorized SENSITIVE task -- held for a human, never auto-resolved,
    regardless of `can_approve_push`.
    """
    task = await store.create_task(
        db_session,
        _submit_with_delivery(branch="main"),
        executor_online=True,
        can_approve_push=True,
    )
    assert task.state == TaskState.AWAITING_APPROVAL.value
    assert task.approval_state == "sensitive"


@pytest.mark.asyncio
async def test_restart_clears_delivery_result_but_not_the_request(db_session: AsyncSession):
    task = await store.create_task(
        db_session,
        _submit_with_delivery(),
        executor_online=True,
        can_approve_push=True,
    )
    assert task.state == TaskState.WAITING_EXECUTOR.value

    await store.update_task_state(db_session, task.id, TaskState.RUNNING)
    completed = await store.store_result(
        db_session,
        task.id,
        {
            "final_state": TaskState.COMPLETED.value,
            "provider_run_ref": "sess-abc",
            "delivery": {"outcome": "committed_and_pushed", "branch": "feature/uc-1", "commit": "deadbeef"},
        },
        TaskState.COMPLETED,
    )
    assert completed.delivery_result_json is not None
    assert "deadbeef" in completed.delivery_result_json
    assert completed.session_id == "sess-abc"

    restarted = await store.restart_finished_task(db_session, task.id, executor_online=True)
    assert restarted.delivery_result_json is None
    # The original request must survive a restart -- only the outcome resets.
    assert restarted.delivery_json is not None
    assert "feature/uc-1" in restarted.delivery_json
