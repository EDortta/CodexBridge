"""`store.effective_task_modes` -- issue #73 Stage 4, WK-20260902-gh73-authorization-plane.

The enforcement half of the authorization plane: the ONE place that decides
which `TaskMode`s an executor may run against a project, replacing the inline
`allowed_modes` membership check `create_task` used to do itself. Every rule
below is proven at the `create_task` boundary, not just against the helper
directly, because `create_task` is the thing that actually gates a real
dispatch -- and every negative case carries a positive control in the same
file (`docs/napkin-lessons.md`, 2026-09-01: "five green tests once proved
only that the code they exercised was unreachable").
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from gateway.app.db.base import Base
from gateway.app.models.entities import (
    AuditEventModel,
    ExecutorModel,
    ProjectAuthorizationModel,
    ProjectModel,
    WorkspaceBindingModel,
)
from gateway.app.services import store
from shared.protocol import (
    BindingState,
    Capability,
    ExecutorRegistration,
    ProjectRegistration,
    SubmitTaskRequest,
    TaskMode,
    TaskPriority,
)


@pytest.fixture
async def db_session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        yield session
    await engine.dispose()


async def _seed(
    session: AsyncSession,
    *,
    executor_id: str = "E1",
    project_id: str = "p1",
    allowed_modes: list[TaskMode] | None = None,
) -> tuple[ExecutorModel, ProjectModel]:
    await store.upsert_registry(
        session,
        executors=[
            ExecutorRegistration(
                executor_id=executor_id,
                display_name=executor_id,
                machine_token="t",
                allowed_projects=[project_id],
            )
        ],
        projects=[
            ProjectRegistration(
                project_id=project_id,
                name=project_id,
                path=f"/srv/{project_id}",
                allowed_modes=allowed_modes if allowed_modes is not None else list(TaskMode),
                max_timeout_seconds=600,
            )
        ],
    )
    await session.commit()
    executor = await session.get(ExecutorModel, executor_id)
    project = await session.get(ProjectModel, project_id)
    return executor, project


async def _bind(session: AsyncSession, *, node_id: str, project_id: str) -> None:
    session.add(
        WorkspaceBindingModel(
            id=f"binding-{node_id}-{project_id}",
            node_id=node_id,
            project_id=project_id,
            local_path=f"/srv/{project_id}",
            state=BindingState.ACTIVE.value,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
    )
    await session.commit()


async def _authorize(
    session: AsyncSession, *, node_id: str, project_id: str, capabilities: list[Capability]
) -> None:
    session.add(
        ProjectAuthorizationModel(
            id=f"auth-{node_id}-{project_id}",
            node_id=node_id,
            project_id=project_id,
            capabilities_json=json.dumps([c.value for c in capabilities]),
            granted_by="operator:tester",
            granted_at=datetime.now(timezone.utc),
        )
    )
    await session.commit()


def _submit(mode: TaskMode, *, executor_id: str = "E1", project_id: str = "p1") -> SubmitTaskRequest:
    return SubmitTaskRequest(
        executor_id=executor_id,
        project_id=project_id,
        instruction="do something",
        mode=mode,
        timeout_seconds=300,
        priority=TaskPriority.NORMAL,
        run_when_available=True,
        expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
    )


# --------------------------------------------------------------------------
# `effective_task_modes` directly
# --------------------------------------------------------------------------


async def test_no_binding_returns_the_project_base_unchanged(db_session: AsyncSession) -> None:
    """Non-regression: a pair that never went through discovery adoption is

    exactly as permissive as `allowed_modes` always said, forever -- not a
    grace period (migrations/0009_control_plane.sql: "access continues
    flowing through the pre-existing allowed_projects"). This is the
    property that would have passed BEFORE this PR's `create_task` change
    existed, proven directly against the new helper.
    """
    executor, project = await _seed(db_session, allowed_modes=[TaskMode.ANALYZE, TaskMode.IMPLEMENT])
    modes = await store.effective_task_modes(db_session, executor, project)
    assert modes == frozenset({TaskMode.ANALYZE, TaskMode.IMPLEMENT})


async def test_a_binding_with_no_authorization_permits_nothing(db_session: AsyncSession) -> None:
    executor, project = await _seed(db_session, allowed_modes=list(TaskMode))
    await _bind(db_session, node_id=executor.node_id, project_id=project.id)
    modes = await store.effective_task_modes(db_session, executor, project)
    assert modes == frozenset()


async def test_a_binding_with_read_and_test_permits_exactly_those_modes(db_session: AsyncSession) -> None:
    executor, project = await _seed(db_session, allowed_modes=list(TaskMode))
    await _bind(db_session, node_id=executor.node_id, project_id=project.id)
    await _authorize(
        db_session, node_id=executor.node_id, project_id=project.id, capabilities=[Capability.READ, Capability.TEST]
    )
    modes = await store.effective_task_modes(db_session, executor, project)
    assert modes == frozenset({TaskMode.ANALYZE, TaskMode.REVIEW, TaskMode.TEST})


async def test_a_revoked_authorization_permits_nothing(db_session: AsyncSession) -> None:
    """Positive control for the "no authorization" case: an authorization row

    that EXISTS but is revoked must behave identically to no row at all.
    """
    executor, project = await _seed(db_session, allowed_modes=list(TaskMode))
    await _bind(db_session, node_id=executor.node_id, project_id=project.id)
    await _authorize(
        db_session, node_id=executor.node_id, project_id=project.id, capabilities=[Capability.READ]
    )
    async with db_session.begin():
        row = (
            await db_session.execute(
                select(ProjectAuthorizationModel).where(
                    ProjectAuthorizationModel.node_id == executor.node_id,
                    ProjectAuthorizationModel.project_id == project.id,
                )
            )
        ).scalars().first()
        row.revoked_at = datetime.now(timezone.utc)
    modes = await store.effective_task_modes(db_session, executor, project)
    assert modes == frozenset()


async def test_authorization_never_widens_past_the_projects_own_allowed_modes(db_session: AsyncSession) -> None:
    """A capability grant intersects with `allowed_modes`, it never adds to it:

    the project's own configuration stays the outer bound.
    """
    executor, project = await _seed(db_session, allowed_modes=[TaskMode.ANALYZE])  # project itself is read-only
    await _bind(db_session, node_id=executor.node_id, project_id=project.id)
    await _authorize(
        db_session,
        node_id=executor.node_id,
        project_id=project.id,
        capabilities=[Capability.READ, Capability.TEST, Capability.MODIFY],
    )
    modes = await store.effective_task_modes(db_session, executor, project)
    # MODIFY/TEST are authorized, but the project's own allowed_modes never
    # named `implement`/`edit`/`test` -- the intersection stays inside it.
    assert modes == frozenset({TaskMode.ANALYZE})


# --------------------------------------------------------------------------
# `create_task` -- the real enforcement boundary
# --------------------------------------------------------------------------


async def test_create_task_for_an_unbound_pair_behaves_exactly_as_before_this_pr(db_session: AsyncSession) -> None:
    """This is the test that would have passed before `effective_task_modes`

    existed: an executor/project pair with no `workspace_bindings` row is
    gated purely by `allowed_modes`, same as `create_task`'s old inline
    check.
    """
    await _seed(db_session, allowed_modes=[TaskMode.ANALYZE])
    task = await store.create_task(db_session, _submit(TaskMode.ANALYZE), executor_online=True)
    assert task.mode == TaskMode.ANALYZE.value

    with pytest.raises(ValueError, match="mode_not_allowed_for_project"):
        await store.create_task(db_session, _submit(TaskMode.IMPLEMENT), executor_online=True)


async def test_create_task_for_a_bound_but_unauthorized_pair_refuses_every_mode(db_session: AsyncSession) -> None:
    executor, project = await _seed(db_session, allowed_modes=list(TaskMode))
    await _bind(db_session, node_id=executor.node_id, project_id=project.id)
    with pytest.raises(ValueError, match="mode_not_allowed_for_project"):
        await store.create_task(db_session, _submit(TaskMode.ANALYZE), executor_online=True)


async def test_create_task_for_a_bound_and_partially_authorized_pair_allows_only_the_granted_modes(
    db_session: AsyncSession,
) -> None:
    executor, project = await _seed(db_session, allowed_modes=list(TaskMode))
    await _bind(db_session, node_id=executor.node_id, project_id=project.id)
    await _authorize(
        db_session, node_id=executor.node_id, project_id=project.id, capabilities=[Capability.READ, Capability.TEST]
    )

    for mode in (TaskMode.ANALYZE, TaskMode.REVIEW, TaskMode.TEST):
        task = await store.create_task(db_session, _submit(mode), executor_online=True)
        assert task.mode == mode.value

    with pytest.raises(ValueError, match="mode_not_allowed_for_project"):
        await store.create_task(db_session, _submit(TaskMode.IMPLEMENT), executor_online=True)


# --------------------------------------------------------------------------
# `grant_project_authorization` / `revoke_project_authorization`
# --------------------------------------------------------------------------


async def test_granting_a_new_pair_creates_one_row(db_session: AsyncSession) -> None:
    executor, project = await _seed(db_session)
    row = await store.grant_project_authorization(
        db_session,
        node_id=executor.node_id,
        project_id=project.id,
        capabilities=[Capability.READ],
        granted_by="operator:alice",
    )
    assert json.loads(row.capabilities_json) == ["read"]
    assert row.granted_by == "operator:alice"
    assert row.revoked_at is None


async def test_granting_twice_overwrites_rather_than_merges(db_session: AsyncSession) -> None:
    """Unlike adoption's own `_grant_project_authorization` (merge-only), this

    is the explicit operator surface: a second grant call states what the
    operator wants NOW, replacing the first grant's capabilities rather than
    adding to them.
    """
    executor, project = await _seed(db_session)
    await store.grant_project_authorization(
        db_session,
        node_id=executor.node_id,
        project_id=project.id,
        capabilities=[Capability.READ, Capability.TEST],
        granted_by="operator:alice",
    )
    row = await store.grant_project_authorization(
        db_session,
        node_id=executor.node_id,
        project_id=project.id,
        capabilities=[Capability.READ],
        granted_by="operator:bob",
    )
    assert json.loads(row.capabilities_json) == ["read"]  # not ["read", "test"]
    assert row.granted_by == "operator:bob"

    rows = (
        (
            await db_session.execute(
                select(ProjectAuthorizationModel).where(
                    ProjectAuthorizationModel.node_id == executor.node_id,
                    ProjectAuthorizationModel.project_id == project.id,
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(rows) == 1  # never a second row


async def test_revoke_then_regrant_reuses_the_same_row(db_session: AsyncSession) -> None:
    executor, project = await _seed(db_session)
    granted = await store.grant_project_authorization(
        db_session, node_id=executor.node_id, project_id=project.id, capabilities=[Capability.READ], granted_by="operator:alice"
    )
    revoked = await store.revoke_project_authorization(
        db_session, node_id=executor.node_id, project_id=project.id, revoked_by="operator:alice"
    )
    assert revoked.id == granted.id
    assert revoked.revoked_at is not None

    regranted = await store.grant_project_authorization(
        db_session, node_id=executor.node_id, project_id=project.id, capabilities=[Capability.TEST], granted_by="operator:alice"
    )
    assert regranted.id == granted.id  # same row, reactivated
    assert regranted.revoked_at is None
    assert json.loads(regranted.capabilities_json) == ["test"]

    rows = (
        (
            await db_session.execute(
                select(ProjectAuthorizationModel).where(
                    ProjectAuthorizationModel.node_id == executor.node_id,
                    ProjectAuthorizationModel.project_id == project.id,
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(rows) == 1  # never a second row, even across revoke/regrant

    events = (
        (
            await db_session.execute(
                select(AuditEventModel).where(AuditEventModel.entity_id == granted.id)
            )
        )
        .scalars()
        .all()
    )
    event_types = [event.event_type for event in events]
    assert event_types == [
        "project_authorization.granted",
        "project_authorization.revoked",
        "project_authorization.granted",
    ]


async def test_revoking_a_pair_with_no_active_authorization_returns_none(db_session: AsyncSession) -> None:
    """Positive control for the revoke/regrant test: revoking nothing is a

    no-op the caller can detect, not a silent success against a phantom row.
    """
    executor, project = await _seed(db_session)
    result = await store.revoke_project_authorization(
        db_session, node_id=executor.node_id, project_id=project.id, revoked_by="operator:alice"
    )
    assert result is None
