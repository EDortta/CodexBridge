"""Epics and issues — issue #8.

Provider-neutral planning entities: this build owns them itself, there is no
GitHub sync. Weighted toward the two things the acceptance criteria name
explicitly — relationship changes (the epic-issue link) and invalid input —
plus the authorization and concurrency conventions every other write endpoint
in this API already carries.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from gateway.app.api.routes import epics as epics_routes
from gateway.app.api.routes import issues as issues_routes
from gateway.app.api.setup import install_api_conventions
from gateway.app.db.base import Base
from gateway.app.db.session import get_session
from gateway.app.services import store
from shared.protocol import ExecutorRegistration, ProjectRegistration, TaskMode


ALICE_TOKEN = "token-alice"    # p1 only, has issues.write
READER_TOKEN = "token-reader"  # p1 only, read-only
ADMIN_TOKEN = "token-admin"    # everything


@pytest.fixture
def users_file(tmp_path):
    path = tmp_path / "users.json"
    path.write_text(
        json.dumps(
            {
                "users": [
                    {
                        "user_id": "alice", "email": "alice@example.com", "password_hash": "x",
                        "roles": [], "allowed_projects": ["p1"],
                        "scopes": ["codexbridge.read", "codexbridge.issues.write"], "enabled": True,
                    },
                    {
                        "user_id": "reader", "email": "reader@example.com", "password_hash": "x",
                        "roles": [], "allowed_projects": ["p1"],
                        "scopes": ["codexbridge.read"], "enabled": True,
                    },
                    {
                        "user_id": "admin", "email": "admin@example.com", "password_hash": "x",
                        "roles": ["admin"], "allowed_projects": [],
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
                    allowed_projects=["p1", "p2"], enabled=True,
                )
            ],
            projects=[
                ProjectRegistration(
                    project_id=pid, name=pid, path=f"/srv/{pid}",
                    allowed_modes=[TaskMode.ANALYZE], max_timeout_seconds=600,
                    sensitive_patterns=[], enabled=True,
                )
                for pid in ("p1", "p2")
            ],
        )
        future = datetime.now(timezone.utc) + timedelta(hours=1)
        for token, user_id, scopes in (
            (ALICE_TOKEN, "alice", ["codexbridge.read", "codexbridge.issues.write"]),
            (READER_TOKEN, "reader", ["codexbridge.read"]),
            (ADMIN_TOKEN, "admin", ["codexbridge.admin"]),
        ):
            await store.create_oauth_access_token(
                seed, token=token, client_id="c", user_id=user_id, scopes=scopes, expires_at=future
            )

    app = FastAPI(openapi_url=None, docs_url=None, redoc_url=None)
    install_api_conventions(app)
    app.include_router(epics_routes.router)
    app.include_router(issues_routes.router)

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


async def make_epic(factory, project_id: str = "p1", title: str = "Epic one"):
    async with factory() as s:
        return await store.create_epic(
            s, project_id=project_id, title=title, description=None, status=None,
            actor_user_id="alice", actor_email="alice@example.com",
        )


async def make_issue(factory, project_id: str = "p1", **kwargs):
    async with factory() as s:
        return await store.create_issue(
            s,
            project_id=project_id,
            epic_id=kwargs.pop("epic_id", None),
            title=kwargs.pop("title", "Issue one"),
            description=kwargs.pop("description", None),
            status=kwargs.pop("status", None),
            priority=kwargs.pop("priority", None),
            labels=kwargs.pop("labels", None),
            assignee_user_id=kwargs.pop("assignee_user_id", None),
            assignee_email=kwargs.pop("assignee_email", None),
            dependencies=kwargs.pop("dependencies", None),
            blocked_reason=kwargs.pop("blocked_reason", None),
            actor_user_id="alice",
            actor_email="alice@example.com",
        )


# --------------------------------------------------------------------------
# Authentication, authorization and project visibility
# --------------------------------------------------------------------------


async def test_epics_and_issues_require_a_token(api) -> None:
    assert api.get("/api/v1/projects/p1/epics").status_code == 401
    assert api.get("/api/v1/projects/p1/issues").status_code == 401
    assert api.post("/api/v1/epics", json={"projectId": "p1", "title": "x"}).status_code == 401
    assert api.post("/api/v1/issues", json={"projectId": "p1", "title": "x"}).status_code == 401


async def test_reader_cannot_create_epics_or_issues(api) -> None:
    for response in (
        api.post("/api/v1/epics", json={"projectId": "p1", "title": "x"}, headers=auth(READER_TOKEN)),
        api.post("/api/v1/issues", json={"projectId": "p1", "title": "x"}, headers=auth(READER_TOKEN)),
    ):
        assert response.status_code == 403
        assert response.json()["code"] == "permission_denied"


async def test_reader_can_still_list_and_read(api) -> None:
    await make_epic(api.factory)
    assert api.get("/api/v1/projects/p1/epics", headers=auth(READER_TOKEN)).status_code == 200
    assert api.get("/api/v1/projects/p1/issues", headers=auth(READER_TOKEN)).status_code == 200


async def test_a_project_outside_the_caller_visibility_is_not_found(api) -> None:
    """404, never 403 — confirming existence is what probing is for."""
    for path in ("/api/v1/projects/p2/epics", "/api/v1/projects/p2/issues"):
        response = api.get(path, headers=auth(ALICE_TOKEN))
        assert response.status_code == 404
        assert response.json()["code"] == "not_found"

    response = api.post(
        "/api/v1/epics", json={"projectId": "p2", "title": "x"}, headers=auth(ALICE_TOKEN)
    )
    assert response.status_code == 404


async def test_an_epic_or_issue_in_an_invisible_project_is_not_found(api) -> None:
    theirs_epic = await make_epic(api.factory, "p2")
    theirs_issue = await make_issue(api.factory, "p2")
    assert api.get(f"/api/v1/issues/{theirs_issue.id}", headers=auth(ALICE_TOKEN)).status_code == 404
    assert api.get(f"/api/v1/epics/{theirs_epic.id}", headers=auth(ALICE_TOKEN)).status_code == 404
    response = api.patch(
        f"/api/v1/epics/{theirs_epic.id}",
        json={"status": "cancelled"},
        headers={**auth(ALICE_TOKEN), "If-Match": f'"{theirs_epic.revision}"'},
    )
    assert response.status_code == 404
    # Linking reaches for both records, and both checks must hold.
    response = api.post(
        f"/api/v1/epics/{theirs_epic.id}/issues/{theirs_issue.id}",
        headers={**auth(ALICE_TOKEN), "If-Match": f'"{theirs_issue.revision}"'},
    )
    assert response.status_code == 404


# --------------------------------------------------------------------------
# Creating epics
# --------------------------------------------------------------------------


async def test_create_epic(api) -> None:
    response = api.post(
        "/api/v1/epics",
        json={"projectId": "p1", "title": "Mobile parity", "description": "Track it"},
        headers=auth(ALICE_TOKEN),
    )
    assert response.status_code == 201
    body = response.json()
    assert body["projectId"] == "p1"
    assert body["status"] == "open"
    assert body["revision"] == 1
    assert body["createdBy"] == "alice@example.com"
    assert response.headers["ETag"] == '"1"'


async def test_create_epic_rejects_an_empty_title(api) -> None:
    response = api.post(
        "/api/v1/epics", json={"projectId": "p1", "title": "   "}, headers=auth(ALICE_TOKEN)
    )
    assert response.status_code == 400
    assert response.json()["code"] == "validation_failed"


async def test_create_epic_rejects_an_unknown_status(api) -> None:
    response = api.post(
        "/api/v1/epics",
        json={"projectId": "p1", "title": "x", "status": "orbiting"},
        headers=auth(ALICE_TOKEN),
    )
    assert response.status_code == 400
    assert response.json()["details"][0]["field"] == "/status"


async def test_a_retried_epic_create_does_not_create_a_second_epic(api) -> None:
    headers = {**auth(ALICE_TOKEN), "Idempotency-Key": "epic-1"}
    payload = {"projectId": "p1", "title": "Once only"}

    first = api.post("/api/v1/epics", json=payload, headers=headers)
    second = api.post("/api/v1/epics", json=payload, headers=headers)

    assert first.status_code == 201
    assert second.status_code == 201
    assert second.headers.get("Idempotent-Replay") == "true"
    assert second.json() == first.json()

    listed = api.get("/api/v1/projects/p1/epics", headers=auth(ALICE_TOKEN)).json()
    assert len(listed["items"]) == 1


# --------------------------------------------------------------------------
# Creating issues
# --------------------------------------------------------------------------


async def test_create_issue_defaults_status_and_priority(api) -> None:
    response = api.post(
        "/api/v1/issues", json={"projectId": "p1", "title": "Fix the thing"}, headers=auth(ALICE_TOKEN)
    )
    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "open"
    assert body["priority"] == "medium"
    assert body["labels"] == []
    assert body["dependencies"] == []
    assert body["epicId"] is None


async def test_create_issue_normalizes_and_dedupes_labels(api) -> None:
    response = api.post(
        "/api/v1/issues",
        json={"projectId": "p1", "title": "x", "labels": [" bug ", "bug", "ui", ""]},
        headers=auth(ALICE_TOKEN),
    )
    assert response.json()["labels"] == ["bug", "ui"]


async def test_create_issue_rejects_an_unknown_priority(api) -> None:
    response = api.post(
        "/api/v1/issues",
        json={"projectId": "p1", "title": "x", "priority": "urgentest"},
        headers=auth(ALICE_TOKEN),
    )
    assert response.status_code == 400
    assert response.json()["details"][0]["field"] == "/priority"


async def test_create_issue_with_an_epic_from_another_project_is_rejected(api) -> None:
    foreign_epic = await make_epic(api.factory, "p2")
    response = api.post(
        "/api/v1/issues",
        json={"projectId": "p1", "title": "x", "epicId": foreign_epic.id},
        headers=auth(ADMIN_TOKEN),
    )
    assert response.status_code == 400
    assert response.json()["details"][0]["field"] == "/epicId"


async def test_create_issue_with_an_unknown_dependency_is_rejected(api) -> None:
    response = api.post(
        "/api/v1/issues",
        json={"projectId": "p1", "title": "x", "dependencies": ["does-not-exist"]},
        headers=auth(ALICE_TOKEN),
    )
    assert response.status_code == 400
    assert response.json()["details"][0]["field"] == "/dependencies"


async def test_create_issue_with_a_dependency_in_another_project_is_rejected(api) -> None:
    foreign = await make_issue(api.factory, "p2")
    response = api.post(
        "/api/v1/issues",
        json={"projectId": "p1", "title": "x", "dependencies": [foreign.id]},
        headers=auth(ADMIN_TOKEN),
    )
    assert response.status_code == 400


async def test_create_issue_records_valid_dependencies(api) -> None:
    blocker = await make_issue(api.factory, "p1", title="Blocker")
    response = api.post(
        "/api/v1/issues",
        json={"projectId": "p1", "title": "Blocked", "dependencies": [blocker.id, blocker.id]},
        headers=auth(ALICE_TOKEN),
    )
    assert response.status_code == 201
    assert response.json()["dependencies"] == [blocker.id]


# --------------------------------------------------------------------------
# Reading and listing issues
# --------------------------------------------------------------------------


async def test_get_issue_returns_an_etag(api) -> None:
    issue = await make_issue(api.factory)
    response = api.get(f"/api/v1/issues/{issue.id}", headers=auth(ALICE_TOKEN))
    assert response.status_code == 200
    assert response.headers["ETag"] == f'"{issue.revision}"'


async def test_the_issue_body_never_carries_the_project_path(api) -> None:
    issue = await make_issue(api.factory)
    text = api.get(f"/api/v1/issues/{issue.id}", headers=auth(ALICE_TOKEN)).text
    assert "/srv/p1" not in text


async def test_list_issues_filters_by_status_priority_epic_and_assignee(api) -> None:
    epic = await make_epic(api.factory)
    await make_issue(api.factory, status="open", priority="low", epic_id=None)
    matching = await make_issue(
        api.factory, status="blocked", priority="high", epic_id=epic.id, assignee_user_id="bob"
    )

    body = api.get(
        "/api/v1/projects/p1/issues",
        params={"status": "blocked", "priority": "high", "epicId": epic.id, "assigneeUserId": "bob"},
        headers=auth(ALICE_TOKEN),
    ).json()
    assert [item["id"] for item in body["items"]] == [matching.id]


async def test_the_issue_list_cursor_walks_every_issue_once(api) -> None:
    for index in range(6):
        await make_issue(api.factory, title=f"issue {index}")

    seen: list[str] = []
    cursor = None
    for _ in range(10):
        params = {"limit": 2}
        if cursor:
            params["cursor"] = cursor
        body = api.get(
            "/api/v1/projects/p1/issues", headers=auth(ALICE_TOKEN), params=params
        ).json()
        seen.extend(item["id"] for item in body["items"])
        cursor = body["page"]["nextCursor"]
        if not body["page"]["hasMore"]:
            break

    assert len(seen) == 6
    assert len(set(seen)) == 6


async def test_an_issue_cursor_from_a_different_project_is_rejected(api) -> None:
    await make_issue(api.factory, "p1")
    await make_issue(api.factory, "p2")
    first = api.get(
        "/api/v1/projects/p1/issues", headers=auth(ADMIN_TOKEN), params={"limit": 1}
    ).json()
    cursor = first["page"]["nextCursor"] or "x"
    response = api.get(
        "/api/v1/projects/p2/issues", headers=auth(ADMIN_TOKEN), params={"cursor": cursor}
    )
    assert response.status_code == 400


# --------------------------------------------------------------------------
# Updating issues
# --------------------------------------------------------------------------


async def test_update_requires_if_match(api) -> None:
    issue = await make_issue(api.factory)
    response = api.patch(
        f"/api/v1/issues/{issue.id}", json={"status": "in_progress"}, headers=auth(ALICE_TOKEN)
    )
    assert response.status_code == 428


async def test_update_with_a_stale_etag_is_refused(api) -> None:
    issue = await make_issue(api.factory)
    response = api.patch(
        f"/api/v1/issues/{issue.id}",
        json={"status": "in_progress"},
        headers={**auth(ALICE_TOKEN), "If-Match": '"999"'},
    )
    assert response.status_code == 412
    assert response.json()["code"] == "stale_write"


async def test_update_changes_only_the_mentioned_fields(api) -> None:
    issue = await make_issue(api.factory, title="Original", priority="low", labels=["a"])
    response = api.patch(
        f"/api/v1/issues/{issue.id}",
        json={"status": "in_progress"},
        headers={**auth(ALICE_TOKEN), "If-Match": f'"{issue.revision}"'},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "in_progress"
    assert body["title"] == "Original"
    assert body["priority"] == "low"
    assert body["labels"] == ["a"]
    assert body["revision"] == issue.revision + 1
    assert body["updatedBy"] == "alice@example.com"


async def test_update_can_explicitly_clear_a_nullable_field(api) -> None:
    issue = await make_issue(api.factory, blocked_reason="waiting on design")
    response = api.patch(
        f"/api/v1/issues/{issue.id}",
        json={"blockedReason": None},
        headers={**auth(ALICE_TOKEN), "If-Match": f'"{issue.revision}"'},
    )
    assert response.status_code == 200
    assert response.json()["blockedReason"] is None


async def test_update_rejects_an_unknown_status(api) -> None:
    issue = await make_issue(api.factory)
    response = api.patch(
        f"/api/v1/issues/{issue.id}",
        json={"status": "not_a_status"},
        headers={**auth(ALICE_TOKEN), "If-Match": f'"{issue.revision}"'},
    )
    assert response.status_code == 400
    assert response.json()["details"][0]["field"] == "/status"


async def test_update_rejects_a_self_dependency(api) -> None:
    issue = await make_issue(api.factory)
    response = api.patch(
        f"/api/v1/issues/{issue.id}",
        json={"dependencies": [issue.id]},
        headers={**auth(ALICE_TOKEN), "If-Match": f'"{issue.revision}"'},
    )
    assert response.status_code == 400
    assert response.json()["details"][0]["code"] == "self_dependency"


async def test_update_does_not_accept_an_epic_id(api) -> None:
    """epicId is deliberately absent from the update body — see the link endpoint."""
    issue = await make_issue(api.factory)
    epic = await make_epic(api.factory)
    response = api.patch(
        f"/api/v1/issues/{issue.id}",
        json={"epicId": epic.id, "status": "in_progress"},
        headers={**auth(ALICE_TOKEN), "If-Match": f'"{issue.revision}"'},
    )
    assert response.status_code == 200
    assert response.json()["epicId"] is None


# --------------------------------------------------------------------------
# Linking issues to epics — the relationship change
# --------------------------------------------------------------------------


async def test_link_issue_to_epic(api) -> None:
    epic = await make_epic(api.factory)
    issue = await make_issue(api.factory)
    response = api.post(
        f"/api/v1/epics/{epic.id}/issues/{issue.id}",
        headers={**auth(ALICE_TOKEN), "If-Match": f'"{issue.revision}"'},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["epicId"] == epic.id
    assert body["revision"] == issue.revision + 1
    assert response.headers["ETag"] == f'"{issue.revision + 1}"'


async def test_link_requires_if_match(api) -> None:
    epic = await make_epic(api.factory)
    issue = await make_issue(api.factory)
    response = api.post(
        f"/api/v1/epics/{epic.id}/issues/{issue.id}", headers=auth(ALICE_TOKEN)
    )
    assert response.status_code == 428


async def test_link_rejects_an_epic_from_a_different_project(api) -> None:
    epic = await make_epic(api.factory, "p2")
    issue = await make_issue(api.factory, "p1")
    response = api.post(
        f"/api/v1/epics/{epic.id}/issues/{issue.id}",
        headers={**auth(ADMIN_TOKEN), "If-Match": f'"{issue.revision}"'},
    )
    assert response.status_code == 400
    assert response.json()["details"][0]["field"] == "/epicId"


async def test_a_reader_cannot_link(api) -> None:
    epic = await make_epic(api.factory)
    issue = await make_issue(api.factory)
    response = api.post(
        f"/api/v1/epics/{epic.id}/issues/{issue.id}",
        headers={**auth(READER_TOKEN), "If-Match": f'"{issue.revision}"'},
    )
    assert response.status_code == 403


async def test_a_retried_link_does_not_relink_twice(api) -> None:
    epic = await make_epic(api.factory)
    issue = await make_issue(api.factory)
    headers = {**auth(ALICE_TOKEN), "If-Match": f'"{issue.revision}"', "Idempotency-Key": "link-1"}

    first = api.post(f"/api/v1/epics/{epic.id}/issues/{issue.id}", headers=headers)
    second = api.post(f"/api/v1/epics/{epic.id}/issues/{issue.id}", headers=headers)

    assert first.status_code == 200
    assert second.status_code == 200
    assert second.headers.get("Idempotent-Replay") == "true"
    assert second.json() == first.json()

    detail = api.get(f"/api/v1/issues/{issue.id}", headers=auth(ALICE_TOKEN)).json()
    assert detail["revision"] == issue.revision + 1, "the link must not have applied twice"


async def test_a_failed_link_does_not_keep_the_key_claimed(api) -> None:
    epic = await make_epic(api.factory)
    issue = await make_issue(api.factory)
    bad = {**auth(ALICE_TOKEN), "If-Match": '"999"', "Idempotency-Key": "link-2"}
    assert api.post(f"/api/v1/epics/{epic.id}/issues/{issue.id}", headers=bad).status_code == 412

    good = {**auth(ALICE_TOKEN), "If-Match": f'"{issue.revision}"', "Idempotency-Key": "link-2"}
    assert api.post(f"/api/v1/epics/{epic.id}/issues/{issue.id}", headers=good).status_code == 200


# --------------------------------------------------------------------------
# Listing epics
# --------------------------------------------------------------------------


async def test_the_epic_list_cursor_walks_every_epic_once(api) -> None:
    for index in range(5):
        await make_epic(api.factory, title=f"epic {index}")

    seen: list[str] = []
    cursor = None
    for _ in range(10):
        params = {"limit": 2}
        if cursor:
            params["cursor"] = cursor
        body = api.get("/api/v1/projects/p1/epics", headers=auth(ALICE_TOKEN), params=params).json()
        seen.extend(item["id"] for item in body["items"])
        cursor = body["page"]["nextCursor"]
        if not body["page"]["hasMore"]:
            break

    assert len(seen) == 5
    assert len(set(seen)) == 5


async def test_list_epics_filters_by_status(api) -> None:
    async with api.factory() as s:
        open_epic = await store.create_epic(
            s, project_id="p1", title="open", description=None, status="open",
            actor_user_id="alice", actor_email="alice@example.com",
        )
        await store.create_epic(
            s, project_id="p1", title="done", description=None, status="done",
            actor_user_id="alice", actor_email="alice@example.com",
        )

    body = api.get(
        "/api/v1/projects/p1/epics", params={"status": "open"}, headers=auth(ALICE_TOKEN)
    ).json()
    assert [item["id"] for item in body["items"]] == [open_epic.id]


# --------------------------------------------------------------------------
# Reading and updating epics -- WK-20260902-epic-update-and-move (issue #8).
#
# Before this, an epic could be created, listed and linked to, but never
# itself changed: `cancelled` -- the project's "there is no delete, use
# cancelled" answer -- was unreachable for an epic through any transport.
# --------------------------------------------------------------------------


async def test_get_epic_returns_an_etag(api) -> None:
    epic = await make_epic(api.factory)
    response = api.get(f"/api/v1/epics/{epic.id}", headers=auth(ALICE_TOKEN))
    assert response.status_code == 200
    assert response.headers["ETag"] == f'"{epic.revision}"'
    assert response.json()["id"] == epic.id


async def test_update_epic_requires_if_match(api) -> None:
    epic = await make_epic(api.factory)
    response = api.patch(
        f"/api/v1/epics/{epic.id}", json={"status": "in_progress"}, headers=auth(ALICE_TOKEN)
    )
    assert response.status_code == 428


async def test_update_epic_with_a_stale_etag_is_refused(api) -> None:
    epic = await make_epic(api.factory)
    response = api.patch(
        f"/api/v1/epics/{epic.id}",
        json={"status": "in_progress"},
        headers={**auth(ALICE_TOKEN), "If-Match": '"999"'},
    )
    assert response.status_code == 412
    assert response.json()["code"] == "stale_write"


async def test_update_epic_changes_only_the_mentioned_fields(api) -> None:
    """Positive control for the two If-Match negatives above."""
    epic = await make_epic(api.factory, title="Original")
    response = api.patch(
        f"/api/v1/epics/{epic.id}",
        json={"status": "cancelled"},
        headers={**auth(ALICE_TOKEN), "If-Match": f'"{epic.revision}"'},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "cancelled"
    assert body["title"] == "Original"
    assert body["revision"] == epic.revision + 1
    assert body["updatedBy"] == "alice@example.com"
    assert response.headers["ETag"] == f'"{epic.revision + 1}"'


async def test_update_epic_can_explicitly_clear_a_nullable_field(api) -> None:
    async with api.factory() as s:
        epic = await store.create_epic(
            s, project_id="p1", title="x", description="Track it", status=None,
            actor_user_id="alice", actor_email="alice@example.com",
        )
    response = api.patch(
        f"/api/v1/epics/{epic.id}",
        json={"description": None},
        headers={**auth(ALICE_TOKEN), "If-Match": f'"{epic.revision}"'},
    )
    assert response.status_code == 200
    assert response.json()["description"] is None


async def test_update_epic_rejects_an_unknown_status(api) -> None:
    epic = await make_epic(api.factory)
    response = api.patch(
        f"/api/v1/epics/{epic.id}",
        json={"status": "orbiting"},
        headers={**auth(ALICE_TOKEN), "If-Match": f'"{epic.revision}"'},
    )
    assert response.status_code == 400
    assert response.json()["details"][0]["field"] == "/status"


async def test_a_reader_cannot_update_an_epic(api) -> None:
    epic = await make_epic(api.factory)
    response = api.patch(
        f"/api/v1/epics/{epic.id}",
        json={"status": "cancelled"},
        headers={**auth(READER_TOKEN), "If-Match": f'"{epic.revision}"'},
    )
    assert response.status_code == 403
