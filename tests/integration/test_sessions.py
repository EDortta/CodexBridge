"""Agent sessions, logs and control — issue #9.

These are the first authenticated endpoints of the mobile API, and the first
that return operator-authored content: the instruction, the project, the logs.
The tests are weighted accordingly — authorization and redaction get more
attention than serialization.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from gateway.app.api.routes import sessions as sessions_routes
from gateway.app.api.setup import install_api_conventions
from gateway.app.db.base import Base
from gateway.app.db.session import get_session
from gateway.app.services import store
from shared.protocol import (
    ExecutorRegistration,
    ProjectRegistration,
    SubmitTaskRequest,
    TaskMode,
    TaskPriority,
    TaskState,
)


ALICE_TOKEN = "token-alice"          # sees project p1 only
ADMIN_TOKEN = "token-admin"          # sees everything
READER_TOKEN = "token-reader"        # p1, but no cancel scope
EXPIRED_TOKEN = "token-expired"


class _Hub:
    """Stands in for the agent hub, including the slot bookkeeping.

    `running_tasks` and `mark_task_finished` are here because omitting them is
    what hid a real defect: the HTTP stop never released the executor's
    concurrency slot, so a cancelled RUNNING task pinned it for the life of the
    process and an executor with `max_concurrent_tasks: 1` was never dispatched
    again. A stub narrower than the real object cannot fail that way.
    """

    def __init__(self, connected: bool = True) -> None:
        self.connected = connected
        self.sent: list = []
        self.running_tasks: dict[str, set[str]] = {}

    def is_connected(self, executor_id: str) -> bool:
        return self.connected

    async def send(self, executor_id: str, envelope) -> None:
        self.sent.append((executor_id, envelope))

    async def mark_task_finished(self, executor_id: str, task_id: str) -> None:
        self.running_tasks.setdefault(executor_id, set()).discard(task_id)


@pytest.fixture
def users_file(tmp_path):
    path = tmp_path / "users.json"
    path.write_text(
        json.dumps(
            {
                "users": [
                    {
                        "user_id": "alice",
                        "email": "alice@example.com",
                        "password_hash": "x",
                        "roles": [],
                        "allowed_projects": ["p1"],
                        "scopes": ["codexbridge.read", "codexbridge.task.cancel"],
                        "enabled": True,
                    },
                    {
                        "user_id": "reader",
                        "email": "reader@example.com",
                        "password_hash": "x",
                        "roles": [],
                        "allowed_projects": ["p1"],
                        "scopes": ["codexbridge.read"],
                        "enabled": True,
                    },
                    {
                        "user_id": "admin",
                        "email": "admin@example.com",
                        "password_hash": "x",
                        "roles": ["admin"],
                        "allowed_projects": [],
                        "scopes": ["codexbridge.admin"],
                        "enabled": True,
                    },
                ]
            }
        ),
        encoding="utf-8",
    )
    return str(path)


@pytest.fixture
async def api(users_file, monkeypatch):
    """A real app over a real database, seeded with two projects."""
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
            (ALICE_TOKEN, "alice", ["codexbridge.read", "codexbridge.task.cancel"]),
            (READER_TOKEN, "reader", ["codexbridge.read"]),
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
    app.include_router(sessions_routes.router)

    async def override():
        async with factory() as s:
            yield s

    app.dependency_overrides[get_session] = override

    hub = _Hub()
    import gateway.app.main as main_module

    monkeypatch.setattr(main_module, "hub", hub, raising=False)

    client = TestClient(app, raise_server_exceptions=False)
    client.hub = hub          # type: ignore[attr-defined]
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


def auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


# --------------------------------------------------------------------------
# Authentication and visibility
# --------------------------------------------------------------------------


async def test_sessions_require_a_token(api) -> None:
    """These endpoints carry the operator's instructions and logs."""
    response = api.get("/api/v1/sessions")
    assert response.status_code == 401
    assert response.json()["code"] == "unauthenticated"
    assert "Bearer" in response.headers.get("WWW-Authenticate", "")


async def test_an_expired_token_is_refused(api) -> None:
    response = api.get("/api/v1/sessions", headers=auth(EXPIRED_TOKEN))
    assert response.status_code == 401


async def test_a_token_without_the_scope_cannot_stop(api) -> None:
    task = await make_task(api.factory, "p1", state="running")
    response = api.post(
        f"/api/v1/sessions/{task.id}/stop",
        headers={**auth(READER_TOKEN), "If-Match": f'"{task.revision}"'},
    )
    assert response.status_code == 403
    assert response.json()["code"] == "permission_denied"


async def test_a_session_in_an_invisible_project_is_not_found_not_forbidden(api) -> None:
    """403 confirms the identifier exists, which is what probing is for."""
    mine = await make_task(api.factory, "p1")
    theirs = await make_task(api.factory, "p2")

    assert api.get(f"/api/v1/sessions/{mine.id}", headers=auth(ALICE_TOKEN)).status_code == 200
    response = api.get(f"/api/v1/sessions/{theirs.id}", headers=auth(ALICE_TOKEN))
    assert response.status_code == 404
    assert response.json()["code"] == "not_found"


async def test_the_list_is_filtered_before_it_is_paged(api) -> None:
    """Filtering after loading makes hasMore describe rows the caller cannot see."""
    await make_task(api.factory, "p1")
    await make_task(api.factory, "p2")
    await make_task(api.factory, "p2")

    body = api.get("/api/v1/sessions", headers=auth(ALICE_TOKEN)).json()
    assert [item["projectId"] for item in body["items"]] == ["p1"]
    assert body["page"]["hasMore"] is False

    admin = api.get("/api/v1/sessions", headers=auth(ADMIN_TOKEN)).json()
    assert len(admin["items"]) == 3


async def test_a_user_with_no_projects_sees_nothing(api, users_file, monkeypatch) -> None:
    """An empty allowlist must not be mistaken for "unrestricted"."""
    from gateway.app.api.auth import visible_projects
    from gateway.app.core.users import AuthenticatedPrincipal

    nobody = AuthenticatedPrincipal(user_id="n", email="n@x", allowed_projects=[], scopes=["codexbridge.read"])
    assert visible_projects(nobody) == []
    admin = AuthenticatedPrincipal(user_id="a", email="a@x", roles=["admin"])
    assert visible_projects(admin) is None


async def test_the_session_body_never_carries_the_project_path(api) -> None:
    """`ProjectModel.path` is the canonical trap named by the contract."""
    task = await make_task(api.factory, "p1")
    text = api.get(f"/api/v1/sessions/{task.id}", headers=auth(ALICE_TOKEN)).text
    assert "/srv/p1" not in text
    assert "path" not in json.loads(text)


# --------------------------------------------------------------------------
# Pagination
# --------------------------------------------------------------------------


async def test_the_cursor_walks_every_session_once(api) -> None:
    for index in range(7):
        await make_task(api.factory, "p1", instruction=f"task {index}")

    seen: list[str] = []
    cursor = None
    for _ in range(10):
        params = {"limit": 3}
        if cursor:
            params["cursor"] = cursor
        body = api.get("/api/v1/sessions", headers=auth(ALICE_TOKEN), params=params).json()
        seen.extend(item["id"] for item in body["items"])
        cursor = body["page"]["nextCursor"]
        if not body["page"]["hasMore"]:
            break

    assert len(seen) == 7
    assert len(set(seen)) == 7, "a session was returned twice"


async def test_a_cursor_from_another_filter_is_rejected(api) -> None:
    await make_task(api.factory, "p1")
    first = api.get("/api/v1/sessions", headers=auth(ALICE_TOKEN), params={"limit": 1}).json()
    cursor = first["page"]["nextCursor"] or "x"
    response = api.get(
        "/api/v1/sessions", headers=auth(ALICE_TOKEN), params={"cursor": cursor, "state": "running"}
    )
    assert response.status_code == 400


# --------------------------------------------------------------------------
# Logs and redaction
# --------------------------------------------------------------------------


async def test_logs_page_by_offset_and_resume(api) -> None:
    task = await make_task(api.factory, "p1")
    async with api.factory() as s:
        for offset in range(5):
            await store.append_log(s, task.id, offset, "stdout", f"line {offset}")

    first = api.get(
        f"/api/v1/sessions/{task.id}/logs", headers=auth(ALICE_TOKEN), params={"limit": 2}
    ).json()
    assert [row["offset"] for row in first["items"]] == [0, 1]
    assert first["hasMore"] is True

    second = api.get(
        f"/api/v1/sessions/{task.id}/logs",
        headers=auth(ALICE_TOKEN),
        params={"limit": 2, "offset": first["nextOffset"]},
    ).json()
    assert [row["offset"] for row in second["items"]] == [2, 3]


@pytest.mark.parametrize(
    ("stored", "must_not_contain"),
    [
        ("connecting wss://host/agent/ws?executor_id=devel3&token=abc123secret", "abc123secret"),
        ("reading /home/esteban/Sync/Projects/secret.py", "/home/esteban"),
        ("upstream 192.168.71.248:18080 refused", "192.168.71.248:18080"),
        ("Authorization: Bearer sk-abcdefghijklmnop", "sk-abcdefghijklmnop"),
    ],
)
async def test_log_lines_are_redacted_on_the_way_out(api, stored: str, must_not_contain: str) -> None:
    """Stored log text is not safe: the gateway's own log carried a token (#15)."""
    task = await make_task(api.factory, "p1")
    async with api.factory() as s:
        await store.append_log(s, task.id, 0, "stdout", stored)

    text = api.get(f"/api/v1/sessions/{task.id}/logs", headers=auth(ALICE_TOKEN)).text
    assert must_not_contain not in text


async def test_logs_of_an_invisible_session_are_not_found(api) -> None:
    theirs = await make_task(api.factory, "p2")
    assert api.get(f"/api/v1/sessions/{theirs.id}/logs", headers=auth(ALICE_TOKEN)).status_code == 404


# --------------------------------------------------------------------------
# Stop
# --------------------------------------------------------------------------


async def test_stop_requires_if_match(api) -> None:
    task = await make_task(api.factory, "p1", state="running")
    response = api.post(f"/api/v1/sessions/{task.id}/stop", headers=auth(ALICE_TOKEN))
    assert response.status_code == 428


async def test_stop_with_a_stale_etag_is_refused(api) -> None:
    task = await make_task(api.factory, "p1", state="running")
    response = api.post(
        f"/api/v1/sessions/{task.id}/stop",
        headers={**auth(ALICE_TOKEN), "If-Match": '"1"'},
    )
    assert response.status_code == 412
    assert response.json()["code"] == "stale_write"


async def test_stop_cancels_and_tells_the_executor(api) -> None:
    task = await make_task(api.factory, "p1", state="running")
    detail = api.get(f"/api/v1/sessions/{task.id}", headers=auth(ALICE_TOKEN))
    etag = detail.headers["ETag"]

    response = api.post(
        f"/api/v1/sessions/{task.id}/stop", headers={**auth(ALICE_TOKEN), "If-Match": etag}
    )
    assert response.status_code == 200
    assert response.json()["state"] == TaskState.CANCELLED.value
    assert response.headers["ETag"] != etag, "the revision must move"
    assert api.hub.sent and api.hub.sent[0][0] == "E1"


async def test_stopping_a_finished_session_is_a_conflict(api) -> None:
    task = await make_task(api.factory, "p1", state="completed")
    detail = api.get(f"/api/v1/sessions/{task.id}", headers=auth(ALICE_TOKEN))
    response = api.post(
        f"/api/v1/sessions/{task.id}/stop",
        headers={**auth(ALICE_TOKEN), "If-Match": detail.headers["ETag"]},
    )
    assert response.status_code == 409
    assert response.json()["code"] == "conflict"


async def test_a_disconnected_executor_does_not_block_the_stop(api) -> None:
    """Refusing here strands the operator exactly when they most want to stop."""
    api.hub.connected = False
    task = await make_task(api.factory, "p1", state="running")
    detail = api.get(f"/api/v1/sessions/{task.id}", headers=auth(ALICE_TOKEN))
    response = api.post(
        f"/api/v1/sessions/{task.id}/stop",
        headers={**auth(ALICE_TOKEN), "If-Match": detail.headers["ETag"]},
    )
    assert response.status_code == 200
    assert response.json()["state"] == TaskState.CANCELLED.value
    assert api.hub.sent == []
    # And the response says so, instead of implying the run stopped. Nothing
    # replays task.cancel on reconnect, so the executor keeps going.
    assert response.json()["executorNotified"] is False


async def test_a_retried_stop_replays_instead_of_acting_twice(api) -> None:
    task = await make_task(api.factory, "p1", state="running")
    detail = api.get(f"/api/v1/sessions/{task.id}", headers=auth(ALICE_TOKEN))
    headers = {**auth(ALICE_TOKEN), "If-Match": detail.headers["ETag"], "Idempotency-Key": "k-1"}

    first = api.post(f"/api/v1/sessions/{task.id}/stop", headers=headers)
    second = api.post(f"/api/v1/sessions/{task.id}/stop", headers=headers)

    assert first.status_code == 200
    assert second.status_code == 200
    assert second.headers.get("Idempotent-Replay") == "true"
    assert second.json() == first.json()
    assert len(api.hub.sent) == 1, "the executor was told twice"


async def test_a_failed_stop_does_not_keep_the_key_claimed(api) -> None:
    """One transient refusal must not lock the key for its whole TTL."""
    task = await make_task(api.factory, "p1", state="running")
    headers = {**auth(ALICE_TOKEN), "If-Match": '"999"', "Idempotency-Key": "k-2"}
    assert api.post(f"/api/v1/sessions/{task.id}/stop", headers=headers).status_code == 412

    detail = api.get(f"/api/v1/sessions/{task.id}", headers=auth(ALICE_TOKEN))
    good = {**auth(ALICE_TOKEN), "If-Match": detail.headers["ETag"], "Idempotency-Key": "k-2"}
    assert api.post(f"/api/v1/sessions/{task.id}/stop", headers=good).status_code == 200


# --------------------------------------------------------------------------
# explain-error
# --------------------------------------------------------------------------


async def test_explain_error_reports_the_recorded_evidence(api) -> None:
    task = await make_task(api.factory, "p1", state="running")
    async with api.factory() as s:
        await store.append_log(s, task.id, 0, "stderr", "boom at /opt/codex-bridge/x.py")
        await store.update_task_state(s, task.id, TaskState.FAILED, error="exit code 1")

    body = api.post(f"/api/v1/sessions/{task.id}/explain-error", headers=auth(ALICE_TOKEN)).json()
    assert body["sessionId"] == task.id
    assert body["reasons"], "a failed session must say something"
    assert body["lastError"] == "exit code 1"
    assert body["recentStderr"]
    assert "/opt/codex-bridge" not in json.dumps(body), "stderr must be redacted too"


async def test_explain_error_on_a_healthy_session_says_so(api) -> None:
    task = await make_task(api.factory, "p1")
    body = api.post(f"/api/v1/sessions/{task.id}/explain-error", headers=auth(ALICE_TOKEN)).json()
    assert body["reasons"] == ["No failure recorded for this session."]


async def test_explain_error_of_an_invisible_session_is_not_found(api) -> None:
    theirs = await make_task(api.factory, "p2")
    response = api.post(f"/api/v1/sessions/{theirs.id}/explain-error", headers=auth(ALICE_TOKEN))
    assert response.status_code == 404


async def test_stop_releases_the_executor_slot(api) -> None:
    """A cancelled RUNNING task must not pin the executor's concurrency slot.

    Every other terminal path calls `mark_task_finished`. The HTTP stop did not,
    so an executor with `max_concurrent_tasks: 1` was never dispatched another
    task for the life of the gateway process — queued work sat there with a
    connected, idle executor.
    """
    task = await make_task(api.factory, "p1", state="running")
    api.hub.running_tasks["E1"] = {task.id}

    detail = api.get(f"/api/v1/sessions/{task.id}", headers=auth(ALICE_TOKEN))
    response = api.post(
        f"/api/v1/sessions/{task.id}/stop", headers={**auth(ALICE_TOKEN), "If-Match": detail.headers["ETag"]}
    )

    assert response.status_code == 200
    assert api.hub.running_tasks["E1"] == set(), "the slot is still held"


async def test_stop_reports_whether_the_executor_was_told(api) -> None:
    task = await make_task(api.factory, "p1", state="running")
    detail = api.get(f"/api/v1/sessions/{task.id}", headers=auth(ALICE_TOKEN))
    body = api.post(
        f"/api/v1/sessions/{task.id}/stop", headers={**auth(ALICE_TOKEN), "If-Match": detail.headers["ETag"]}
    ).json()
    assert body["executorNotified"] is True


async def test_a_cursor_on_a_whole_second_timestamp_does_not_truncate(api) -> None:
    """`str(datetime)` drops ".000000" on a whole second.

    The cursor then matched nothing and the list ended early — no error, no 400,
    just sessions the client was told did not exist.
    """
    from sqlalchemy import update

    from gateway.app.models.entities import TaskModel

    ids = []
    for index in range(4):
        task = await make_task(api.factory, "p1", instruction=f"t{index}")
        ids.append(task.id)
    async with api.factory() as s:
        # Whole seconds, descending, so every page boundary lands on one.
        for offset, task_id in enumerate(ids):
            await s.execute(
                update(TaskModel)
                .where(TaskModel.id == task_id)
                .values(created_at=datetime(2026, 8, 10, 12, 0, offset, 0, tzinfo=timezone.utc))
            )
        await s.commit()

    seen: list[str] = []
    cursor = None
    for _ in range(10):
        params = {"limit": 2}
        if cursor:
            params["cursor"] = cursor
        body = api.get("/api/v1/sessions", headers=auth(ALICE_TOKEN), params=params).json()
        seen.extend(item["id"] for item in body["items"])
        cursor = body["page"]["nextCursor"]
        if not body["page"]["hasMore"]:
            break

    assert sorted(seen) == sorted(ids), f"the list truncated: got {len(seen)} of {len(ids)}"


async def test_a_cursor_is_not_valid_for_another_caller(api) -> None:
    """A cursor issued to one principal must not position another's pagination.

    The project filter still holds either way, so no forbidden row is returned —
    but the second caller silently skips rows it is entitled to see, while
    `hasMore` asserts the page is authoritative.
    """
    for index in range(4):
        await make_task(api.factory, "p1", instruction=f"t{index}")

    admin_page = api.get("/api/v1/sessions", headers=auth(ADMIN_TOKEN), params={"limit": 1}).json()
    cursor = admin_page["page"]["nextCursor"]
    assert cursor

    response = api.get("/api/v1/sessions", headers=auth(ALICE_TOKEN), params={"cursor": cursor})
    assert response.status_code == 400
    assert response.json()["code"] == "validation_failed"


async def test_the_replayed_stop_carries_an_etag(api) -> None:
    """The contract declares ETag on this 200, and a retrying client needs one."""
    task = await make_task(api.factory, "p1", state="running")
    detail = api.get(f"/api/v1/sessions/{task.id}", headers=auth(ALICE_TOKEN))
    headers = {**auth(ALICE_TOKEN), "If-Match": detail.headers["ETag"], "Idempotency-Key": "k-etag"}

    api.post(f"/api/v1/sessions/{task.id}/stop", headers=headers)
    replay = api.post(f"/api/v1/sessions/{task.id}/stop", headers=headers)

    assert replay.headers.get("Idempotent-Replay") == "true"
    assert "ETag" in replay.headers


async def test_explain_error_reports_the_newest_stderr(api) -> None:
    """Reading the first 1000 lines and slicing the end returns the OLDEST.

    On a long session that is stale evidence presented as recent, and a way for
    whoever produces output to push their own traces out of view.
    """
    task = await make_task(api.factory, "p1", state="running")
    async with api.factory() as s:
        for offset in range(1100):
            await store.append_log(s, task.id, offset, "stderr", f"line {offset}")

    body = api.post(f"/api/v1/sessions/{task.id}/explain-error", headers=auth(ALICE_TOKEN)).json()
    offsets = [row["offset"] for row in body["recentStderr"]]
    assert offsets and max(offsets) == 1099, f"newest offset returned was {max(offsets)}"


@pytest.mark.parametrize(
    ("stored", "must_not_contain"),
    [
        ("redis://:s3cr3tpw@10.0.0.5:6379/0", "s3cr3tpw"),
        ("postgres://user:pw123456@db-primary.internal:5432/app", "pw123456"),
        ("github pat github_pat_11ABCDEFG0abcdefghijklmnopqrstuvwxyz0123456789", "github_pat_11"),
        ("AWS key AKIAIOSFODNN7EXAMPLE", "AKIAIOSFODNN7EXAMPLE"),
        ('response: {"password": "hunter2"}', "hunter2"),
        ("Authorization: Basic YWxpY2U6c3VwZXJzZWNyZXQ=", "YWxpY2U6c3VwZXJzZWNyZXQ"),
        ("X-Api-Key: sekret1234567890", "sekret1234567890"),
        ("jwt eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxIn0.abcdefghijklmnop", "eyJhbGciOiJIUzI1NiJ9"),
        ("relative ../../etc/shadow", "etc/shadow"),
        ("windows C:\\Users\\esteban\\.ssh\\id_rsa", "esteban"),
        ("bare 10.0.0.5 host", "10.0.0.5"),
        ("host db.internal.corp", "db.internal.corp"),
    ],
)
async def test_more_secret_shapes_are_redacted(api, stored: str, must_not_contain: str) -> None:
    """Each of these reached the client verbatim before an adversarial pass."""
    task = await make_task(api.factory, "p1")
    async with api.factory() as s:
        await store.append_log(s, task.id, 0, "stdout", stored)
    text = api.get(f"/api/v1/sessions/{task.id}/logs", headers=auth(ALICE_TOKEN)).text
    assert must_not_contain not in text


async def test_terminal_escapes_are_stripped(api) -> None:
    """`\x1b]0;title\x07` retitles a CLI consumer's window."""
    task = await make_task(api.factory, "p1")
    async with api.factory() as s:
        await store.append_log(s, task.id, 0, "stdout", "\x1b[31mred\x1b[0m \x1b]0;pwned\x07")
    line = api.get(f"/api/v1/sessions/{task.id}/logs", headers=auth(ALICE_TOKEN)).json()["items"][0]["line"]
    assert "\x1b" not in line and "pwned" not in line


async def test_the_instruction_is_redacted_like_everything_else(api) -> None:
    """It sat raw beside a redacted lastError; it is free text a human writes."""
    task = await make_task(api.factory, "p1", instruction="deploy with token=abcdef1234567890 from /home/esteban/app")
    body = api.get(f"/api/v1/sessions/{task.id}", headers=auth(ALICE_TOKEN)).json()
    assert "abcdef1234567890" not in body["instruction"]
    assert "/home/esteban" not in body["instruction"]
