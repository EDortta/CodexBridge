"""`store.record_discovery_report` -- issue #73 Stage 3.

The gateway-side half of discovery: reconciling one node's per-root
`DiscoveryReport` into `discovered_resources`. Same in-memory-sqlite idiom
`tests/unit/test_node_store.py` uses for `record_node_announcement` -- a real
(in-memory) async engine, no FastAPI app.

Every negative rule below (never regress ADOPTED/AUTHORIZED, never touch
DENIED, never resurrect STALE without cause) is paired with a positive
control in the same test: `docs/napkin-lessons.md`'s 2026-09-01 entry is
explicit that five green tests once proved only that the code they exercised
was unreachable, not that it behaved -- a purely negative assertion cannot
tell "correctly refused" apart from "never ran".
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from gateway.app.db.base import Base
from gateway.app.models.entities import (
    DiscoveredResourceModel,
    ExecutorModel,
    ProjectAuthorizationModel,
    ProjectModel,
)
from gateway.app.services import store
from shared.protocol import (
    Capability,
    DiscoveredCandidate,
    DiscoveredState,
    DiscoveryReport,
    DiscoveryRoot,
    ExecutorRegistration,
)
from shared.security import hash_resource_key


@pytest.fixture
async def db_session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        yield session
    await engine.dispose()


async def _executor(
    session: AsyncSession, executor_id: str = "E1", *, discovery_roots: list[DiscoveryRoot] | None = None
) -> ExecutorModel:
    await store.upsert_registry(
        session,
        executors=[
            ExecutorRegistration(
                executor_id=executor_id,
                display_name=executor_id,
                machine_token="t",
                allowed_projects=[],
                discovery_roots=discovery_roots or [],
            )
        ],
        projects=[],
    )
    return await session.get(ExecutorModel, executor_id)


def _candidate(resource_key: str, **overrides) -> DiscoveredCandidate:
    fields = {
        "resource_key": resource_key,
        "suggested_project_id": resource_key.rsplit("/", 1)[-1],
        "suggested_name": resource_key.rsplit("/", 1)[-1],
        "remote_url": None,
        "head": "abc123",
        "dirty": False,
    }
    fields.update(overrides)
    return DiscoveredCandidate(**fields)


def _report(root_path: str, candidates: list[DiscoveredCandidate], *, scanned_at: datetime | None = None) -> DiscoveryReport:
    return DiscoveryReport(root_path=root_path, candidates=candidates, scanned_at=scanned_at or datetime.now(timezone.utc))


async def _row(session: AsyncSession, node_id: str, path: str) -> DiscoveredResourceModel | None:
    """The row for `path` on `node_id`, matched by `resource_path`.

    Not `resource_key`: since `migrations/0013_discovery_resource_key_hash.
    sql`, that column holds `hash_resource_key(path)`, a lookup key rather
    than the path itself -- see that migration's own comment.
    """
    result = await session.execute(
        select(DiscoveredResourceModel).where(
            DiscoveredResourceModel.node_id == node_id,
            DiscoveredResourceModel.resource_path == path,
        )
    )
    return result.scalars().first()


async def _seed_row(
    session: AsyncSession,
    *,
    node_id: str,
    resource_key: str,
    root_path: str,
    state: str,
    project_id: str | None = None,
    evidence: dict | None = None,
    first_seen_at: datetime | None = None,
    last_seen_at: datetime | None = None,
) -> DiscoveredResourceModel:
    """Seed a row as it would exist after adoption/report work has run.

    `resource_key` here is the candidate's PATH, kept as the parameter name
    across every call site below for a minimal diff -- the column itself
    stores `hash_resource_key(resource_key)`, and the path lives in the new
    `resource_path` column, exactly as `record_discovery_report` writes both
    today.
    """
    now = datetime.now(timezone.utc)
    row = DiscoveredResourceModel(
        id=f"row-{resource_key}",
        node_id=node_id,
        kind="project",
        resource_key=hash_resource_key(resource_key),
        resource_path=resource_key,
        project_id=project_id,
        evidence_json=json.dumps(evidence or {"suggested_project_id": "x"}),
        state=state,
        root_path=root_path,
        first_seen_at=first_seen_at or now,
        last_seen_at=last_seen_at or now,
    )
    session.add(row)
    await session.commit()
    return row


# --------------------------------------------------------------------------
# Rule 1: a new candidate is INSERTed as DISCOVERED
# --------------------------------------------------------------------------


async def test_a_new_candidate_is_inserted_as_discovered(db_session) -> None:
    executor = await _executor(db_session)
    now = datetime.now(timezone.utc)
    report = _report("/root", [_candidate("/root/hub", suggested_project_id="hub", suggested_name="hub")])

    await store.record_discovery_report(db_session, executor, report, now=now)

    row = await _row(db_session, "E1", "/root/hub")
    assert row is not None
    assert row.state == DiscoveredState.DISCOVERED.value
    seen = row.first_seen_at if row.first_seen_at.tzinfo else row.first_seen_at.replace(tzinfo=timezone.utc)
    assert seen == now
    assert row.first_seen_at == row.last_seen_at
    evidence = json.loads(row.evidence_json)
    assert evidence["suggested_project_id"] == "hub"


# --------------------------------------------------------------------------
# Rule 2: an existing candidate refreshes evidence/last_seen_at, never state
# --------------------------------------------------------------------------


async def test_existing_candidate_refreshes_evidence_without_regressing_state(db_session) -> None:
    executor = await _executor(db_session)
    old_seen = datetime.now(timezone.utc) - timedelta(hours=1)
    await _seed_row(
        db_session,
        node_id="E1",
        resource_key="/root/hub",
        root_path="/root",
        state=DiscoveredState.ADOPTED.value,
        evidence={"suggested_project_id": "hub", "head": "old-sha"},
        last_seen_at=old_seen,
    )

    now = datetime.now(timezone.utc)
    report = _report(
        "/root",
        [
            _candidate("/root/hub", suggested_project_id="hub", suggested_name="hub", head="new-sha"),
            # Positive control: a genuinely new candidate in the SAME report
            # still gets inserted -- proves the loop is not a global no-op.
            _candidate("/root/new-repo", suggested_project_id="new-repo", suggested_name="new-repo"),
        ],
    )
    await store.record_discovery_report(db_session, executor, report, now=now)

    hub = await _row(db_session, "E1", "/root/hub")
    assert hub.state == DiscoveredState.ADOPTED.value  # never regressed
    assert json.loads(hub.evidence_json)["head"] == "new-sha"
    seen = hub.last_seen_at if hub.last_seen_at.tzinfo else hub.last_seen_at.replace(tzinfo=timezone.utc)
    assert seen == now

    new_repo = await _row(db_session, "E1", "/root/new-repo")
    assert new_repo is not None
    assert new_repo.state == DiscoveredState.DISCOVERED.value


# --------------------------------------------------------------------------
# Rule 3: a row absent from the current report (and not DENIED) goes STALE
# --------------------------------------------------------------------------


async def test_a_row_missing_from_the_report_becomes_stale(db_session) -> None:
    executor = await _executor(db_session)
    await _seed_row(
        db_session, node_id="E1", resource_key="/root/gone", root_path="/root", state=DiscoveredState.DISCOVERED.value
    )
    await _seed_row(
        db_session, node_id="E1", resource_key="/root/still-here", root_path="/root", state=DiscoveredState.DISCOVERED.value
    )

    report = _report("/root", [_candidate("/root/still-here", suggested_project_id="still-here", suggested_name="s")])
    await store.record_discovery_report(db_session, executor, report)

    gone = await _row(db_session, "E1", "/root/gone")
    assert gone.state == DiscoveredState.STALE.value

    # Positive control: presence prevents staling.
    still_here = await _row(db_session, "E1", "/root/still-here")
    assert still_here.state == DiscoveredState.DISCOVERED.value


async def test_reconciliation_is_scoped_to_the_reports_own_root_path(db_session) -> None:
    """A row for a DIFFERENT root on the same node must not go STALE just

    because this report is about a different root entirely.
    """
    executor = await _executor(db_session)
    await _seed_row(
        db_session,
        node_id="E1",
        resource_key="/other-root/untouched",
        root_path="/other-root",
        state=DiscoveredState.DISCOVERED.value,
    )

    report = _report("/root", [_candidate("/root/hub", suggested_project_id="hub", suggested_name="hub")])
    await store.record_discovery_report(db_session, executor, report)

    untouched = await _row(db_session, "E1", "/other-root/untouched")
    assert untouched.state == DiscoveredState.DISCOVERED.value


# --------------------------------------------------------------------------
# Rule 4: DENIED is never touched by observation, in either direction
# --------------------------------------------------------------------------


async def test_denied_row_is_not_touched_even_when_reported_again(db_session) -> None:
    old_evidence = {"suggested_project_id": "hub", "head": "old-sha"}
    old_seen = datetime.now(timezone.utc) - timedelta(days=1)
    await _seed_row(
        db_session,
        node_id="E1",
        resource_key="/root/hub",
        root_path="/root",
        state=DiscoveredState.DENIED.value,
        evidence=old_evidence,
        last_seen_at=old_seen,
    )
    executor = await _executor(db_session)

    report = _report(
        "/root",
        [
            _candidate("/root/hub", suggested_project_id="hub", suggested_name="hub", head="new-sha"),
            # Positive control: a non-denied candidate in the same report DOES update.
            _candidate("/root/other", suggested_project_id="other", suggested_name="other"),
        ],
    )
    await store.record_discovery_report(db_session, executor, report)

    hub = await _row(db_session, "E1", "/root/hub")
    assert hub.state == DiscoveredState.DENIED.value
    assert json.loads(hub.evidence_json) == old_evidence  # untouched, not just "state unchanged"
    seen = hub.last_seen_at if hub.last_seen_at.tzinfo else hub.last_seen_at.replace(tzinfo=timezone.utc)
    assert abs(seen - old_seen) < timedelta(seconds=1)  # untouched -- not refreshed to "now"

    other = await _row(db_session, "E1", "/root/other")
    assert other is not None
    assert other.state == DiscoveredState.DISCOVERED.value


async def test_denied_row_does_not_regress_to_stale_when_absent(db_session) -> None:
    """The exact bug named in `docs/control-plane.md`: a refused candidate

    must not return to the adoption queue -- here, by going STALE and later
    reappearing as DISCOVERED -- on a reconnect that no longer reports it.
    """
    await _seed_row(
        db_session, node_id="E1", resource_key="/root/hub", root_path="/root", state=DiscoveredState.DENIED.value
    )
    executor = await _executor(db_session)

    report = _report("/root", [])  # hub no longer reported at all
    await store.record_discovery_report(db_session, executor, report)

    hub = await _row(db_session, "E1", "/root/hub")
    assert hub.state == DiscoveredState.DENIED.value


# --------------------------------------------------------------------------
# Rule 5: a STALE row that reappears restores the prior decision, not DISCOVERED
# --------------------------------------------------------------------------


async def test_stale_row_reappearing_with_no_project_reverts_to_discovered(db_session) -> None:
    await _seed_row(
        db_session, node_id="E1", resource_key="/root/hub", root_path="/root", state=DiscoveredState.STALE.value
    )
    executor = await _executor(db_session)

    report = _report("/root", [_candidate("/root/hub", suggested_project_id="hub", suggested_name="hub")])
    await store.record_discovery_report(db_session, executor, report)

    hub = await _row(db_session, "E1", "/root/hub")
    assert hub.state == DiscoveredState.DISCOVERED.value


async def test_stale_row_reappearing_with_active_authorization_reverts_to_authorized(db_session) -> None:
    await _seed_row(
        db_session,
        node_id="E1",
        resource_key="/root/hub",
        root_path="/root",
        state=DiscoveredState.STALE.value,
        project_id="p1",
    )
    db_session.add(
        ProjectAuthorizationModel(
            id="auth-1",
            node_id="E1",
            project_id="p1",
            capabilities_json="[\"read\"]",
            granted_by="operator:esteban",
            granted_at=datetime.now(timezone.utc),
            revoked_at=None,
        )
    )
    await db_session.commit()
    executor = await _executor(db_session)

    report = _report("/root", [_candidate("/root/hub", suggested_project_id="hub", suggested_name="hub")])
    await store.record_discovery_report(db_session, executor, report)

    hub = await _row(db_session, "E1", "/root/hub")
    assert hub.state == DiscoveredState.AUTHORIZED.value


async def test_stale_row_reappearing_with_only_a_revoked_authorization_reverts_to_adopted(db_session) -> None:
    """The negative half of the pair above: a REVOKED authorization must not

    count -- the row goes back to ADOPTED (the binding decision survives),
    not AUTHORIZED (which the operator specifically took away).
    """
    await _seed_row(
        db_session,
        node_id="E1",
        resource_key="/root/hub",
        root_path="/root",
        state=DiscoveredState.STALE.value,
        project_id="p1",
    )
    db_session.add(
        ProjectAuthorizationModel(
            id="auth-1",
            node_id="E1",
            project_id="p1",
            capabilities_json="[\"read\"]",
            granted_by="operator:esteban",
            granted_at=datetime.now(timezone.utc) - timedelta(days=2),
            revoked_at=datetime.now(timezone.utc) - timedelta(days=1),
        )
    )
    await db_session.commit()
    executor = await _executor(db_session)

    report = _report("/root", [_candidate("/root/hub", suggested_project_id="hub", suggested_name="hub")])
    await store.record_discovery_report(db_session, executor, report)

    hub = await _row(db_session, "E1", "/root/hub")
    assert hub.state == DiscoveredState.ADOPTED.value


# --------------------------------------------------------------------------
# Structural property: discovery never touches authorization or projects
# --------------------------------------------------------------------------


async def test_record_discovery_report_never_writes_authorization_or_projects(db_session) -> None:
    """The property that makes "the node proposes, the panel adopts" true by

    construction: this function has no code path to either table at all.
    """
    executor = await _executor(db_session)
    db_session.add(ProjectModel(id="p1", name="Existing Project", path="/srv/p1", enabled=True))
    db_session.add(
        ProjectAuthorizationModel(
            id="auth-1",
            node_id="E1",
            project_id="p1",
            capabilities_json="[\"read\"]",
            granted_by="operator:esteban",
            granted_at=datetime.now(timezone.utc),
        )
    )
    await db_session.commit()

    projects_before = (await db_session.execute(select(ProjectModel))).scalars().all()
    authorizations_before = (await db_session.execute(select(ProjectAuthorizationModel))).scalars().all()
    projects_before_dump = [(p.id, p.name, p.path, p.enabled) for p in projects_before]
    authorizations_before_dump = [
        (a.id, a.node_id, a.project_id, a.capabilities_json, a.revoked_at) for a in authorizations_before
    ]

    report = _report(
        "/root",
        [_candidate(f"/root/repo-{i}", suggested_project_id=f"repo-{i}", suggested_name=f"repo-{i}") for i in range(20)],
    )
    await store.record_discovery_report(db_session, executor, report)

    projects_after = (await db_session.execute(select(ProjectModel))).scalars().all()
    authorizations_after = (await db_session.execute(select(ProjectAuthorizationModel))).scalars().all()
    projects_after_dump = [(p.id, p.name, p.path, p.enabled) for p in projects_after]
    authorizations_after_dump = [
        (a.id, a.node_id, a.project_id, a.capabilities_json, a.revoked_at) for a in authorizations_after
    ]

    assert projects_after_dump == projects_before_dump
    assert authorizations_after_dump == authorizations_before_dump


async def test_a_matching_auto_authorize_root_grants_nothing_from_a_report_alone(db_session) -> None:
    """The invariant this PR must not break: a node cannot authorize itself.

    `E1`'s own registration names a `DiscoveryRoot` at `/root` with
    `auto_authorize=[read]` -- exactly the configuration
    `adopt_discovered_resource` reads to grant standing capability on
    adoption. Reporting a candidate under that root is the ONLY thing this
    test does; `record_discovery_report` never looks at `discovery_roots`
    at all, so `project_authorizations` must still be empty afterward no
    matter what the registration would have permitted, once a human adopts.

    Positive control: the same setup, adopted through `store.
    adopt_discovered_resource`, DOES grant -- proving the negative above is
    "never reachable from a report", not "never reachable at all" (the
    2026-09-01 lesson `docs/napkin-lessons.md` names).
    """
    executor = await _executor(
        db_session, discovery_roots=[DiscoveryRoot(path="/root", auto_authorize=[Capability.READ])]
    )
    report = _report("/root", [_candidate("/root/hub", suggested_project_id="hub", suggested_name="hub")])

    await store.record_discovery_report(db_session, executor, report)

    authorizations = (await db_session.execute(select(ProjectAuthorizationModel))).scalars().all()
    assert authorizations == []

    hub = await _row(db_session, "E1", "/root/hub")
    adopted = await store.adopt_discovered_resource(
        db_session,
        hub.id,
        project_id=None,
        new_project_id="hub",
        new_project_name="hub",
        grant_capabilities=[],
        actor_user_id="esteban",
    )
    assert adopted.state == DiscoveredState.AUTHORIZED.value
    granted = (await db_session.execute(select(ProjectAuthorizationModel))).scalars().all()
    assert len(granted) == 1
    assert granted[0].granted_by == "root-config:/root"
    assert json.loads(granted[0].capabilities_json) == ["read"]


# --------------------------------------------------------------------------
# resource_key / resource_path: the migration 0013 defect and its fix
# --------------------------------------------------------------------------


async def test_resource_key_is_a_fixed_width_hash_and_resource_path_carries_the_real_path(db_session) -> None:
    """The defect this PR fixes: a MySQL `varchar(255)` cannot hold every

    path `DiscoveredCandidate.resource_key` allows (up to 2048 characters).
    A candidate at that width must still round-trip cleanly.
    """
    executor = await _executor(db_session)
    long_path = "/root/" + ("a" * 2000)
    report = _report(
        "/root", [_candidate(long_path, suggested_project_id="deep", suggested_name="deep")]
    )

    await store.record_discovery_report(db_session, executor, report)

    row = await _row(db_session, "E1", long_path)
    assert row is not None
    assert row.resource_path == long_path
    assert row.resource_key == hash_resource_key(long_path)
    assert len(row.resource_key) == 64  # sha256 hex -- comfortably under varchar(255)


async def test_a_pre_migration_row_self_heals_its_resource_key_on_next_report(db_session) -> None:
    """A row written before 0013 has `resource_key` = the raw path (the

    migration's backfill copies it into `resource_path` and leaves
    `resource_key` untouched -- see that file's own comment). The next time
    its node reports the same path, `record_discovery_report` must still
    recognise it (matched by `resource_path`, not `resource_key`) and repair
    `resource_key` to the hash, rather than reading it as new and
    duplicating the row.
    """
    executor = await _executor(db_session)
    legacy = DiscoveredResourceModel(
        id="legacy-row",
        node_id="E1",
        kind="project",
        resource_key="/root/hub",  # pre-0013 shape: the raw path, unhashed
        resource_path="/root/hub",  # what the migration's backfill sets
        evidence_json=json.dumps({"suggested_project_id": "hub"}),
        state=DiscoveredState.DISCOVERED.value,
        root_path="/root",
        first_seen_at=datetime.now(timezone.utc) - timedelta(days=1),
        last_seen_at=datetime.now(timezone.utc) - timedelta(days=1),
    )
    db_session.add(legacy)
    await db_session.commit()

    report = _report("/root", [_candidate("/root/hub", suggested_project_id="hub", suggested_name="hub")])
    await store.record_discovery_report(db_session, executor, report)

    rows = (
        (await db_session.execute(select(DiscoveredResourceModel).where(DiscoveredResourceModel.node_id == "E1")))
        .scalars()
        .all()
    )
    assert len(rows) == 1, "the legacy row must be updated in place, never duplicated"
    assert rows[0].resource_key == hash_resource_key("/root/hub")
    assert rows[0].resource_path == "/root/hub"


# --------------------------------------------------------------------------
# Batch behaviour: many candidates, not one round trip each
# --------------------------------------------------------------------------


async def test_a_large_report_does_not_cost_one_round_trip_per_candidate(db_session) -> None:
    """247 candidates -- the real root that motivated this work, rounded up

    to 250 -- must not cost 250 `SELECT`s or 250 commits. `record_discovery_
    report`'s own docstring promises exactly one of each; this asserts it.
    """
    executor = await _executor(db_session)
    report = _report(
        "/root",
        [_candidate(f"/root/repo-{i}", suggested_project_id=f"repo-{i}", suggested_name=f"repo-{i}") for i in range(250)],
    )

    execute_calls = 0
    commit_calls = 0
    original_execute = AsyncSession.execute
    original_commit = AsyncSession.commit

    async def counting_execute(self, *args, **kwargs):
        nonlocal execute_calls
        execute_calls += 1
        return await original_execute(self, *args, **kwargs)

    async def counting_commit(self, *args, **kwargs):
        nonlocal commit_calls
        commit_calls += 1
        return await original_commit(self, *args, **kwargs)

    AsyncSession.execute = counting_execute
    AsyncSession.commit = counting_commit
    try:
        await store.record_discovery_report(db_session, executor, report)
    finally:
        AsyncSession.execute = original_execute
        AsyncSession.commit = original_commit

    # One SELECT to load existing rows for this (node, root); one COMMIT to
    # persist all 250 inserts together. Nowhere near 250 of either.
    assert execute_calls <= 2, f"expected O(1) session.execute calls, got {execute_calls}"
    assert commit_calls == 1

    rows = (await db_session.execute(select(DiscoveredResourceModel))).scalars().all()
    assert len(rows) == 250
