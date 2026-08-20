"""Projects and the project operational dashboard — issue #5.

Weighted like `test_sessions.py`: authorization and the fields this build must
not invent (`ProjectModel.path`, always-zero `issues`/`artifacts` counts) get
more attention than serialization. Health and the `attention` filter are
derived data, so their tests manipulate the executor row directly rather than
trusting a fixture default.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from gateway.app.api.routes import projects as projects_routes
from gateway.app.api.setup import install_api_conventions
from gateway.app.db.base import Base
from gateway.app.db.session import get_session
from gateway.app.models.entities import ExecutorModel
from gateway.app.services import store
from shared.protocol import (
    ExecutorRegistration,
    ProjectRegistration,
    SubmitTaskRequest,
    TaskMode,
    TaskPriority,
    TaskState,
)


ALICE_TOKEN = "token-alice"    # sees project p1 only
ADMIN_TOKEN = "token-admin"    # sees everything
NOSCOPE_TOKEN = "token-noscope"  # authenticated, no codexbridge.read
EXPIRED_TOKEN = "token-expired"


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
                        "scopes": ["codexbridge.read"], "enabled": True,
                    },
                    {
                        "user_id": "noscope", "email": "noscope@example.com", "password_hash": "x",
                        "roles": [], "allowed_projects": ["p1"],
                        "scopes": ["codexbridge.task.cancel"], "enabled": True,
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
    """A real app over a real database, seeded with two projects and one executor.

    `E1` is registered but never marked connected — every test that needs a
    "live" or "stale" executor drives that through `store.mark_executor_connected`
    and `_set_last_seen` itself, so the starting point (health `degraded`, not
    `ok`) is not an assumption tests silently depend on.
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
                    allowed_projects=["p1", "p2"], enabled=True,
                )
            ],
            projects=[
                ProjectRegistration(
                    project_id=pid, name=f"Project {pid}", path=f"/srv/{pid}",
                    allowed_modes=[TaskMode.ANALYZE], max_timeout_seconds=600,
                    sensitive_patterns=[], enabled=True,
                )
                for pid in ("p1", "p2")
            ],
        )
        future = datetime.now(timezone.utc) + timedelta(hours=1)
        for token, user_id, scopes in (
            (ALICE_TOKEN, "alice", ["codexbridge.read"]),
            (NOSCOPE_TOKEN, "noscope", ["codexbridge.task.cancel"]),
            (ADMIN_TOKEN, "admin", ["codexbridge.admin"]),
        ):
            await store.create_oauth_access_token(
                seed, token=token, client_id="c", user_id=user_id,
                scopes=scopes, expires_at=future,
            )
        await store.create_oauth_access_token(
            seed, token=EXPIRED_TOKEN, client_id="c", user_id="alice",
            scopes=["codexbridge.read"],
            expires_at=datetime.now(timezone.utc) - timedelta(hours=1),
        )

    app = FastAPI(openapi_url=None, docs_url=None, redoc_url=None)
    install_api_conventions(app)
    app.include_router(projects_routes.router)

    async def override():
        async with factory() as s:
            yield s

    app.dependency_overrides[get_session] = override

    client = TestClient(app, raise_server_exceptions=False)
    client.factory = factory  # type: ignore[attr-defined]
    yield client
    await engine.dispose()


async def make_task(factory, project_id: str, instruction: str = "analyze it", state: str | None = None):
    async with factory() as s:
        task = await store.create_task(
            s,
            SubmitTaskRequest(
                executor_id="E1", project_id=project_id, instruction=instruction,
                mode=TaskMode.ANALYZE, priority=TaskPriority.NORMAL, timeout_seconds=60,
                expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
            ),
            executor_online=True,
        )
        if state:
            task = await store.update_task_state(s, task.id, TaskState(state))
        return task


async def mark_live(factory, executor_id: str = "E1") -> None:
    async with factory() as s:
        await store.mark_executor_connected(s, executor_id, True)


async def set_last_seen(factory, executor_id: str, when: datetime) -> None:
    """Force a specific `last_seen_at` without going through a heartbeat."""
    async with factory() as s:
        executor = await s.get(ExecutorModel, executor_id)
        executor.last_seen_at = when
        await s.commit()


async def add_project(factory, project_id: str, *, enabled: bool = True, executor_id: str | None = "E1") -> None:
    async with factory() as s:
        await store.upsert_registry(
            s,
            executors=[],
            projects=[
                ProjectRegistration(
                    project_id=project_id, name=f"Project {project_id}", path=f"/srv/{project_id}",
                    allowed_modes=[TaskMode.ANALYZE], max_timeout_seconds=600,
                    sensitive_patterns=[], enabled=enabled,
                )
            ],
        )
        if executor_id is not None:
            executor = await s.get(ExecutorModel, executor_id)
            metadata = json.loads(executor.metadata_json)
            allowed = metadata.setdefault("allowed_projects", [])
            if project_id not in allowed:
                allowed.append(project_id)
            executor.metadata_json = json.dumps(metadata)
            await s.commit()


def auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


# --------------------------------------------------------------------------
# Authentication and visibility
# --------------------------------------------------------------------------


async def test_projects_require_a_token(api) -> None:
    response = api.get("/api/v1/projects")
    assert response.status_code == 401
    assert response.json()["code"] == "unauthenticated"


async def test_an_expired_token_is_refused(api) -> None:
    assert api.get("/api/v1/projects", headers=auth(EXPIRED_TOKEN)).status_code == 401


async def test_a_token_without_the_read_scope_is_forbidden(api) -> None:
    response = api.get("/api/v1/projects", headers=auth(NOSCOPE_TOKEN))
    assert response.status_code == 403
    assert response.json()["code"] == "permission_denied"


async def test_a_project_outside_the_callers_scope_is_not_found_not_forbidden(api) -> None:
    """404 confirms the identifier exists, which is what probing is for."""
    assert api.get("/api/v1/projects/p1", headers=auth(ALICE_TOKEN)).status_code == 200
    response = api.get("/api/v1/projects/p2", headers=auth(ALICE_TOKEN))
    assert response.status_code == 404
    assert response.json()["code"] == "not_found"


async def test_the_same_scope_rule_applies_to_summary(api) -> None:
    response = api.get("/api/v1/projects/p2/summary", headers=auth(ALICE_TOKEN))
    assert response.status_code == 404


async def test_the_list_is_filtered_before_it_is_paged(api) -> None:
    body = api.get("/api/v1/projects", headers=auth(ALICE_TOKEN)).json()
    assert [item["id"] for item in body["items"]] == ["p1"]

    admin = api.get("/api/v1/projects", headers=auth(ADMIN_TOKEN)).json()
    assert {item["id"] for item in admin["items"]} == {"p1", "p2"}


async def test_a_user_with_no_projects_sees_nothing(api, users_file, monkeypatch) -> None:
    registry = json.loads(open(users_file).read())
    registry["users"][0]["allowed_projects"] = []
    with open(users_file, "w") as handle:
        json.dump(registry, handle)

    body = api.get("/api/v1/projects", headers=auth(ALICE_TOKEN)).json()
    assert body["items"] == []


async def test_the_project_body_never_carries_the_filesystem_path(api) -> None:
    text = api.get("/api/v1/projects/p1", headers=auth(ALICE_TOKEN)).text
    assert "/srv/p1" not in text
    assert "path" not in json.loads(text)

    summary_text = api.get("/api/v1/projects/p1/summary", headers=auth(ALICE_TOKEN)).text
    assert "/srv/p1" not in summary_text
    assert "path" not in json.loads(summary_text)


# --------------------------------------------------------------------------
# Health
# --------------------------------------------------------------------------


async def test_health_is_unknown_when_no_executor_names_the_project(api) -> None:
    await add_project(api.factory, "p3", executor_id=None)
    body = api.get("/api/v1/projects/p3", headers=auth(ADMIN_TOKEN)).json()
    assert body["health"] == "unknown"


async def test_health_is_degraded_when_the_assigned_executor_is_not_live(api) -> None:
    body = api.get("/api/v1/projects/p1", headers=auth(ALICE_TOKEN)).json()
    assert body["health"] == "degraded"


async def test_health_is_ok_when_the_assigned_executor_is_live(api) -> None:
    await mark_live(api.factory)
    body = api.get("/api/v1/projects/p1", headers=auth(ALICE_TOKEN)).json()
    assert body["health"] == "ok"


async def test_a_stale_heartbeat_reads_as_not_live_even_though_the_column_says_connected(api) -> None:
    """The bug `store.executor_is_live` exists to close.

    `connected` is flipped false only by a graceful disconnect. An abrupt kill
    leaves it `true` forever with no further heartbeat — simulated here by
    marking the executor connected and then rewinding `last_seen_at` past the
    grace window without going through a real disconnect.
    """
    from gateway.app.core.config import settings

    await mark_live(api.factory)
    await set_last_seen(
        api.factory, "E1", datetime.now(timezone.utc) - timedelta(seconds=settings.reconnect_grace_seconds + 1)
    )
    body = api.get("/api/v1/projects/p1", headers=auth(ALICE_TOKEN)).json()
    assert body["health"] == "degraded"


async def test_health_is_disabled_for_a_disabled_project_regardless_of_executors(api) -> None:
    await add_project(api.factory, "p3", enabled=False)
    await mark_live(api.factory)
    body = api.get("/api/v1/projects/p3", headers=auth(ADMIN_TOKEN)).json()
    assert body["health"] == "disabled"


# --------------------------------------------------------------------------
# Counts
# --------------------------------------------------------------------------


async def test_counts_reflect_task_state(api) -> None:
    await make_task(api.factory, "p1", state="awaiting_approval")
    await make_task(api.factory, "p1", state="running")
    await make_task(api.factory, "p1", state="completed")

    body = api.get("/api/v1/projects/p1", headers=auth(ALICE_TOKEN)).json()
    assert body["pendingDecisions"] == 1
    assert body["activeMissions"] == 2  # awaiting_approval + running
    assert body["totalSessions"] == 3


async def test_a_project_with_no_sessions_reports_zero_not_a_missing_field(api) -> None:
    body = api.get("/api/v1/projects/p1", headers=auth(ALICE_TOKEN)).json()
    assert body["pendingDecisions"] == 0
    assert body["activeMissions"] == 0
    assert body["totalSessions"] == 0
    assert body["lastActivityAt"] is None


async def test_last_activity_reflects_the_newest_session(api) -> None:
    await make_task(api.factory, "p1", instruction="first")
    newest = await make_task(api.factory, "p1", instruction="second")

    body = api.get("/api/v1/projects/p1", headers=auth(ALICE_TOKEN)).json()
    assert body["lastActivityAt"] is not None
    # The newest task's own createdAt, not merely "not null" — proves the query
    # picks the max, not the first row.
    async with api.factory() as s:
        from gateway.app.models.entities import TaskModel

        row = await s.get(TaskModel, newest.id)
    from gateway.app.api import timestamps

    assert body["lastActivityAt"] == timestamps.utc_z(row.created_at)


async def test_the_list_carries_the_same_counts_as_the_detail_read(api) -> None:
    """The list must not be a lighter lie than the detail endpoint."""
    await make_task(api.factory, "p1", state="awaiting_approval")
    detail = api.get("/api/v1/projects/p1", headers=auth(ALICE_TOKEN)).json()
    listed = api.get("/api/v1/projects", headers=auth(ALICE_TOKEN)).json()["items"][0]
    assert listed["pendingDecisions"] == detail["pendingDecisions"] == 1
    assert listed["health"] == detail["health"]


async def test_issues_and_artifacts_are_not_invented(api) -> None:
    """No `IssueModel`/`ArtifactModel` exists yet; an always-zero field would
    be a claim with nothing behind it (docs/api/README.md, "Projects")."""
    body = api.get("/api/v1/projects/p1", headers=auth(ALICE_TOKEN)).json()
    assert "issues" not in body
    assert "artifacts" not in body


# --------------------------------------------------------------------------
# Summary
# --------------------------------------------------------------------------


async def test_summary_reports_the_executor_breakdown(api) -> None:
    await mark_live(api.factory)
    body = api.get("/api/v1/projects/p1/summary", headers=auth(ALICE_TOKEN)).json()
    assert body["executors"] == [
        {"executorId": "E1", "connected": True, "lastSeenAt": body["executors"][0]["lastSeenAt"]}
    ]
    assert body["executors"][0]["lastSeenAt"] is not None
    assert body["generatedAt"] is not None


async def test_summary_never_reports_a_host_or_port(api) -> None:
    """`docs/api/README.md` "Fields that must never ship" — no hostname, no port."""
    text = api.get("/api/v1/projects/p1/summary", headers=auth(ALICE_TOKEN)).text
    assert "192.168" not in text
    assert "ws://" not in text and "wss://" not in text


# --------------------------------------------------------------------------
# Filters
# --------------------------------------------------------------------------


async def test_search_matches_id_or_name_case_insensitively(api) -> None:
    body = api.get("/api/v1/projects", headers=auth(ADMIN_TOKEN), params={"q": "P1"}).json()
    assert [item["id"] for item in body["items"]] == ["p1"]

    none = api.get("/api/v1/projects", headers=auth(ADMIN_TOKEN), params={"q": "nope"}).json()
    assert none["items"] == []


async def test_status_filters_by_enabled(api) -> None:
    await add_project(api.factory, "p3", enabled=False)

    enabled = api.get("/api/v1/projects", headers=auth(ADMIN_TOKEN), params={"status": "enabled"}).json()
    assert "p3" not in {item["id"] for item in enabled["items"]}

    disabled = api.get("/api/v1/projects", headers=auth(ADMIN_TOKEN), params={"status": "disabled"}).json()
    assert {item["id"] for item in disabled["items"]} == {"p3"}


async def test_an_invalid_status_value_is_rejected(api) -> None:
    response = api.get("/api/v1/projects", headers=auth(ADMIN_TOKEN), params={"status": "sideways"})
    assert response.status_code == 400
    assert response.json()["code"] == "validation_failed"


async def test_attention_surfaces_projects_needing_a_decision_or_unhealthy(api) -> None:
    await mark_live(api.factory)  # p1 and p2 both become "ok" via E1
    await make_task(api.factory, "p2", state="awaiting_approval")

    attention = api.get("/api/v1/projects", headers=auth(ADMIN_TOKEN), params={"attention": "true"}).json()
    assert {item["id"] for item in attention["items"]} == {"p2"}

    calm = api.get("/api/v1/projects", headers=auth(ADMIN_TOKEN), params={"attention": "false"}).json()
    assert {item["id"] for item in calm["items"]} == {"p1"}


async def test_attention_does_not_flag_a_disabled_project(api) -> None:
    """A disabled project was turned off on purpose; that is not a surprise."""
    await add_project(api.factory, "p3", enabled=False)
    attention = api.get("/api/v1/projects", headers=auth(ADMIN_TOKEN), params={"attention": "true"}).json()
    assert "p3" not in {item["id"] for item in attention["items"]}


# --------------------------------------------------------------------------
# Pagination
# --------------------------------------------------------------------------


async def test_the_cursor_walks_every_project_once(api) -> None:
    for index in range(5):
        await add_project(api.factory, f"z{index}", executor_id=None)

    seen: list[str] = []
    cursor = None
    for _ in range(10):
        params = {"limit": 3}
        if cursor:
            params["cursor"] = cursor
        body = api.get("/api/v1/projects", headers=auth(ADMIN_TOKEN), params=params).json()
        seen.extend(item["id"] for item in body["items"])
        cursor = body["page"]["nextCursor"]
        if not body["page"]["hasMore"]:
            break

    assert len(seen) == 7  # p1, p2, plus the 5 added here
    assert len(set(seen)) == 7, "a project was returned twice"


async def test_the_cursor_walks_every_project_once_under_attention(api) -> None:
    """The in-memory-paginated path (`attention` set) must not repeat or skip either."""
    for index in range(5):
        await add_project(api.factory, f"z{index}", executor_id=None)  # health "unknown" -> attention

    seen: list[str] = []
    cursor = None
    for _ in range(10):
        params = {"limit": 2, "attention": "true"}
        if cursor:
            params["cursor"] = cursor
        body = api.get("/api/v1/projects", headers=auth(ADMIN_TOKEN), params=params).json()
        seen.extend(item["id"] for item in body["items"])
        cursor = body["page"]["nextCursor"]
        if not body["page"]["hasMore"]:
            break

    # p1 and p2 are "degraded" (executor assigned, never marked live) so they
    # are attention-worthy too; all 7 projects qualify.
    assert len(seen) == 7
    assert len(set(seen)) == 7


async def test_a_cursor_from_another_filter_is_rejected(api) -> None:
    first = api.get("/api/v1/projects", headers=auth(ADMIN_TOKEN), params={"limit": 1}).json()
    cursor = first["page"]["nextCursor"] or "x"
    response = api.get(
        "/api/v1/projects", headers=auth(ADMIN_TOKEN), params={"cursor": cursor, "status": "disabled"}
    )
    assert response.status_code == 400


async def test_a_cursor_is_not_valid_for_another_caller(api) -> None:
    """The caller's scope is bound into the cursor, same rule as sessions."""
    first = api.get("/api/v1/projects", headers=auth(ADMIN_TOKEN), params={"limit": 1}).json()
    cursor = first["page"]["nextCursor"]
    assert cursor is not None
    response = api.get("/api/v1/projects", headers=auth(ALICE_TOKEN), params={"cursor": cursor})
    assert response.status_code == 400
