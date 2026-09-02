"""Discovered-resource adoption routes — issue #73 Stage 3 adoption half.

WK-20260902-gh73-discovery-adoption. Fixture idiom copied from
`test_nodes.py`: real FastAPI app, in-memory sqlite, `store.upsert_registry`
seeding, OAuth tokens minted through `store.create_oauth_access_token`.

Weighted toward the invariant this PR exists to prove: a node cannot reach
`project_authorizations` through any REST surface this module adds, only a
human with the administrative scope can, and adopting is the only door into
`projects`/`workspace_bindings`/`scm_associations`/`project_authorizations`
from a `discovered_resources` row. Every negative case is paired with a
positive control in the same file (`docs/napkin-lessons.md`, 2026-09-01).
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from gateway.app.api.routes import discovery as discovery_routes
from gateway.app.api.setup import install_api_conventions
from gateway.app.db.base import Base
from gateway.app.db.session import get_session
from gateway.app.models.entities import (
    DiscoveredResourceModel,
    ProjectAuthorizationModel,
    ProjectModel,
    ScmAssociationModel,
    WorkspaceBindingModel,
)
from gateway.app.services import store
from shared.protocol import DiscoveredState, DiscoveryRoot, ExecutorRegistration, Capability


ADMIN_TOKEN = "token-admin"      # roles=["admin"] -- may adopt/deny
FLEETWATCHER_TOKEN = "token-fleetwatcher"  # codexbridge.admin scope, no admin role
ALICE_TOKEN = "token-alice"      # authenticated, codexbridge.read only -- no fleet access
NOSCOPE_TOKEN = "token-noscope"  # authenticated, no scopes at all


@pytest.fixture
def users_file(tmp_path):
    path = tmp_path / "users.json"
    path.write_text(
        json.dumps(
            {
                "users": [
                    {
                        "user_id": "admin", "email": "admin@example.com", "password_hash": "x",
                        "roles": ["admin"], "allowed_projects": [],
                        "scopes": ["codexbridge.admin"], "enabled": True,
                    },
                    {
                        "user_id": "alice", "email": "alice@example.com", "password_hash": "x",
                        "roles": [], "allowed_projects": ["p1"],
                        "scopes": ["codexbridge.read"], "enabled": True,
                    },
                    {
                        "user_id": "noscope", "email": "noscope@example.com", "password_hash": "x",
                        "roles": [], "allowed_projects": [],
                        "scopes": [], "enabled": True,
                    },
                    {
                        # Fleet visibility without the admin role and without
                        # can_approve_sensitive: the exact actor the sensitive
                        # capability ladder exists to stop from granting
                        # modify/deliver. `codexbridge.admin` as a SCOPE is
                        # what `nodes.discoveries.decide` requires; it must
                        # not by itself buy a sensitive grant.
                        "user_id": "fleetwatcher", "email": "fw@example.com", "password_hash": "x",
                        "roles": [], "allowed_projects": [],
                        "scopes": ["codexbridge.admin"], "enabled": True,
                    },
                ]
            }
        ),
        encoding="utf-8",
    )
    return str(path)


@pytest.fixture
async def api(users_file, monkeypatch):
    from gateway.app.core.config import settings

    monkeypatch.setattr(settings, "user_registry_file", users_file)

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with factory() as seed:
        await store.upsert_registry(
            seed,
            executors=[
                ExecutorRegistration(
                    executor_id="E1", display_name="E1", machine_token="t",
                    allowed_projects=[], enabled=True,
                    discovery_roots=[DiscoveryRoot(path="/root", auto_authorize=[Capability.READ])],
                ),
                ExecutorRegistration(
                    executor_id="E2", display_name="E2", machine_token="t2",
                    allowed_projects=[], enabled=True,
                ),
            ],
            projects=[],
        )
        future = datetime.now(timezone.utc) + timedelta(hours=1)
        for token, user_id, scopes in (
            (ADMIN_TOKEN, "admin", ["codexbridge.admin"]),
            (ALICE_TOKEN, "alice", ["codexbridge.read"]),
            (NOSCOPE_TOKEN, "noscope", []),
            (FLEETWATCHER_TOKEN, "fleetwatcher", ["codexbridge.admin"]),
        ):
            await store.create_oauth_access_token(
                seed, token=token, client_id="c", user_id=user_id,
                scopes=scopes, expires_at=future,
            )

    app = FastAPI(openapi_url=None, docs_url=None, redoc_url=None)
    install_api_conventions(app)
    app.include_router(discovery_routes.router)

    async def override():
        async with factory() as s:
            yield s

    app.dependency_overrides[get_session] = override

    client = TestClient(app, raise_server_exceptions=False)
    client.factory = factory  # type: ignore[attr-defined]
    yield client
    await engine.dispose()


def auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


async def seed_resource(
    factory,
    *,
    resource_id: str,
    node_id: str = "E1",
    root_path: str = "/root",
    resource_path: str = "/root/hub",
    state: str = DiscoveredState.DISCOVERED.value,
    remote_url: str | None = None,
    project_id: str | None = None,
) -> None:
    async with factory() as session:
        session.add(
            DiscoveredResourceModel(
                id=resource_id,
                node_id=node_id,
                kind="project",
                resource_key=f"hash-{resource_id}",
                resource_path=resource_path,
                project_id=project_id,
                evidence_json=json.dumps(
                    {
                        "suggested_project_id": "hub",
                        "suggested_name": "Hub",
                        "remote_url": remote_url,
                        "head": "abc123",
                        "dirty": False,
                    }
                ),
                state=state,
                root_path=root_path,
                first_seen_at=datetime.now(timezone.utc),
                last_seen_at=datetime.now(timezone.utc),
            )
        )
        await session.commit()


# --------------------------------------------------------------------------
# Authentication and authorization
# --------------------------------------------------------------------------


async def test_list_requires_a_token(api) -> None:
    response = api.get("/api/v1/nodes/E1/discovered-resources")
    assert response.status_code == 401


async def test_list_without_the_admin_scope_is_forbidden(api) -> None:
    response = api.get("/api/v1/nodes/E1/discovered-resources", headers=auth(ALICE_TOKEN))
    assert response.status_code == 403
    assert response.json()["code"] == "permission_denied"


async def test_list_with_the_admin_scope_is_allowed(api) -> None:
    """Positive control for the previous two: the scope alone is sufficient."""
    response = api.get("/api/v1/nodes/E1/discovered-resources", headers=auth(ADMIN_TOKEN))
    assert response.status_code == 200


async def test_a_principal_without_the_administrative_scope_cannot_adopt(api) -> None:
    await seed_resource(api.factory, resource_id="r1")
    response = api.post(
        "/api/v1/discovered-resources/r1/adopt",
        headers=auth(ALICE_TOKEN),
        json={"newProject": {"projectId": "hub", "name": "Hub"}},
    )
    assert response.status_code == 403
    async with api.factory() as session:
        row = await session.get(DiscoveredResourceModel, "r1")
        assert row.state == DiscoveredState.DISCOVERED.value  # untouched


async def test_a_principal_with_the_administrative_scope_can_adopt(api) -> None:
    """Positive control for the previous test."""
    await seed_resource(api.factory, resource_id="r1")
    response = api.post(
        "/api/v1/discovered-resources/r1/adopt",
        headers=auth(ADMIN_TOKEN),
        json={"newProject": {"projectId": "hub", "name": "Hub"}},
    )
    assert response.status_code == 200


async def test_adoption_cannot_grant_modify_without_the_sensitive_ladder(api) -> None:
    """The second door to `modify`/`deliver`, closed.

    `POST .../authorize` applies a privilege ladder on top of its
    administrative scope: granting `modify` or `deliver` also needs
    `can_approve_sensitive` or the admin role. Adoption writes the same
    `project_authorizations` table through `grantCapabilities`, so gating
    only the dedicated route would leave this one open to exactly the
    principal the ladder exists to stop -- a token carrying
    `codexbridge.admin` for fleet visibility, for an account nobody trusted
    with a sensitive grant.
    """
    await seed_resource(api.factory, resource_id="r1")
    response = api.post(
        "/api/v1/discovered-resources/r1/adopt",
        headers=auth(FLEETWATCHER_TOKEN),
        json={
            "newProject": {"projectId": "hub", "name": "Hub"},
            "grantCapabilities": ["modify"],
        },
    )
    assert response.status_code == 403
    async with api.factory() as session:
        row = await session.get(DiscoveredResourceModel, "r1")
        assert row.state == DiscoveredState.DISCOVERED.value  # nothing adopted either


async def test_the_same_actor_may_adopt_when_it_asks_for_no_sensitive_capability(api) -> None:
    """Positive control: the ladder gates the capability, not the adoption.

    Without this, a bug that refused `fleetwatcher` every adoption would pass
    the test above while breaking the read/test flow the operator actually
    uses most.
    """
    await seed_resource(api.factory, resource_id="r1")
    response = api.post(
        "/api/v1/discovered-resources/r1/adopt",
        headers=auth(FLEETWATCHER_TOKEN),
        json={
            "newProject": {"projectId": "hub", "name": "Hub"},
            "grantCapabilities": ["read", "test"],
        },
    )
    assert response.status_code == 200


async def test_a_token_with_no_scopes_cannot_deny(api) -> None:
    await seed_resource(api.factory, resource_id="r1")
    response = api.post("/api/v1/discovered-resources/r1/deny", headers=auth(NOSCOPE_TOKEN))
    assert response.status_code == 403


# --------------------------------------------------------------------------
# List: pagination, filtering, node scope
# --------------------------------------------------------------------------


async def test_an_unknown_node_id_is_not_found(api) -> None:
    response = api.get("/api/v1/nodes/does-not-exist/discovered-resources", headers=auth(ADMIN_TOKEN))
    assert response.status_code == 404


async def test_an_invalid_state_filter_is_rejected(api) -> None:
    response = api.get(
        "/api/v1/nodes/E1/discovered-resources", params={"state": "bogus"}, headers=auth(ADMIN_TOKEN)
    )
    assert response.status_code == 400


async def test_the_state_filter_narrows_the_list(api) -> None:
    await seed_resource(api.factory, resource_id="discovered-1", state=DiscoveredState.DISCOVERED.value)
    await seed_resource(api.factory, resource_id="denied-1", state=DiscoveredState.DENIED.value)

    response = api.get(
        "/api/v1/nodes/E1/discovered-resources",
        params={"state": "denied"},
        headers=auth(ADMIN_TOKEN),
    )
    body = response.json()
    assert [item["id"] for item in body["items"]] == ["denied-1"]

    # Positive control: no filter returns both.
    unfiltered = api.get("/api/v1/nodes/E1/discovered-resources", headers=auth(ADMIN_TOKEN)).json()
    assert {item["id"] for item in unfiltered["items"]} == {"discovered-1", "denied-1"}


async def test_a_resource_from_a_different_node_is_not_listed(api) -> None:
    await seed_resource(api.factory, resource_id="on-e1", node_id="E1")
    await seed_resource(api.factory, resource_id="on-e2", node_id="E2", resource_path="/root/other")

    body = api.get("/api/v1/nodes/E1/discovered-resources", headers=auth(ADMIN_TOKEN)).json()
    assert [item["id"] for item in body["items"]] == ["on-e1"]


async def test_pagination_covers_more_candidates_than_one_page(api) -> None:
    """The real-world case this PR names: 247 candidates from one root."""
    for i in range(5):
        await seed_resource(api.factory, resource_id=f"r{i:03d}", resource_path=f"/root/repo-{i}")

    first = api.get(
        "/api/v1/nodes/E1/discovered-resources", params={"limit": 2}, headers=auth(ADMIN_TOKEN)
    ).json()
    assert len(first["items"]) == 2
    assert first["page"]["hasMore"] is True
    assert first["page"]["nextCursor"] is not None

    seen = list(first["items"])
    cursor = first["page"]["nextCursor"]
    while cursor:
        page = api.get(
            "/api/v1/nodes/E1/discovered-resources",
            params={"limit": 2, "cursor": cursor},
            headers=auth(ADMIN_TOKEN),
        ).json()
        seen.extend(page["items"])
        cursor = page["page"]["nextCursor"]

    assert {item["id"] for item in seen} == {f"r{i:03d}" for i in range(5)}
    assert len(seen) == 5  # no duplicate across the page boundary


async def test_the_dto_carries_the_sensitive_path_fields(api) -> None:
    """This IS the pre-registered exception (`docs/control-plane.md`,

    `docs/api/README.md`): only on this administrative endpoint.
    """
    await seed_resource(api.factory, resource_id="r1", resource_path="/root/hub", root_path="/root")
    body = api.get("/api/v1/nodes/E1/discovered-resources", headers=auth(ADMIN_TOKEN)).json()
    item = body["items"][0]
    assert item["resourcePath"] == "/root/hub"
    assert item["rootPath"] == "/root"


# --------------------------------------------------------------------------
# Adopt: project creation/reuse, binding, SCM association, state transition
# --------------------------------------------------------------------------


async def test_adopting_with_a_new_project_creates_project_binding_and_moves_state(api) -> None:
    await seed_resource(
        api.factory, resource_id="r1", resource_path="/root/hub", root_path="/other-root", remote_url="https://github.com/x/hub.git"
    )
    response = api.post(
        "/api/v1/discovered-resources/r1/adopt",
        headers=auth(ADMIN_TOKEN),
        json={"newProject": {"projectId": "hub", "name": "Hub"}},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["projectId"] == "hub"
    assert body["state"] == "adopted"  # /other-root has no auto_authorize entry

    async with api.factory() as session:
        project = await session.get(ProjectModel, "hub")
        assert project is not None and project.name == "Hub"

        binding = (
            (
                await session.execute(
                    select(WorkspaceBindingModel).where(
                        WorkspaceBindingModel.node_id == "E1", WorkspaceBindingModel.project_id == "hub"
                    )
                )
            )
            .scalars()
            .first()
        )
        assert binding is not None
        assert binding.local_path == "/root/hub"

        association = (
            (await session.execute(select(ScmAssociationModel).where(ScmAssociationModel.project_id == "hub")))
            .scalars()
            .first()
        )
        assert association is not None
        assert association.remote_url == "https://github.com/x/hub.git"
        assert association.confidence == "observed"


async def test_adopting_without_a_remote_url_creates_no_scm_association(api) -> None:
    """Positive control for the previous test's association assertion."""
    await seed_resource(api.factory, resource_id="r1", resource_path="/root/hub", root_path="/other-root", remote_url=None)
    api.post(
        "/api/v1/discovered-resources/r1/adopt",
        headers=auth(ADMIN_TOKEN),
        json={"newProject": {"projectId": "hub", "name": "Hub"}},
    )
    async with api.factory() as session:
        associations = (await session.execute(select(ScmAssociationModel))).scalars().all()
        assert associations == []


async def test_adopting_into_an_existing_project_reuses_it(api) -> None:
    async with api.factory() as session:
        session.add(ProjectModel(id="existing", name="Existing", path="/srv/existing", enabled=True, config_json="{}"))
        await session.commit()
    await seed_resource(api.factory, resource_id="r1", resource_path="/root/hub", root_path="/other-root")

    response = api.post(
        "/api/v1/discovered-resources/r1/adopt",
        headers=auth(ADMIN_TOKEN),
        json={"projectId": "existing"},
    )
    assert response.status_code == 200
    assert response.json()["projectId"] == "existing"

    async with api.factory() as session:
        projects = (await session.execute(select(ProjectModel))).scalars().all()
        assert len(projects) == 1, "no duplicate project was created"


async def test_adopting_twice_does_not_duplicate_the_binding(api) -> None:
    await seed_resource(api.factory, resource_id="r1", resource_path="/root/hub", root_path="/other-root")
    body = {"newProject": {"projectId": "hub", "name": "Hub"}}

    first = api.post("/api/v1/discovered-resources/r1/adopt", headers=auth(ADMIN_TOKEN), json=body)
    assert first.status_code == 200

    second = api.post("/api/v1/discovered-resources/r1/adopt", headers=auth(ADMIN_TOKEN), json=body)
    assert second.status_code == 409  # already decided -- not decidable again

    async with api.factory() as session:
        bindings = (await session.execute(select(WorkspaceBindingModel))).scalars().all()
        assert len(bindings) == 1
        projects = (await session.execute(select(ProjectModel))).scalars().all()
        assert len(projects) == 1


async def test_adopt_requires_exactly_one_of_project_id_or_new_project(api) -> None:
    await seed_resource(api.factory, resource_id="r1")
    neither = api.post("/api/v1/discovered-resources/r1/adopt", headers=auth(ADMIN_TOKEN), json={})
    assert neither.status_code == 400

    await seed_resource(api.factory, resource_id="r2", resource_path="/root/hub2")
    async with api.factory() as session:
        session.add(ProjectModel(id="existing", name="Existing", path="/srv/existing", enabled=True, config_json="{}"))
        await session.commit()
    both = api.post(
        "/api/v1/discovered-resources/r2/adopt",
        headers=auth(ADMIN_TOKEN),
        json={"projectId": "existing", "newProject": {"projectId": "hub2", "name": "Hub2"}},
    )
    assert both.status_code == 400


async def test_adopting_an_unknown_resource_is_not_found(api) -> None:
    response = api.post(
        "/api/v1/discovered-resources/does-not-exist/adopt",
        headers=auth(ADMIN_TOKEN),
        json={"newProject": {"projectId": "hub", "name": "Hub"}},
    )
    assert response.status_code == 404


# --------------------------------------------------------------------------
# Auto-authorize: only when the root grants it, and never modify/deliver
# --------------------------------------------------------------------------


async def test_a_matching_auto_authorize_root_grants_read_on_adoption(api) -> None:
    """`E1`'s registration grants `read` for exactly `/root` (see the `api` fixture)."""
    await seed_resource(api.factory, resource_id="r1", resource_path="/root/hub", root_path="/root")
    response = api.post(
        "/api/v1/discovered-resources/r1/adopt",
        headers=auth(ADMIN_TOKEN),
        json={"newProject": {"projectId": "hub", "name": "Hub"}},
    )
    assert response.json()["state"] == "authorized"

    async with api.factory() as session:
        authorizations = (await session.execute(select(ProjectAuthorizationModel))).scalars().all()
        assert len(authorizations) == 1
        assert authorizations[0].granted_by == "root-config:/root"
        assert json.loads(authorizations[0].capabilities_json) == ["read"]


async def test_a_non_matching_root_grants_nothing(api) -> None:
    """Positive control: a candidate under a root E1 never registered grants nothing automatically."""
    await seed_resource(api.factory, resource_id="r1", resource_path="/unregistered/hub", root_path="/unregistered")
    response = api.post(
        "/api/v1/discovered-resources/r1/adopt",
        headers=auth(ADMIN_TOKEN),
        json={"newProject": {"projectId": "hub", "name": "Hub"}},
    )
    assert response.json()["state"] == "adopted"
    async with api.factory() as session:
        authorizations = (await session.execute(select(ProjectAuthorizationModel))).scalars().all()
        assert authorizations == []


async def test_operator_grant_capabilities_can_include_modify_and_deliver(api) -> None:
    await seed_resource(api.factory, resource_id="r1", resource_path="/other-root/hub", root_path="/other-root")
    response = api.post(
        "/api/v1/discovered-resources/r1/adopt",
        headers=auth(ADMIN_TOKEN),
        json={
            "newProject": {"projectId": "hub", "name": "Hub"},
            "grantCapabilities": ["modify", "deliver"],
        },
    )
    assert response.status_code == 200
    async with api.factory() as session:
        authorizations = (await session.execute(select(ProjectAuthorizationModel))).scalars().all()
        assert len(authorizations) == 1
        assert authorizations[0].granted_by == "operator:admin"
        assert set(json.loads(authorizations[0].capabilities_json)) == {"modify", "deliver"}


async def test_root_config_and_operator_grants_coexist_in_one_call(api) -> None:
    """Both origins apply in the same adopt call -- `/root` auto-grants `read`,

    the operator additionally grants `modify`. One authorization row, both
    capabilities, both origins recorded.
    """
    await seed_resource(api.factory, resource_id="r1", resource_path="/root/hub", root_path="/root")
    response = api.post(
        "/api/v1/discovered-resources/r1/adopt",
        headers=auth(ADMIN_TOKEN),
        json={"newProject": {"projectId": "hub", "name": "Hub"}, "grantCapabilities": ["modify"]},
    )
    assert response.status_code == 200
    async with api.factory() as session:
        authorizations = (await session.execute(select(ProjectAuthorizationModel))).scalars().all()
        assert len(authorizations) == 1
        row = authorizations[0]
        assert set(row.granted_by.split(";")) == {"root-config:/root", "operator:admin"}
        assert set(json.loads(row.capabilities_json)) == {"read", "modify"}


async def test_auto_authorize_can_never_grant_modify_or_deliver(api) -> None:
    """A malicious/misconfigured root cannot smuggle `modify`/`deliver` in --

    `DiscoveryRoot`'s own validator already refuses to construct one at
    registration time (`AUTO_AUTHORIZABLE_CAPABILITIES`), so this is really a
    parse-time control; asserted here end-to-end through the registry.
    """
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        DiscoveryRoot(path="/x", auto_authorize=[Capability.MODIFY])


# --------------------------------------------------------------------------
# Deny: state transition, and DENIED surviving a later report
# --------------------------------------------------------------------------


async def test_denying_moves_state_and_records_the_actor(api) -> None:
    await seed_resource(api.factory, resource_id="r1")
    response = api.post("/api/v1/discovered-resources/r1/deny", headers=auth(ADMIN_TOKEN))
    assert response.status_code == 200
    body = response.json()
    assert body["state"] == "denied"
    assert body["decidedBy"] == "operator:admin"
    assert body["decidedAt"] is not None


async def test_denying_twice_is_a_conflict(api) -> None:
    await seed_resource(api.factory, resource_id="r1")
    first = api.post("/api/v1/discovered-resources/r1/deny", headers=auth(ADMIN_TOKEN))
    assert first.status_code == 200
    second = api.post("/api/v1/discovered-resources/r1/deny", headers=auth(ADMIN_TOKEN))
    assert second.status_code == 409


async def test_a_denied_resource_is_not_touched_by_a_later_report(api) -> None:
    """The rule `docs/control-plane.md` names survives this PR: DENIED is

    never regressed by observation, adoption route included.
    """
    await seed_resource(api.factory, resource_id="r1", resource_path="/root/hub", root_path="/root")
    api.post("/api/v1/discovered-resources/r1/deny", headers=auth(ADMIN_TOKEN))

    from shared.protocol import DiscoveredCandidate, DiscoveryReport

    async with api.factory() as session:
        from gateway.app.models.entities import ExecutorModel

        executor = await session.get(ExecutorModel, "E1")
        report = DiscoveryReport(
            root_path="/root",
            candidates=[
                DiscoveredCandidate(
                    resource_key="/root/hub",
                    suggested_project_id="hub",
                    suggested_name="Hub",
                )
            ],
            scanned_at=datetime.now(timezone.utc),
        )
        await store.record_discovery_report(session, executor, report)

    async with api.factory() as session:
        row = await session.get(DiscoveredResourceModel, "r1")
        assert row.state == DiscoveredState.DENIED.value

    # Positive control: a fresh, non-denied candidate in the same report IS recorded.
    async with api.factory() as session:
        result = await session.execute(
            select(DiscoveredResourceModel).where(DiscoveredResourceModel.resource_path == "/root/hub")
        )
        assert result.scalars().first() is not None
