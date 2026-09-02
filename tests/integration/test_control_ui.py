"""CodexBridge Control's server-rendered screens — issue #73 Stage 5.

WK-20260902-gh73-control-ui. Fixture idiom copied from `test_nodes.py`/
`test_discovery_routes.py`: real FastAPI app, in-memory sqlite, `store.
upsert_registry` seeding, rows inserted directly for the two models no seeding
helper covers (`DiscoveredResourceModel`, `ProjectAuthorizationModel`).

One thing this file's fixtures do differently from every sibling: authenticating
against `gateway/app/api/routes/control_ui.py` means presenting a real HTTP
Basic credential, verified by `authenticate_async` against an actual password
hash — not an `Authorization: Bearer <token>` looked up in a pre-seeded table.
`_hash` below is `tests/integration/test_auth.py`'s own helper, copied
verbatim: cheap on purpose (1000 PBKDF2 iterations, not the production
600000), because `verify_password` reads the cost from the hash itself.

Weighted toward what this module's own docstring claims and this PR's brief
requires: the door refuses before any fleet data renders (401/403, not a
blank or half-loaded page), HTML escaping actually holds against a hostile
`display_name`/project name/resource path, pagination actually walks a second
page, and the invite screen honestly explains the gap instead of quietly
mocking one up. Every negative case is paired with a positive control in this
same file (`docs/napkin-lessons.md`, 2026-09-01).
"""

from __future__ import annotations

import base64
import hashlib
import json
from datetime import datetime, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from gateway.app.api.routes import control_ui as control_ui_routes
from gateway.app.api.setup import install_api_conventions
from gateway.app.db.base import Base
from gateway.app.db.session import get_session
from gateway.app.models.entities import (
    AuditEventModel,
    DiscoveredResourceModel,
    ProjectAuthorizationModel,
    ProjectModel,
)
from gateway.app.services import store
from shared.protocol import DiscoveredState, ExecutorRegistration


PASSWORD = "correct-horse-battery-staple"
OTHER_PASSWORD = "not-the-password"


def _hash(password: str, iterations: int = 1000) -> str:
    """A registry hash, cheap on purpose — copied from `test_auth.py`'s own.

    `verify_password` reads the iteration count out of the hash itself, so a
    test fixture can cost a thousand iterations while production costs six
    hundred thousand.
    """
    salt = b"codexbridge-test-salt"
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    encode = lambda raw: base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")  # noqa: E731
    return "$".join(("pbkdf2_sha256", str(iterations), encode(salt), encode(digest)))


def basic(username: str, password: str = PASSWORD) -> dict:
    token = base64.b64encode(f"{username}:{password}".encode("utf-8")).decode("ascii")
    return {"Authorization": f"Basic {token}"}


@pytest.fixture
def users_file(tmp_path):
    path = tmp_path / "users.json"
    path.write_text(
        json.dumps(
            {
                "users": [
                    {
                        "user_id": "admin", "email": "admin@example.com",
                        "password_hash": _hash(PASSWORD),
                        "roles": ["admin"], "allowed_projects": [],
                        "scopes": ["codexbridge.admin"], "can_approve_sensitive": False, "enabled": True,
                    },
                    {
                        "user_id": "alice", "email": "alice@example.com",
                        "password_hash": _hash(PASSWORD),
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
                    executor_id="E1", display_name="E1", machine_token="t",
                    allowed_projects=[], enabled=True,
                )
            ],
            projects=[],
        )

    app = FastAPI(openapi_url=None, docs_url=None, redoc_url=None)
    install_api_conventions(app)
    app.include_router(control_ui_routes.router)

    async def override():
        async with factory() as s:
            yield s

    app.dependency_overrides[get_session] = override

    client = TestClient(app, raise_server_exceptions=False)
    client.factory = factory  # type: ignore[attr-defined]
    yield client
    await engine.dispose()


async def set_node_display_name(factory, node_id: str, display_name: str) -> None:
    async with factory() as session:
        from gateway.app.models.entities import NodeModel

        node = await session.get(NodeModel, node_id)
        node.display_name = display_name
        await session.commit()


async def seed_resource(
    factory,
    *,
    resource_id: str,
    node_id: str = "E1",
    root_path: str = "/root",
    resource_path: str = "/root/hub",
    state: str = DiscoveredState.DISCOVERED.value,
    project_id: str | None = None,
    suggested_name: str = "Hub",
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
                evidence_json=json.dumps({"suggested_name": suggested_name}),
                state=state,
                root_path=root_path,
                first_seen_at=datetime.now(timezone.utc),
                last_seen_at=datetime.now(timezone.utc),
            )
        )
        await session.commit()


async def seed_project(factory, *, project_id: str, name: str) -> None:
    async with factory() as session:
        session.add(ProjectModel(id=project_id, name=name, path="/srv/irrelevant", enabled=True))
        await session.commit()


async def grant(factory, *, node_id: str = "E1", project_id: str, capabilities: list[str], granted_by: str = "operator:admin") -> None:
    async with factory() as session:
        session.add(
            ProjectAuthorizationModel(
                id=f"auth-{project_id}",
                node_id=node_id,
                project_id=project_id,
                capabilities_json=json.dumps(capabilities),
                granted_by=granted_by,
                granted_at=datetime.now(timezone.utc),
            )
        )
        await session.commit()


# ---------------------------------------------------------------------------
# GET /control — fleet list
# ---------------------------------------------------------------------------


async def test_control_home_requires_a_credential(api) -> None:
    response = api.get("/control")
    assert response.status_code == 401
    assert response.headers["www-authenticate"].startswith("Basic")


async def test_control_home_with_a_wrong_password_is_refused(api) -> None:
    response = api.get("/control", headers=basic("admin", OTHER_PASSWORD))
    assert response.status_code == 401


async def test_control_home_without_the_admin_scope_is_forbidden(api) -> None:
    response = api.get("/control", headers=basic("alice"))
    assert response.status_code == 403
    assert "nodes.read" in response.text


async def test_control_home_with_the_admin_scope_is_allowed(api) -> None:
    """Positive control for the previous three: the credential and scope alone are sufficient."""
    response = api.get("/control", headers=basic("admin"))
    assert response.status_code == 200
    assert "E1" in response.text


async def test_control_home_escapes_a_hostile_display_name(api) -> None:
    await set_node_display_name(api.factory, "E1", "<script>alert(1)</script>")
    response = api.get("/control", headers=basic("admin"))
    assert response.status_code == 200
    assert "<script>alert(1)</script>" not in response.text
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in response.text


async def test_control_home_counts_pending_candidates(api) -> None:
    await seed_resource(api.factory, resource_id="r1", resource_path="/root/hub")
    await seed_resource(api.factory, resource_id="r2", resource_path="/root/other")
    response = api.get("/control", headers=basic("admin"))
    assert response.status_code == 200
    # Two DISCOVERED candidates for E1 -- the fleet row's pending-count cell.
    assert ">2<" in response.text


# ---------------------------------------------------------------------------
# GET /control/nodes/{node_id} — node detail
# ---------------------------------------------------------------------------


async def test_control_node_detail_requires_a_credential(api) -> None:
    response = api.get("/control/nodes/E1")
    assert response.status_code == 401


async def test_control_node_detail_unknown_node_is_404(api) -> None:
    response = api.get("/control/nodes/does-not-exist", headers=basic("admin"))
    assert response.status_code == 404


async def test_control_node_detail_renders_capabilities_for_an_admin(api) -> None:
    """Positive control for the previous two."""
    response = api.get("/control/nodes/E1", headers=basic("admin"))
    assert response.status_code == 200
    assert "Capabilities" in response.text


async def test_control_node_detail_escapes_a_hostile_resource_path_and_suggested_name(api) -> None:
    await seed_resource(
        api.factory,
        resource_id="r1",
        resource_path="/tmp/<img src=x onerror=alert(1)>",
        suggested_name="</code><script>alert(2)</script>",
    )
    response = api.get("/control/nodes/E1", headers=basic("admin"))
    assert response.status_code == 200
    assert "<img src=x onerror=alert(1)>" not in response.text
    assert "<script>alert(2)</script>" not in response.text
    assert "&lt;img src=x onerror=alert(1)&gt;" in response.text
    assert "&lt;script&gt;alert(2)&lt;/script&gt;" in response.text


async def test_control_node_detail_shows_the_candidate_resource_path(api) -> None:
    """The one authorized surface `resourcePath` may appear on (docs/api/README.md).

    Positive control for the escaping test above, and for the "never in a
    title/query string" rule this module's docstring states: the path is in
    the escaped table body, not in `<title>` and not appended to any `href`.
    """
    await seed_resource(api.factory, resource_id="r1", resource_path="/srv/projects/hub")
    response = api.get("/control/nodes/E1", headers=basic("admin"))
    assert response.status_code == 200
    assert "/srv/projects/hub" in response.text
    title_line = response.text.split("<title>", 1)[1].split("</title>", 1)[0]
    assert "/srv/projects/hub" not in title_line


async def test_control_node_detail_paginates_discovered_candidates(api) -> None:
    total = control_ui_routes.CANDIDATES_PAGE_SIZE + 5
    for i in range(total):
        await seed_resource(api.factory, resource_id=f"r{i:03d}", resource_path=f"/root/p{i:03d}")

    first = api.get("/control/nodes/E1", headers=basic("admin"))
    assert first.status_code == 200
    first_ids = {f"r{i:03d}" for i in range(total)}
    shown_on_first = {rid for rid in first_ids if f">{rid}<" in first.text}
    assert len(shown_on_first) == control_ui_routes.CANDIDATES_PAGE_SIZE
    assert "Next page" in first.text

    cursor = first.text.split("?cursor=", 1)[1].split('"', 1)[0]
    second = api.get(f"/control/nodes/E1?cursor={cursor}", headers=basic("admin"))
    assert second.status_code == 200
    shown_on_second = {rid for rid in first_ids if f">{rid}<" in second.text}
    assert len(shown_on_second) == total - control_ui_routes.CANDIDATES_PAGE_SIZE
    assert shown_on_second.isdisjoint(shown_on_first)
    assert "Next page" not in second.text


async def test_control_node_detail_shows_a_grant_form_for_an_adopted_unauthorized_project(api) -> None:
    """`ADOPTED` with no capability grant yet has no `project_authorizations`

    row at all -- the exact case `_authorization_section`'s docstring names.
    The Grant form must still appear so an operator can act on it.
    """
    await seed_project(api.factory, project_id="hub", name="Hub")
    await seed_resource(
        api.factory, resource_id="r1", resource_path="/root/hub",
        state=DiscoveredState.ADOPTED.value, project_id="hub",
    )
    response = api.get("/control/nodes/E1", headers=basic("admin"))
    assert response.status_code == 200
    assert 'data-project-id="hub"' in response.text
    assert "control-grant" in response.text


async def test_control_node_detail_shows_active_capabilities_and_a_revoke_form(api) -> None:
    await seed_project(api.factory, project_id="hub", name="Hub")
    await grant(api.factory, project_id="hub", capabilities=["read", "test"])
    response = api.get("/control/nodes/E1", headers=basic("admin"))
    assert response.status_code == 200
    assert "read, test" in response.text
    assert "control-revoke" in response.text


async def test_control_node_detail_warns_that_modify_and_deliver_need_more_than_admin_scope(api) -> None:
    response = api.get("/control/nodes/E1", headers=basic("admin"))
    assert response.status_code == 200
    assert "can_approve_sensitive" in response.text
    assert "admin" in response.text


async def test_control_node_detail_mints_no_audit_event(api) -> None:
    """Reading a page, and the token minted for its own fetch() calls, are not audited.

    Matches every other *read* path in this codebase (only writes call
    `record_event`) — see the module docstring, "Authentication".
    """
    await seed_resource(api.factory, resource_id="r1")
    async with api.factory() as session:
        before = (await session.execute(select(AuditEventModel))).scalars().all()
    response = api.get("/control/nodes/E1", headers=basic("admin"))
    assert response.status_code == 200
    async with api.factory() as session:
        after = (await session.execute(select(AuditEventModel))).scalars().all()
    assert len(after) == len(before)


async def test_control_node_detail_embeds_a_real_bearer_token_for_its_own_fetch_calls(api) -> None:
    """The page-scoped token is an ordinary row in the same table `/api/v1/**` reads.

    Confirms the module docstring's claim literally: the token embedded in
    the rendered page's `<script>` resolves to a live `oauth_access_tokens`
    row, the same table `current_principal` (`gateway/app/api/auth.py`)
    looks up for every `/api/v1/**` request.
    """
    response = api.get("/control/nodes/E1", headers=basic("admin"))
    assert response.status_code == 200
    token = response.text.split("const CB_TOKEN = ", 1)[1].split(";", 1)[0].strip('"')
    async with api.factory() as session:
        row = await store.get_oauth_access_token(session, token)
    assert row is not None
    assert row.user_id == "admin"


# ---------------------------------------------------------------------------
# GET /control/invite — see control_ui.py's own docstring
# ---------------------------------------------------------------------------


async def test_control_invite_requires_a_credential(api) -> None:
    response = api.get("/control/invite")
    assert response.status_code == 401


async def test_control_invite_without_the_admin_scope_is_forbidden(api) -> None:
    response = api.get("/control/invite", headers=basic("alice"))
    assert response.status_code == 403


async def test_control_invite_explains_the_gap_honestly(api) -> None:
    """Positive control for the previous two, and the point of this screen today:

    it must say plainly that it cannot do what its name promises on THIS
    build, and never present a form that posts to an endpoint this process
    does not serve. It must also not claim the capability is unbuilt: the
    endpoint and the script exist on the branch carrying issue #76's minimal
    cut, and this page says so, because "missing from this build" and
    "missing from this codebase" are different statements and only the first
    one is true.
    """
    response = api.get("/control/invite", headers=basic("admin"))
    assert response.status_code == 200
    assert "Not available yet on this build" in response.text
    assert "/api/v1/nodes/invite" in response.text
    assert "enroll_node.py" in response.text
    assert "#76" in response.text
    assert "<form" not in response.text
