"""Conversations and contextual messaging — issue #10.

Weighted toward the acceptance criteria named explicitly: at least one context
reference, idempotent offline message replay and duplicate prevention, stable
pagination, and unauthorized entity references answering `404` rather than
disclosing what the caller cannot see — plus the authorization and
idempotency conventions every other write endpoint in this API already
carries.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from gateway.app.api.routes import conversations as conversations_routes
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
)


ALICE_TOKEN = "token-alice"    # p1 only, has conversations.write
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
                        "scopes": ["codexbridge.read", "codexbridge.conversations.write"], "enabled": True,
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
            (ALICE_TOKEN, "alice", ["codexbridge.read", "codexbridge.conversations.write"]),
            (READER_TOKEN, "reader", ["codexbridge.read"]),
            (ADMIN_TOKEN, "admin", ["codexbridge.admin"]),
        ):
            await store.create_oauth_access_token(
                seed, token=token, client_id="c", user_id=user_id, scopes=scopes, expires_at=future
            )

    app = FastAPI(openapi_url=None, docs_url=None, redoc_url=None)
    install_api_conventions(app)
    app.include_router(conversations_routes.router)

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


async def make_task(factory, project_id: str = "p1"):
    async with factory() as s:
        return await store.create_task(
            s,
            SubmitTaskRequest(
                executor_id="E1", project_id=project_id, instruction="analyze it",
                mode=TaskMode.ANALYZE, priority=TaskPriority.NORMAL, timeout_seconds=60,
                expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
            ),
            executor_online=True,
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


async def make_conversation(factory, *, project_id: str = "p1", context: list[dict] | None = None):
    async with factory() as s:
        return await store.create_conversation(
            s,
            project_id=project_id,
            title="Existing",
            context=context or [{"type": "project", "id": project_id}],
            actor_user_id="alice",
            actor_email="alice@example.com",
        )


def create_payload(context: list[dict], title: str | None = None) -> dict:
    body: dict = {"context": context}
    if title is not None:
        body["title"] = title
    return body


# --------------------------------------------------------------------------
# Authentication, authorization and project visibility
# --------------------------------------------------------------------------


async def test_conversations_require_a_token(api) -> None:
    assert api.get("/api/v1/conversations").status_code == 401
    assert api.post(
        "/api/v1/conversations", json=create_payload([{"type": "project", "id": "p1"}])
    ).status_code == 401


async def test_reader_cannot_create_a_conversation_or_post_a_message(api) -> None:
    conversation = await make_conversation(api.factory)
    response = api.post(
        "/api/v1/conversations",
        json=create_payload([{"type": "project", "id": "p1"}]),
        headers=auth(READER_TOKEN),
    )
    assert response.status_code == 403
    assert response.json()["code"] == "permission_denied"

    response = api.post(
        f"/api/v1/conversations/{conversation.id}/messages",
        json={"body": "hello"},
        headers=auth(READER_TOKEN),
    )
    assert response.status_code == 403


async def test_reader_can_still_list_get_and_read_messages(api) -> None:
    conversation = await make_conversation(api.factory)
    assert api.get("/api/v1/conversations", headers=auth(READER_TOKEN)).status_code == 200
    assert api.get(f"/api/v1/conversations/{conversation.id}", headers=auth(READER_TOKEN)).status_code == 200
    assert (
        api.get(f"/api/v1/conversations/{conversation.id}/messages", headers=auth(READER_TOKEN)).status_code
        == 200
    )


async def test_a_conversation_in_an_invisible_project_is_not_found(api) -> None:
    """404, never 403 — confirming existence is what probing is for."""
    theirs = await make_conversation(api.factory, project_id="p2")
    for response in (
        api.get(f"/api/v1/conversations/{theirs.id}", headers=auth(ALICE_TOKEN)),
        api.get(f"/api/v1/conversations/{theirs.id}/messages", headers=auth(ALICE_TOKEN)),
        api.post(f"/api/v1/conversations/{theirs.id}/messages", json={"body": "x"}, headers=auth(ALICE_TOKEN)),
    ):
        assert response.status_code == 404
        assert response.json()["code"] == "not_found"


# --------------------------------------------------------------------------
# Context references — the acceptance criterion
# --------------------------------------------------------------------------


async def test_create_requires_at_least_one_context_reference(api) -> None:
    response = api.post("/api/v1/conversations", json={"context": []}, headers=auth(ALICE_TOKEN))
    assert response.status_code == 422


async def test_create_rejects_an_unknown_context_type(api) -> None:
    response = api.post(
        "/api/v1/conversations",
        json=create_payload([{"type": "artifact", "id": "p1"}]),
        headers=auth(ALICE_TOKEN),
    )
    assert response.status_code == 400
    assert response.json()["details"][0]["code"] == "invalid_context_type"


async def test_create_with_a_context_reference_in_a_hidden_project_is_not_found(api) -> None:
    """Unauthorized entity references are rejected without disclosing hidden resources."""
    hidden_task = await make_task(api.factory, "p2")
    response = api.post(
        "/api/v1/conversations",
        json=create_payload([{"type": "session", "id": hidden_task.id}]),
        headers=auth(ALICE_TOKEN),
    )
    assert response.status_code == 404
    assert response.json()["code"] == "not_found"


async def test_create_with_an_unknown_context_id_is_not_found(api) -> None:
    """A reference to something that does not exist answers exactly like a hidden one."""
    response = api.post(
        "/api/v1/conversations",
        json=create_payload([{"type": "issue", "id": "does-not-exist"}]),
        headers=auth(ALICE_TOKEN),
    )
    assert response.status_code == 404


async def test_create_rejects_context_references_spanning_two_projects(api) -> None:
    task_p1 = await make_task(api.factory, "p1")
    task_p2 = await make_task(api.factory, "p2")
    response = api.post(
        "/api/v1/conversations",
        json=create_payload(
            [{"type": "session", "id": task_p1.id}, {"type": "session", "id": task_p2.id}]
        ),
        headers=auth(ADMIN_TOKEN),
    )
    assert response.status_code == 400
    assert response.json()["details"][0]["code"] == "mixed_project"


async def test_create_accepts_a_session_decision_or_mission_reference_to_the_same_task(api) -> None:
    """session/decision/mission all name the same TaskModel row."""
    task = await make_task(api.factory, "p1")
    for context_type in ("session", "decision", "mission"):
        response = api.post(
            "/api/v1/conversations",
            json=create_payload([{"type": context_type, "id": task.id}]),
            headers=auth(ALICE_TOKEN),
        )
        assert response.status_code == 201, response.text
        assert response.json()["projectId"] == "p1"


async def test_create_derives_project_id_from_the_context_and_deduplicates(api) -> None:
    issue = await make_issue(api.factory, "p1")
    response = api.post(
        "/api/v1/conversations",
        json=create_payload(
            [
                {"type": "issue", "id": issue.id},
                {"type": "issue", "id": issue.id},
                {"type": "project", "id": "p1"},
            ],
            title="About this issue",
        ),
        headers=auth(ALICE_TOKEN),
    )
    assert response.status_code == 201
    body = response.json()
    assert body["projectId"] == "p1"
    assert body["title"] == "About this issue"
    assert len(body["context"]) == 2
    assert {"type": "issue", "id": issue.id} in body["context"]
    assert {"type": "project", "id": "p1"} in body["context"]
    # The creator is caught up on what they just wrote.
    assert body["unread"] is False
    assert body["lastActivityAt"] is None


async def test_a_project_outside_the_caller_visibility_is_not_found_when_used_as_context(api) -> None:
    response = api.post(
        "/api/v1/conversations",
        json=create_payload([{"type": "project", "id": "p2"}]),
        headers=auth(ALICE_TOKEN),
    )
    assert response.status_code == 404


# --------------------------------------------------------------------------
# Idempotent creation, and duplicate prevention
# --------------------------------------------------------------------------


async def test_a_retried_conversation_create_does_not_create_a_second_conversation(api) -> None:
    headers = {**auth(ALICE_TOKEN), "Idempotency-Key": "conv-1"}
    payload = create_payload([{"type": "project", "id": "p1"}])

    first = api.post("/api/v1/conversations", json=payload, headers=headers)
    second = api.post("/api/v1/conversations", json=payload, headers=headers)

    assert first.status_code == 201
    assert second.status_code == 201
    assert second.headers.get("Idempotent-Replay") == "true"
    assert second.json() == first.json()

    listed = api.get("/api/v1/conversations", headers=auth(ALICE_TOKEN)).json()
    assert len(listed["items"]) == 1


# --------------------------------------------------------------------------
# Messages: markdown bodies, attachments, idempotent offline replay
# --------------------------------------------------------------------------


async def test_post_message_stores_markdown_and_attachments_verbatim(api) -> None:
    conversation = await make_conversation(api.factory)
    response = api.post(
        f"/api/v1/conversations/{conversation.id}/messages",
        json={"body": "**bold** and a [link](https://example.com)", "attachments": ["artifact-1", "file-2"]},
        headers=auth(ALICE_TOKEN),
    )
    assert response.status_code == 201
    body = response.json()
    assert body["body"] == "**bold** and a [link](https://example.com)"
    assert body["attachments"] == ["artifact-1", "file-2"]
    assert body["author"] == "alice@example.com"
    assert body["conversationId"] == conversation.id


async def test_post_message_rejects_an_empty_body(api) -> None:
    conversation = await make_conversation(api.factory)
    response = api.post(
        f"/api/v1/conversations/{conversation.id}/messages",
        json={"body": "   "},
        headers=auth(ALICE_TOKEN),
    )
    assert response.status_code == 400
    assert response.json()["details"][0]["field"] == "/body"


async def test_a_retried_message_post_does_not_create_a_second_message(api) -> None:
    """Message creation is idempotent for offline retries — the acceptance criterion."""
    conversation = await make_conversation(api.factory)
    headers = {**auth(ALICE_TOKEN), "Idempotency-Key": "msg-1"}
    payload = {"body": "sent once"}

    first = api.post(f"/api/v1/conversations/{conversation.id}/messages", json=payload, headers=headers)
    second = api.post(f"/api/v1/conversations/{conversation.id}/messages", json=payload, headers=headers)

    assert first.status_code == 201
    assert second.status_code == 201
    assert second.headers.get("Idempotent-Replay") == "true"
    assert second.json() == first.json()

    listed = api.get(
        f"/api/v1/conversations/{conversation.id}/messages", headers=auth(ALICE_TOKEN)
    ).json()
    assert len(listed["items"]) == 1


async def test_the_same_key_with_a_different_body_is_a_conflict(api) -> None:
    """Reusing a key for a different payload is a client bug, not a silent replay."""
    conversation = await make_conversation(api.factory)
    headers = {**auth(ALICE_TOKEN), "Idempotency-Key": "msg-2"}
    first = api.post(
        f"/api/v1/conversations/{conversation.id}/messages", json={"body": "first"}, headers=headers
    )
    assert first.status_code == 201

    second = api.post(
        f"/api/v1/conversations/{conversation.id}/messages", json={"body": "different"}, headers=headers
    )
    assert second.status_code == 409

    listed = api.get(
        f"/api/v1/conversations/{conversation.id}/messages", headers=auth(ALICE_TOKEN)
    ).json()
    assert len(listed["items"]) == 1


async def test_a_message_without_an_idempotency_key_is_never_deduplicated(api) -> None:
    """No key means no replay protection — each call is a genuinely new message."""
    conversation = await make_conversation(api.factory)
    payload = {"body": "sent twice on purpose"}
    api.post(f"/api/v1/conversations/{conversation.id}/messages", json=payload, headers=auth(ALICE_TOKEN))
    api.post(f"/api/v1/conversations/{conversation.id}/messages", json=payload, headers=auth(ALICE_TOKEN))

    listed = api.get(
        f"/api/v1/conversations/{conversation.id}/messages", headers=auth(ALICE_TOKEN)
    ).json()
    assert len(listed["items"]) == 2


# --------------------------------------------------------------------------
# Unread and last-activity
# --------------------------------------------------------------------------


async def test_a_new_message_makes_the_conversation_unread_for_others(api) -> None:
    conversation = await make_conversation(api.factory)
    assert api.get(f"/api/v1/conversations/{conversation.id}", headers=auth(READER_TOKEN)).json()["unread"] is False

    api.post(
        f"/api/v1/conversations/{conversation.id}/messages", json={"body": "hi"}, headers=auth(ALICE_TOKEN)
    )

    reader_view = api.get(f"/api/v1/conversations/{conversation.id}", headers=auth(READER_TOKEN)).json()
    assert reader_view["unread"] is True
    assert reader_view["lastActivityAt"] is not None

    # The sender is never shown their own conversation as unread.
    alice_view = api.get(f"/api/v1/conversations/{conversation.id}", headers=auth(ALICE_TOKEN)).json()
    assert alice_view["unread"] is False


async def test_fetching_messages_marks_the_conversation_read(api) -> None:
    conversation = await make_conversation(api.factory)
    api.post(f"/api/v1/conversations/{conversation.id}/messages", json={"body": "hi"}, headers=auth(ALICE_TOKEN))

    assert api.get(f"/api/v1/conversations/{conversation.id}", headers=auth(READER_TOKEN)).json()["unread"] is True

    api.get(f"/api/v1/conversations/{conversation.id}/messages", headers=auth(READER_TOKEN))

    assert api.get(f"/api/v1/conversations/{conversation.id}", headers=auth(READER_TOKEN)).json()["unread"] is False


async def test_an_early_page_of_messages_does_not_mark_later_ones_read(api) -> None:
    """Fetching the oldest page must not silently mark newer, unfetched messages seen."""
    conversation = await make_conversation(api.factory)
    for index in range(3):
        api.post(
            f"/api/v1/conversations/{conversation.id}/messages",
            json={"body": f"message {index}"},
            headers=auth(ALICE_TOKEN),
        )

    first_page = api.get(
        f"/api/v1/conversations/{conversation.id}/messages",
        params={"limit": 1},
        headers=auth(READER_TOKEN),
    ).json()
    assert first_page["page"]["hasMore"] is True
    assert first_page["items"][0]["body"] == "message 0"

    # Only the oldest message was fetched, so the conversation must still read
    # unread: two newer messages have not been seen yet.
    assert (
        api.get(f"/api/v1/conversations/{conversation.id}", headers=auth(READER_TOKEN)).json()["unread"] is True
    )


async def test_an_empty_conversation_is_never_unread(api) -> None:
    conversation = await make_conversation(api.factory)
    assert api.get(f"/api/v1/conversations/{conversation.id}", headers=auth(READER_TOKEN)).json()["unread"] is False
    assert api.get(f"/api/v1/conversations/{conversation.id}", headers=auth(READER_TOKEN)).json()["lastActivityAt"] is None


# --------------------------------------------------------------------------
# Pagination — stable ordering
# --------------------------------------------------------------------------


async def test_the_conversation_list_cursor_walks_every_conversation_once(api) -> None:
    for index in range(6):
        await make_conversation(api.factory)

    seen: list[str] = []
    cursor = None
    for _ in range(10):
        params = {"limit": 2}
        if cursor:
            params["cursor"] = cursor
        body = api.get("/api/v1/conversations", headers=auth(ALICE_TOKEN), params=params).json()
        seen.extend(item["id"] for item in body["items"])
        cursor = body["page"]["nextCursor"]
        if not body["page"]["hasMore"]:
            break

    assert len(seen) == 6
    assert len(set(seen)) == 6


async def test_the_message_list_cursor_walks_every_message_once_oldest_first(api) -> None:
    conversation = await make_conversation(api.factory)
    for index in range(6):
        api.post(
            f"/api/v1/conversations/{conversation.id}/messages",
            json={"body": f"message {index}"},
            headers=auth(ALICE_TOKEN),
        )

    seen: list[str] = []
    cursor = None
    for _ in range(10):
        params = {"limit": 2}
        if cursor:
            params["cursor"] = cursor
        body = api.get(
            f"/api/v1/conversations/{conversation.id}/messages",
            headers=auth(ALICE_TOKEN),
            params=params,
        ).json()
        seen.extend(item["body"] for item in body["items"])
        cursor = body["page"]["nextCursor"]
        if not body["page"]["hasMore"]:
            break

    assert seen == [f"message {index}" for index in range(6)], "must read oldest first, in order"


async def test_a_conversation_cursor_from_a_different_project_is_rejected(api) -> None:
    await make_conversation(api.factory, project_id="p1")
    await make_conversation(api.factory, project_id="p2")
    first = api.get(
        "/api/v1/conversations", headers=auth(ADMIN_TOKEN), params={"projectId": "p1", "limit": 1}
    ).json()
    cursor = first["page"]["nextCursor"] or "x"
    response = api.get(
        "/api/v1/conversations", headers=auth(ADMIN_TOKEN), params={"projectId": "p2", "cursor": cursor}
    )
    assert response.status_code == 400


async def test_list_conversations_filters_by_project(api) -> None:
    p1 = await make_conversation(api.factory, project_id="p1")
    await make_conversation(api.factory, project_id="p2")
    body = api.get(
        "/api/v1/conversations", params={"projectId": "p1"}, headers=auth(ADMIN_TOKEN)
    ).json()
    assert [item["id"] for item in body["items"]] == [p1.id]
