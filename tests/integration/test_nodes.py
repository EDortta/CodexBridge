"""Bridge Node fleet visibility — issue #73 Stage 2.

Weighted like `test_projects.py`: authorization, the four reachable health
values, inventory staleness and the "never a filesystem path" rule get the
attention, not serialization. Fixture idiom copied from `test_projects.py` —
real FastAPI app, in-memory sqlite, `store.upsert_registry` seeding, OAuth
tokens minted through `store.create_oauth_access_token`.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from gateway.app.api.routes import nodes as nodes_routes
from gateway.app.api.routes.nodes import INVENTORY_STALE_AFTER_SECONDS
from gateway.app.api.setup import install_api_conventions
from gateway.app.db.base import Base
from gateway.app.db.session import get_session
from gateway.app.models.entities import ExecutorModel, NodeModel
from gateway.app.services import store
from shared.protocol import Capability, EngineAvailability, ExecutorRegistration, NodeAnnouncement


ADMIN_TOKEN = "token-admin"      # roles=["admin"] -- sees the fleet
ALICE_TOKEN = "token-alice"      # authenticated, codexbridge.read only -- no fleet access
NOSCOPE_TOKEN = "token-noscope"  # authenticated, no scopes at all
EXPIRED_TOKEN = "token-expired"


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
                ]
            }
        ),
        encoding="utf-8",
    )
    return str(path)


@pytest.fixture
async def api(users_file, monkeypatch):
    """A real app over a real database, seeded with one executor -> one node.

    `E1` is registered but never marked connected — every test that needs a
    "live" or "stale" node drives that through `store.mark_executor_connected`
    and `set_last_seen` itself, the same discipline `test_projects.py` applies,
    so the starting point (health `unknown`) is not an assumption a test
    silently depends on.
    """
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
                    allowed_projects=["p1"], enabled=True,
                )
            ],
            projects=[],
        )
        future = datetime.now(timezone.utc) + timedelta(hours=1)
        for token, user_id, scopes in (
            (ADMIN_TOKEN, "admin", ["codexbridge.admin"]),
            (ALICE_TOKEN, "alice", ["codexbridge.read"]),
            (NOSCOPE_TOKEN, "noscope", []),
        ):
            await store.create_oauth_access_token(
                seed, token=token, client_id="c", user_id=user_id,
                scopes=scopes, expires_at=future,
            )
        await store.create_oauth_access_token(
            seed, token=EXPIRED_TOKEN, client_id="c", user_id="admin",
            scopes=["codexbridge.admin"],
            expires_at=datetime.now(timezone.utc) - timedelta(hours=1),
        )

    app = FastAPI(openapi_url=None, docs_url=None, redoc_url=None)
    install_api_conventions(app)
    app.include_router(nodes_routes.router)

    async def override():
        async with factory() as s:
            yield s

    app.dependency_overrides[get_session] = override

    client = TestClient(app, raise_server_exceptions=False)
    client.factory = factory  # type: ignore[attr-defined]
    yield client
    await engine.dispose()


async def mark_live(factory, executor_id: str = "E1") -> None:
    async with factory() as s:
        await store.mark_executor_connected(s, executor_id, True)


async def set_last_seen(factory, executor_id: str, when: datetime) -> None:
    async with factory() as s:
        executor = await s.get(ExecutorModel, executor_id)
        executor.last_seen_at = when
        await s.commit()


async def set_node_enabled(factory, node_id: str, enabled: bool) -> None:
    async with factory() as s:
        node = await s.get(NodeModel, node_id)
        node.enabled = enabled
        await s.commit()


async def set_capabilities_observed_at(factory, node_id: str, when: datetime) -> None:
    async with factory() as s:
        node = await s.get(NodeModel, node_id)
        node.capabilities_observed_at = when
        await s.commit()


async def announce(factory, executor_id: str = "E1", **overrides) -> None:
    defaults = dict(
        agent_version="1.2.3",
        os="Linux",
        arch="x86_64",
        engines=[EngineAvailability(engine="codex", implemented=True, available=True, version="0.9.0")],
        capabilities=[Capability.READ, Capability.TEST],
        max_concurrent_tasks=2,
        discovery_root_count=3,
    )
    defaults.update(overrides)
    async with factory() as s:
        executor = await s.get(ExecutorModel, executor_id)
        await store.record_node_announcement(s, executor, NodeAnnouncement(**defaults))


def auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _assert_no_absolute_paths(value) -> None:
    if isinstance(value, str):
        assert not value.startswith("/"), f"absolute path leaked: {value!r}"
    elif isinstance(value, dict):
        for item in value.values():
            _assert_no_absolute_paths(item)
    elif isinstance(value, list):
        for item in value:
            _assert_no_absolute_paths(item)


# --------------------------------------------------------------------------
# Authentication and authorization
# --------------------------------------------------------------------------


async def test_nodes_require_a_token(api) -> None:
    response = api.get("/api/v1/nodes")
    assert response.status_code == 401
    assert response.json()["code"] == "unauthenticated"


async def test_an_expired_token_is_refused(api) -> None:
    assert api.get("/api/v1/nodes", headers=auth(EXPIRED_TOKEN)).status_code == 401


async def test_a_token_without_the_admin_scope_is_forbidden(api) -> None:
    response = api.get("/api/v1/nodes", headers=auth(ALICE_TOKEN))
    assert response.status_code == 403
    assert response.json()["code"] == "permission_denied"


async def test_a_token_with_no_scopes_at_all_is_forbidden(api) -> None:
    response = api.get("/api/v1/nodes", headers=auth(NOSCOPE_TOKEN))
    assert response.status_code == 403


async def test_an_unknown_node_id_is_not_found(api) -> None:
    response = api.get("/api/v1/nodes/does-not-exist", headers=auth(ADMIN_TOKEN))
    assert response.status_code == 404
    assert response.json()["code"] == "not_found"


# --------------------------------------------------------------------------
# List and detail return the seeded node
# --------------------------------------------------------------------------


async def test_list_returns_the_seeded_node(api) -> None:
    body = api.get("/api/v1/nodes", headers=auth(ADMIN_TOKEN)).json()
    assert [item["id"] for item in body["items"]] == ["E1"]
    assert body["items"][0]["displayName"] == "E1"
    assert body["items"][0]["enabled"] is True


async def test_detail_returns_the_seeded_node(api) -> None:
    body = api.get("/api/v1/nodes/E1", headers=auth(ADMIN_TOKEN)).json()
    assert body["id"] == "E1"
    assert body["displayName"] == "E1"


# --------------------------------------------------------------------------
# Health: all four values are reachable
# --------------------------------------------------------------------------


async def test_health_is_unknown_when_the_node_has_never_been_seen(api) -> None:
    body = api.get("/api/v1/nodes/E1", headers=auth(ADMIN_TOKEN)).json()
    assert body["health"] == "unknown"


async def test_health_is_offline_when_last_seen_is_older_than_the_reconnect_grace(api) -> None:
    from gateway.app.core.config import settings

    # Mark it live once (so `last_seen_at` is set) and then rewind past the
    # grace window without a real disconnect -- the same technique
    # `test_projects.py` uses for its own stale-heartbeat case.
    await mark_live(api.factory)
    await set_last_seen(
        api.factory, "E1", datetime.now(timezone.utc) - timedelta(seconds=settings.reconnect_grace_seconds + 1)
    )
    body = api.get("/api/v1/nodes/E1", headers=auth(ADMIN_TOKEN)).json()
    assert body["health"] == "offline"


async def test_health_is_degraded_when_live_but_disabled(api) -> None:
    await mark_live(api.factory)
    await set_node_enabled(api.factory, "E1", False)
    body = api.get("/api/v1/nodes/E1", headers=auth(ADMIN_TOKEN)).json()
    assert body["health"] == "degraded"


async def test_health_is_ok_when_live_and_enabled(api) -> None:
    await mark_live(api.factory)
    body = api.get("/api/v1/nodes/E1", headers=auth(ADMIN_TOKEN)).json()
    assert body["health"] == "ok"


# --------------------------------------------------------------------------
# Inventory staleness
# --------------------------------------------------------------------------


async def test_inventory_is_stale_before_any_announcement(api) -> None:
    body = api.get("/api/v1/nodes/E1", headers=auth(ADMIN_TOKEN)).json()
    assert body["inventoryStale"] is True
    assert body["capabilitiesObservedAt"] is None


async def test_inventory_is_not_stale_right_after_an_announcement(api) -> None:
    await announce(api.factory)
    body = api.get("/api/v1/nodes/E1", headers=auth(ADMIN_TOKEN)).json()
    assert body["inventoryStale"] is False
    assert body["capabilitiesObservedAt"] is not None
    assert body["agentVersion"] == "1.2.3"
    assert body["os"] == "Linux"
    assert body["arch"] == "x86_64"
    assert body["maxConcurrentTasks"] == 2
    assert body["discoveryRootCount"] == 3
    assert set(body["capabilities"]) == {"read", "test"}
    assert body["engines"][0]["engine"] == "codex"


async def test_a_stale_capabilities_observed_at_is_reported_stale(api) -> None:
    await announce(api.factory)
    stale_at = datetime.now(timezone.utc) - timedelta(seconds=INVENTORY_STALE_AFTER_SECONDS + 1)
    await set_capabilities_observed_at(api.factory, "E1", stale_at)
    body = api.get("/api/v1/nodes/E1", headers=auth(ADMIN_TOKEN)).json()
    assert body["inventoryStale"] is True


# --------------------------------------------------------------------------
# No absolute filesystem path ever leaks
# --------------------------------------------------------------------------


async def test_no_absolute_path_leaks_after_an_announcement(api) -> None:
    """`docs/api/README.md` "fields that must never ship" excludes absolute
    paths; `NodeAnnouncement.discovery_root_count` exists precisely so this
    endpoint never needs one.
    """
    await announce(api.factory, discovery_root_count=5)

    list_body = api.get("/api/v1/nodes", headers=auth(ADMIN_TOKEN)).json()
    _assert_no_absolute_paths(list_body)

    detail_body = api.get("/api/v1/nodes/E1", headers=auth(ADMIN_TOKEN)).json()
    _assert_no_absolute_paths(detail_body)
    assert "discoveryRootCount" in detail_body
    assert "discoveryRoots" not in detail_body
