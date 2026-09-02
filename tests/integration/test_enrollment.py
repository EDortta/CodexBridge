"""`POST /api/v1/nodes/invite` / `enroll` / `{id}/revoke` — issue #76 (minimal
cut), the HTTP surface over `store.create_node_invite` / `enroll_node` /
`revoke_node` (unit-tested directly in `tests/unit/test_node_enrollment.py`)
and `AgentHub.force_close` (integration-tested against a live socket in
`tests/integration/test_node_enrollment_ws.py`). This file is what proves
authorization, status codes and response shape at the actual routes — same
fixture idiom `tests/integration/test_nodes.py` uses: a real FastAPI app
assembled from just the routers this surface needs, in-memory sqlite, OAuth
tokens minted through `store.create_oauth_access_token`.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from gateway.app.api.routes import enrollment as enrollment_routes
from gateway.app.api.routes import nodes as nodes_routes
from gateway.app.api.setup import install_api_conventions
from gateway.app.db.base import Base
from gateway.app.db.session import get_session
from gateway.app.models.entities import AuditEventModel, NodeInviteModel
from gateway.app.services import store


ADMIN_TOKEN = "token-admin"      # roles=["admin"], codexbridge.admin -- may invite/revoke
ALICE_TOKEN = "token-alice"      # authenticated, codexbridge.read only -- may not


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
                        "roles": [], "allowed_projects": [],
                        "scopes": ["codexbridge.read"], "enabled": True,
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
        future = datetime.now(timezone.utc) + timedelta(hours=1)
        for token, user_id, scopes in (
            (ADMIN_TOKEN, "admin", ["codexbridge.admin"]),
            (ALICE_TOKEN, "alice", ["codexbridge.read"]),
        ):
            await store.create_oauth_access_token(
                seed, token=token, client_id="c", user_id=user_id, scopes=scopes, expires_at=future,
            )

    app = FastAPI(openapi_url=None, docs_url=None, redoc_url=None)
    install_api_conventions(app)
    app.include_router(enrollment_routes.router)
    app.include_router(nodes_routes.router)

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


async def _expire_invite(factory, raw_token: str) -> None:
    from shared.security import hash_token

    async with factory() as session:
        invite = (
            (await session.execute(select(NodeInviteModel).where(NodeInviteModel.token_hash == hash_token(raw_token))))
            .scalars()
            .one()
        )
        invite.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
        await session.commit()


# --------------------------------------------------------------------------
# POST /nodes/invite
# --------------------------------------------------------------------------


def test_admin_can_issue_an_invite(api) -> None:
    response = api.post("/api/v1/nodes/invite", json={"displayNameHint": "devel3"}, headers=auth(ADMIN_TOKEN))

    assert response.status_code == 201
    body = response.json()
    assert body["inviteToken"]
    assert "id" in body and "expiresAt" in body


def test_a_read_only_caller_cannot_issue_an_invite(api) -> None:
    response = api.post("/api/v1/nodes/invite", json={}, headers=auth(ALICE_TOKEN))
    assert response.status_code == 403


async def test_the_raw_invite_token_never_lands_in_audit_events(api) -> None:
    response = api.post("/api/v1/nodes/invite", json={"displayNameHint": "devel3"}, headers=auth(ADMIN_TOKEN))
    raw = response.json()["inviteToken"]

    async with api.factory() as session:
        rows = (await session.execute(select(AuditEventModel))).scalars().all()
        assert rows, "the positive control: an audit row was actually written"
        for row in rows:
            assert raw not in row.payload_json


# --------------------------------------------------------------------------
# POST /nodes/enroll
# --------------------------------------------------------------------------


def test_enroll_redeems_the_invite_and_the_node_connects_with_the_returned_token(api) -> None:
    invite = api.post("/api/v1/nodes/invite", json={}, headers=auth(ADMIN_TOKEN)).json()

    response = api.post(
        "/api/v1/nodes/enroll",
        json={"inviteToken": invite["inviteToken"], "displayName": "devel3"},
    )

    assert response.status_code == 201
    body = response.json()
    assert body["nodeId"]
    assert body["displayName"] == "devel3"
    assert body["machineToken"]

    node = api.get(f"/api/v1/nodes/{body['nodeId']}", headers=auth(ADMIN_TOKEN)).json()
    assert node["admissionState"] == "enrolled"
    assert node["enabled"] is True


def test_enroll_needs_no_bearer_token_at_all(api) -> None:
    """Decision #2: the node has no credential yet -- the invite is the gate."""
    invite = api.post("/api/v1/nodes/invite", json={}, headers=auth(ADMIN_TOKEN)).json()

    response = api.post(
        "/api/v1/nodes/enroll",
        json={"inviteToken": invite["inviteToken"], "displayName": "devel3"},
        # No Authorization header.
    )

    assert response.status_code == 201


def test_enroll_refuses_an_unknown_invite_token(api) -> None:
    response = api.post(
        "/api/v1/nodes/enroll", json={"inviteToken": "never-issued", "displayName": "devel3"}
    )
    assert response.status_code == 400


def test_enroll_refuses_a_consumed_invite_the_second_time(api) -> None:
    invite = api.post("/api/v1/nodes/invite", json={}, headers=auth(ADMIN_TOKEN)).json()
    body = {"inviteToken": invite["inviteToken"], "displayName": "devel3"}

    first = api.post("/api/v1/nodes/enroll", json=body)
    assert first.status_code == 201, "the positive control: the first redemption must succeed"

    second = api.post("/api/v1/nodes/enroll", json=body)
    assert second.status_code == 400


async def test_enroll_refuses_an_expired_invite(api) -> None:
    invite = api.post("/api/v1/nodes/invite", json={}, headers=auth(ADMIN_TOKEN)).json()

    await _expire_invite(api.factory, invite["inviteToken"])

    response = api.post(
        "/api/v1/nodes/enroll",
        json={"inviteToken": invite["inviteToken"], "displayName": "devel3"},
    )
    assert response.status_code == 400


async def test_the_raw_machine_token_never_lands_in_audit_events(api) -> None:
    invite = api.post("/api/v1/nodes/invite", json={}, headers=auth(ADMIN_TOKEN)).json()
    enrolled = api.post(
        "/api/v1/nodes/enroll",
        json={"inviteToken": invite["inviteToken"], "displayName": "devel3"},
    ).json()
    raw_machine_token = enrolled["machineToken"]

    async with api.factory() as session:
        rows = (await session.execute(select(AuditEventModel))).scalars().all()
        for row in rows:
            assert raw_machine_token not in row.payload_json


# --------------------------------------------------------------------------
# POST /nodes/{id}/revoke
# --------------------------------------------------------------------------


def test_admin_can_revoke_an_enrolled_node(api) -> None:
    invite = api.post("/api/v1/nodes/invite", json={}, headers=auth(ADMIN_TOKEN)).json()
    node_id = api.post(
        "/api/v1/nodes/enroll",
        json={"inviteToken": invite["inviteToken"], "displayName": "devel3"},
    ).json()["nodeId"]

    response = api.post(f"/api/v1/nodes/{node_id}/revoke", headers=auth(ADMIN_TOKEN))

    assert response.status_code == 200
    body = response.json()
    assert body["admissionState"] == "revoked"
    assert body["enabled"] is False

    node = api.get(f"/api/v1/nodes/{node_id}", headers=auth(ADMIN_TOKEN)).json()
    assert node["admissionState"] == "revoked"
    assert node["enabled"] is False


def test_a_read_only_caller_cannot_revoke(api) -> None:
    invite = api.post("/api/v1/nodes/invite", json={}, headers=auth(ADMIN_TOKEN)).json()
    node_id = api.post(
        "/api/v1/nodes/enroll",
        json={"inviteToken": invite["inviteToken"], "displayName": "devel3"},
    ).json()["nodeId"]

    response = api.post(f"/api/v1/nodes/{node_id}/revoke", headers=auth(ALICE_TOKEN))
    assert response.status_code == 403


def test_revoking_an_unknown_node_answers_not_found(api) -> None:
    response = api.post("/api/v1/nodes/no-such-node/revoke", headers=auth(ADMIN_TOKEN))
    assert response.status_code == 404
