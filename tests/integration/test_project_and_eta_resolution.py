"""`resolve_project_reference` and `estimate_task_duration_seconds`.

WK-20260830-chatgpt-entry-provider-and-delivery, `start_development_task`
support. Both are pure store-layer functions the gateway never has to touch
a filesystem for -- see `docs/architecture.md`: the gateway only ever
resolves a `project_id`, never a path.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from gateway.app.db.base import Base
from gateway.app.services import store
from shared.protocol import (
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
                    executor_id="T610", display_name="T610", machine_token="t",
                    allowed_projects=["codexbridge", "jk-structure", "jk-panel"], max_concurrent_tasks=1,
                )
            ],
            projects=[
                ProjectRegistration(project_id="codexbridge", name="CodexBridge", path="/srv/codexbridge"),
                ProjectRegistration(project_id="jk-structure", name="JK Structure", path="/srv/jk-structure"),
                ProjectRegistration(project_id="jk-panel", name="JK Panel", path="/srv/jk-panel"),
            ],
        )
        yield session
    await engine.dispose()


# --------------------------------------------------------------------------
# resolve_project_reference
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_resolves_exact_project_id(db_session: AsyncSession):
    project = await store.resolve_project_reference(db_session, "codexbridge")
    assert project.id == "codexbridge"


@pytest.mark.asyncio
async def test_resolves_exact_name_case_insensitively(db_session: AsyncSession):
    project = await store.resolve_project_reference(db_session, "codexbridge".upper())
    assert project.id == "codexbridge"
    project = await store.resolve_project_reference(db_session, "jk structure".title())
    assert project.id == "jk-structure"


@pytest.mark.asyncio
async def test_resolves_a_unique_prefix(db_session: AsyncSession):
    project = await store.resolve_project_reference(db_session, "codex")
    assert project.id == "codexbridge"


@pytest.mark.asyncio
async def test_ambiguous_prefix_names_every_candidate_and_never_guesses(db_session: AsyncSession):
    with pytest.raises(store.AmbiguousProjectReference) as raised:
        await store.resolve_project_reference(db_session, "jk-")
    ids = sorted(c.id for c in raised.value.candidates)
    assert ids == ["jk-panel", "jk-structure"]


@pytest.mark.asyncio
async def test_unknown_reference_raises_unknown_project(db_session: AsyncSession):
    with pytest.raises(ValueError, match="unknown_project"):
        await store.resolve_project_reference(db_session, "no-such-project")


@pytest.mark.asyncio
async def test_empty_reference_raises_unknown_project(db_session: AsyncSession):
    with pytest.raises(ValueError, match="unknown_project"):
        await store.resolve_project_reference(db_session, "   ")


@pytest.mark.asyncio
async def test_a_percent_or_underscore_in_the_reference_is_not_a_wildcard(db_session: AsyncSession):
    """`_like_escape` must neutralize SQL LIKE metacharacters in

    caller-supplied text -- otherwise "jk_structure" (an underscore standing
    for "any one character" in LIKE) would ALSO prefix-match "jk-structure",
    turning an exact-looking typo into a silent, wrong match.
    """
    with pytest.raises(ValueError, match="unknown_project"):
        await store.resolve_project_reference(db_session, "jk_structure_typo")


# --------------------------------------------------------------------------
# estimate_task_duration_seconds
# --------------------------------------------------------------------------


async def _seed_completed_task(
    session: AsyncSession, *, project_id: str, mode: TaskMode, engine: str, duration_seconds: float
) -> None:
    request = SubmitTaskRequest(
        executor_id="T610",
        project_id=project_id,
        instruction="do the thing",
        mode=mode,
        timeout_seconds=3600,
        priority=TaskPriority.NORMAL,
        run_when_available=True,
        expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
        engine=engine,
    )
    task = await store.create_task(session, request, executor_online=True)
    await store.update_task_state(session, task.id, TaskState.RUNNING)
    task = await session.get(type(task), task.id)
    # A single anchor instant for both timestamps -- two separate
    # `datetime.now()` calls would carry sub-millisecond jitter between them,
    # producing a duration a hair off `duration_seconds` and flaking the
    # exact-median assertions below.
    anchor = datetime.now(timezone.utc)
    task.started_at = anchor - timedelta(seconds=duration_seconds)
    task.completed_at = anchor
    task.state = TaskState.COMPLETED.value
    await session.commit()


@pytest.mark.asyncio
async def test_reports_no_estimate_with_zero_samples(db_session: AsyncSession):
    estimate = await store.estimate_task_duration_seconds(
        db_session, project_id="codexbridge", mode="implement", engine="claude"
    )
    assert estimate == {"eta_seconds": None, "eta_basis": "none", "eta_sample_size": 0}


@pytest.mark.asyncio
async def test_uses_the_narrowest_basis_once_it_has_enough_samples(db_session: AsyncSession):
    for seconds in (100, 200, 300, 400, 500):
        await _seed_completed_task(
            db_session, project_id="codexbridge", mode=TaskMode.IMPLEMENT, engine="claude", duration_seconds=seconds
        )
    estimate = await store.estimate_task_duration_seconds(
        db_session, project_id="codexbridge", mode="implement", engine="claude"
    )
    assert estimate["eta_basis"] == "project+mode+engine"
    assert estimate["eta_sample_size"] == 5
    assert estimate["eta_seconds"] == 300  # median of 100..500


@pytest.mark.asyncio
async def test_widens_to_project_and_mode_when_the_engine_specific_sample_is_too_thin(db_session: AsyncSession):
    for seconds in (100, 200, 300, 400, 500):
        await _seed_completed_task(
            db_session, project_id="codexbridge", mode=TaskMode.IMPLEMENT, engine="codex", duration_seconds=seconds
        )
    # Only 2 samples for the "claude" engine specifically -- below the
    # threshold, so the estimate must widen to project+mode (5 codex + 2
    # claude = 7 samples, still all project=codexbridge, mode=implement).
    for seconds in (50, 60):
        await _seed_completed_task(
            db_session, project_id="codexbridge", mode=TaskMode.IMPLEMENT, engine="claude", duration_seconds=seconds
        )
    estimate = await store.estimate_task_duration_seconds(
        db_session, project_id="codexbridge", mode="implement", engine="claude"
    )
    assert estimate["eta_basis"] == "project+mode"
    assert estimate["eta_sample_size"] == 7


@pytest.mark.asyncio
async def test_widens_to_global_mode_and_finally_to_none(db_session: AsyncSession):
    # A different project/mode entirely -- not enough for any narrower basis,
    # but present for the final "any completed task" fallback.
    for seconds in (10, 20, 30, 40, 50):
        await _seed_completed_task(
            db_session, project_id="jk-structure", mode=TaskMode.ANALYZE, engine="codex", duration_seconds=seconds
        )
    estimate = await store.estimate_task_duration_seconds(
        db_session, project_id="codexbridge", mode="implement", engine="claude"
    )
    assert estimate["eta_basis"] == "global"
    assert estimate["eta_sample_size"] == 5


@pytest.mark.asyncio
async def test_median_not_mean_so_one_outlier_does_not_dominate(db_session: AsyncSession):
    for seconds in (10, 10, 10, 10, 3600):
        await _seed_completed_task(
            db_session, project_id="codexbridge", mode=TaskMode.IMPLEMENT, engine="claude", duration_seconds=seconds
        )
    estimate = await store.estimate_task_duration_seconds(
        db_session, project_id="codexbridge", mode="implement", engine="claude"
    )
    assert estimate["eta_seconds"] == 10
