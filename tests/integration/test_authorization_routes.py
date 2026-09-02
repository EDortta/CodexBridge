"""`POST .../authorize` and `.../revoke` -- issue #73 Stage 4.

WK-20260902-gh73-authorization-plane. Fixture idiom copied from
`test_discovery_routes.py`: real FastAPI app, in-memory sqlite, `store.
upsert_registry` seeding, OAuth tokens minted through `store.
create_oauth_access_token`.

Weighted toward the privilege ladder this PR adds: granting `modify`/
`deliver` requires `can_approve_sensitive` or a REAL `"admin"` role on top of
the base `nodes.authorizations.manage` scope -- see `permissions.is_allowed`'s
own docstring for why that second gate reads `"admin" in principal.roles`
rather than `principal.is_admin()`. Every negative case is paired with a
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

from gateway.app.api.routes import authorizations as authorizations_routes
from gateway.app.api.setup import install_api_conventions
from gateway.app.db.base import Base
from gateway.app.db.session import get_session
from gateway.app.models.entities import AuditEventModel, ProjectAuthorizationModel, ProjectModel
from gateway.app.services import store
from shared.protocol import ExecutorRegistration


# `codexbridge.admin` alone, no real admin role, no `can_approve_sensitive` --
# enough for the base gate, never enough for `modify`/`deliver`.
ADMIN_SCOPE_TOKEN = "token-admin-scope"
# A real admin role -- clears both gates via the role check.
ROLE_ADMIN_TOKEN = "token-role-admin"
# `codexbridge.admin` plus `can_approve_sensitive`, no admin role -- clears
# both gates via the sensitive-approval flag.
SENSITIVE_APPROVER_TOKEN = "token-sensitive-approver"
# Authenticated, no admin scope at all -- refused by the base gate itself.
ALICE_TOKEN = "token-alice"


@pytest.fixture
def users_file(tmp_path):
    path = tmp_path / "users.json"
    path.write_text(
        json.dumps(
            {
                "users": [
                    {
                        "user_id": "scoped-admin", "email": "scoped-admin@example.com", "password_hash": "x",
                        "roles": [], "allowed_projects": [],
                        "scopes": ["codexbridge.admin"], "can_approve_sensitive": False, "enabled": True,
                    },
                    {
                        "user_id": "role-admin", "email": "role-admin@example.com", "password_hash": "x",
                        "roles": ["admin"], "allowed_projects": [],
                        "scopes": ["codexbridge.admin"], "can_approve_sensitive": False, "enabled": True,
                    },
                    {
                        "user_id": "sensitive-approver", "email": "sensitive-approver@example.com", "password_hash": "x",
                        "roles": [], "allowed_projects": [],
                        "scopes": ["codexbridge.admin"], "can_approve_sensitive": True, "enabled": True,
                    },
                    {
                        "user_id": "alice", "email": "alice@example.com", "password_hash": "x",
                        "roles": [], "allowed_projects": ["p1"],
                        "scopes": ["codexbridge.read"], "can_approve_sensitive": False, "enabled": True,
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
                    executor_id="E1", display_name="E1", machine_token="t", allowed_projects=[], enabled=True,
                ),
            ],
            projects=[],
        )
        seed.add(ProjectModel(id="p1", name="P1", path="/srv/p1", enabled=True, config_json="{}"))
        await seed.commit()

        future = datetime.now(timezone.utc) + timedelta(hours=1)
        for token, user_id in (
            (ADMIN_SCOPE_TOKEN, "scoped-admin"),
            (ROLE_ADMIN_TOKEN, "role-admin"),
            (SENSITIVE_APPROVER_TOKEN, "sensitive-approver"),
            (ALICE_TOKEN, "alice"),
        ):
            await store.create_oauth_access_token(
                seed, token=token, client_id="c", user_id=user_id,
                scopes=["codexbridge.admin"] if user_id != "alice" else ["codexbridge.read"],
                expires_at=future,
            )

    app = FastAPI(openapi_url=None, docs_url=None, redoc_url=None)
    install_api_conventions(app)
    app.include_router(authorizations_routes.router)

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


# --------------------------------------------------------------------------
# Authentication and the base administrative gate
# --------------------------------------------------------------------------


async def test_authorize_requires_a_token(api) -> None:
    response = api.post("/api/v1/nodes/E1/projects/p1/authorize", json={"capabilities": ["read"]})
    assert response.status_code == 401


async def test_authorize_without_the_admin_scope_is_forbidden(api) -> None:
    response = api.post(
        "/api/v1/nodes/E1/projects/p1/authorize", headers=auth(ALICE_TOKEN), json={"capabilities": ["read"]}
    )
    assert response.status_code == 403


async def test_authorize_read_with_the_admin_scope_is_allowed(api) -> None:
    """Positive control: the base scope alone is sufficient for `read`/`test`."""
    response = api.post(
        "/api/v1/nodes/E1/projects/p1/authorize", headers=auth(ADMIN_SCOPE_TOKEN), json={"capabilities": ["read"]}
    )
    assert response.status_code == 200
    assert response.json()["capabilities"] == ["read"]


# --------------------------------------------------------------------------
# The privilege ladder: modify/deliver need a second gate
# --------------------------------------------------------------------------


async def test_granting_modify_without_can_approve_sensitive_or_admin_role_is_refused(api) -> None:
    """The scope alone (`codexbridge.admin`, no real admin role, no

    `can_approve_sensitive`) clears the base gate but not this one --
    `permissions.is_allowed`'s own docstring explains why `is_admin()` would
    have made this vacuous.
    """
    response = api.post(
        "/api/v1/nodes/E1/projects/p1/authorize", headers=auth(ADMIN_SCOPE_TOKEN), json={"capabilities": ["modify"]}
    )
    assert response.status_code == 403
    assert response.json()["code"] == "permission_denied"
    async with api.factory() as session:
        rows = (await session.execute(select(ProjectAuthorizationModel))).scalars().all()
        assert rows == []  # nothing was written


async def test_granting_modify_with_can_approve_sensitive_is_allowed(api) -> None:
    """Positive control: the sensitive-approval flag alone is sufficient, no admin role needed."""
    response = api.post(
        "/api/v1/nodes/E1/projects/p1/authorize",
        headers=auth(SENSITIVE_APPROVER_TOKEN),
        json={"capabilities": ["modify"]},
    )
    assert response.status_code == 200
    assert response.json()["capabilities"] == ["modify"]


async def test_granting_deliver_with_a_real_admin_role_is_allowed(api) -> None:
    """Positive control: a real `"admin"` role alone is sufficient, no `can_approve_sensitive` needed."""
    response = api.post(
        "/api/v1/nodes/E1/projects/p1/authorize", headers=auth(ROLE_ADMIN_TOKEN), json={"capabilities": ["deliver"]}
    )
    assert response.status_code == 200
    assert response.json()["capabilities"] == ["deliver"]


async def test_granting_read_and_modify_together_still_needs_the_second_gate(api) -> None:
    """Mixing a sensitive capability into an otherwise-plain request still trips the gate."""
    response = api.post(
        "/api/v1/nodes/E1/projects/p1/authorize",
        headers=auth(ADMIN_SCOPE_TOKEN),
        json={"capabilities": ["read", "modify"]},
    )
    assert response.status_code == 403


# --------------------------------------------------------------------------
# Grant/revoke semantics: same row, both events audited
# --------------------------------------------------------------------------


async def test_authorize_overwrites_rather_than_merges_capabilities(api) -> None:
    api.post("/api/v1/nodes/E1/projects/p1/authorize", headers=auth(ADMIN_SCOPE_TOKEN), json={"capabilities": ["read", "test"]})
    response = api.post(
        "/api/v1/nodes/E1/projects/p1/authorize", headers=auth(ADMIN_SCOPE_TOKEN), json={"capabilities": ["read"]}
    )
    assert response.status_code == 200
    assert response.json()["capabilities"] == ["read"]

    async with api.factory() as session:
        rows = (await session.execute(select(ProjectAuthorizationModel))).scalars().all()
        assert len(rows) == 1


async def test_revoke_then_regrant_reuses_the_same_row_and_both_events_are_audited(api) -> None:
    granted = api.post(
        "/api/v1/nodes/E1/projects/p1/authorize", headers=auth(ADMIN_SCOPE_TOKEN), json={"capabilities": ["read"]}
    ).json()
    assert granted["revokedAt"] is None

    revoked = api.post("/api/v1/nodes/E1/projects/p1/revoke", headers=auth(ADMIN_SCOPE_TOKEN)).json()
    assert revoked["revokedAt"] is not None

    regranted = api.post(
        "/api/v1/nodes/E1/projects/p1/authorize", headers=auth(ADMIN_SCOPE_TOKEN), json={"capabilities": ["test"]}
    ).json()
    assert regranted["revokedAt"] is None
    assert regranted["capabilities"] == ["test"]

    async with api.factory() as session:
        rows = (await session.execute(select(ProjectAuthorizationModel))).scalars().all()
        assert len(rows) == 1  # never a second row, even across revoke/regrant

        events = (await session.execute(select(AuditEventModel))).scalars().all()
        event_types = [event.event_type for event in events]
        assert event_types.count("project_authorization.granted") == 2
        assert event_types.count("project_authorization.revoked") == 1


async def test_revoking_a_pair_with_no_active_authorization_is_not_found(api) -> None:
    response = api.post("/api/v1/nodes/E1/projects/p1/revoke", headers=auth(ADMIN_SCOPE_TOKEN))
    assert response.status_code == 404


async def test_revoke_never_needs_the_sensitive_gate(api) -> None:
    """Positive control for the "no second gate on revoke" claim: the

    scope-only principal, who could never grant `modify`, can still revoke an
    authorization that already carries it.
    """
    api.post(
        "/api/v1/nodes/E1/projects/p1/authorize", headers=auth(SENSITIVE_APPROVER_TOKEN), json={"capabilities": ["modify"]}
    )
    response = api.post("/api/v1/nodes/E1/projects/p1/revoke", headers=auth(ADMIN_SCOPE_TOKEN))
    assert response.status_code == 200
    assert response.json()["revokedAt"] is not None


# --------------------------------------------------------------------------
# Unknown node/project
# --------------------------------------------------------------------------


async def test_authorizing_an_unknown_node_is_not_found(api) -> None:
    response = api.post(
        "/api/v1/nodes/does-not-exist/projects/p1/authorize", headers=auth(ADMIN_SCOPE_TOKEN), json={"capabilities": ["read"]}
    )
    assert response.status_code == 404


async def test_authorizing_an_unknown_project_is_not_found(api) -> None:
    response = api.post(
        "/api/v1/nodes/E1/projects/does-not-exist/authorize", headers=auth(ADMIN_SCOPE_TOKEN), json={"capabilities": ["read"]}
    )
    assert response.status_code == 404
