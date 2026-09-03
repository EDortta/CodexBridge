"""REST reminders — issue #72.

The REST transport in front of #71's `gateway/app/services/google_calendar.py`.
Google is never touched here: `create_reminder`/`cancel_reminder`/
`list_reminders` are monkeypatched with fakes, the same way
`tests/integration/test_mcp_reminders.py` proves the MCP transport without a
network call — the real HTTP/JWT logic is `tests/unit/test_google_calendar.py`'s
job, and this file's job is the REST glue: scope enforcement for both `.read`
and `.write`, the `Idempotency-Key` replay this transport gets "for free" from
`gateway/app/api/idempotency.py` (unlike `/mcp`, which sits outside it), and
that a REST response carries the same logical fields #71's MCP tool output
does, field-for-field, for the same underlying event.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from gateway.app.api.routes import reminders as reminders_routes
from gateway.app.api.setup import install_api_conventions
from gateway.app.db.base import Base
from gateway.app.db.session import get_session
from gateway.app.services import google_calendar, store


WRITE_ONLY_TOKEN = "token-write-only"   # codexbridge.reminders.write only
READ_ONLY_TOKEN = "token-read-only"     # codexbridge.reminders.read only
BOTH_TOKEN = "token-both"               # both reminders scopes
NOTHING_TOKEN = "token-nothing"         # codexbridge.read only


@pytest.fixture
def users_file(tmp_path):
    path = tmp_path / "users.json"
    path.write_text(
        json.dumps(
            {
                "users": [
                    {
                        "user_id": "writer", "email": "writer@example.com", "password_hash": "x",
                        "roles": [], "allowed_projects": [],
                        "scopes": ["codexbridge.reminders.write"], "enabled": True,
                    },
                    {
                        "user_id": "reader", "email": "reader@example.com", "password_hash": "x",
                        "roles": [], "allowed_projects": [],
                        "scopes": ["codexbridge.reminders.read"], "enabled": True,
                    },
                    {
                        "user_id": "both", "email": "both@example.com", "password_hash": "x",
                        "roles": [], "allowed_projects": [],
                        "scopes": ["codexbridge.reminders.write", "codexbridge.reminders.read"], "enabled": True,
                    },
                    {
                        "user_id": "outsider", "email": "outsider@example.com", "password_hash": "x",
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
    # A configured calendar. Individual tests still monkeypatch the
    # `google_calendar` functions themselves, so no network call is ever made
    # regardless of these values -- they only need to be non-empty so the
    # route layer's own "is this configured" guard does not short-circuit
    # before reaching the (faked) service call.
    monkeypatch.setattr(settings, "google_calendar_credentials_file", "/does/not/matter.json")
    monkeypatch.setattr(settings, "google_calendar_id", "cal-1")

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    future = datetime.now(timezone.utc) + timedelta(hours=1)
    async with factory() as seed:
        for token, user_id, scopes in (
            (WRITE_ONLY_TOKEN, "writer", ["codexbridge.reminders.write"]),
            (READ_ONLY_TOKEN, "reader", ["codexbridge.reminders.read"]),
            (BOTH_TOKEN, "both", ["codexbridge.reminders.write", "codexbridge.reminders.read"]),
            (NOTHING_TOKEN, "outsider", ["codexbridge.read"]),
        ):
            await store.create_oauth_access_token(
                seed, token=token, client_id="c", user_id=user_id, scopes=scopes, expires_at=future
            )

    app = FastAPI(openapi_url=None, docs_url=None, redoc_url=None)
    install_api_conventions(app)
    app.include_router(reminders_routes.router)

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


FAKE_CREATE_RESULT = {
    "reminder_id": "cbfakeid123",
    "calendar_id": "cal-1",
    "summary": "Ligar para o contador",
    "scheduled_for": "2099-01-01T10:00:00-03:00",
    "timezone": "America/Sao_Paulo",
    "lead_minutes": 30,
    "created": True,
    "html_link": "https://calendar.example/e",
    "when_was_naive": False,
}


# --------------------------------------------------------------------------
# Authentication and scope enforcement
# --------------------------------------------------------------------------


def test_every_route_requires_a_token(api) -> None:
    assert api.get("/api/v1/reminders").status_code == 401
    assert api.post("/api/v1/reminders", json={"text": "x", "when": "2099-01-01T10:00:00-03:00"}).status_code == 401
    assert api.delete("/api/v1/reminders/cbabc").status_code == 401


def test_write_scope_alone_cannot_list(api) -> None:
    response = api.get("/api/v1/reminders", headers=auth(WRITE_ONLY_TOKEN))
    assert response.status_code == 403
    assert response.json()["code"] == "permission_denied"


def test_read_scope_alone_cannot_create_or_cancel(api, monkeypatch) -> None:
    async def must_not_run(**kwargs):
        raise AssertionError("the calendar service must not be called for a caller lacking the write scope")

    monkeypatch.setattr(google_calendar, "create_reminder", must_not_run)
    monkeypatch.setattr(google_calendar, "cancel_reminder", must_not_run)

    create = api.post(
        "/api/v1/reminders",
        json={"text": "x", "when": "2099-01-01T10:00:00-03:00"},
        headers=auth(READ_ONLY_TOKEN),
    )
    assert create.status_code == 403
    assert create.json()["code"] == "permission_denied"

    cancel = api.delete("/api/v1/reminders/cbabc", headers=auth(READ_ONLY_TOKEN))
    assert cancel.status_code == 403


def test_a_principal_with_neither_scope_is_refused_everywhere(api) -> None:
    assert api.get("/api/v1/reminders", headers=auth(NOTHING_TOKEN)).status_code == 403
    assert api.post(
        "/api/v1/reminders", json={"text": "x", "when": "2099-01-01T10:00:00-03:00"}, headers=auth(NOTHING_TOKEN)
    ).status_code == 403
    assert api.delete("/api/v1/reminders/cbabc", headers=auth(NOTHING_TOKEN)).status_code == 403


# --------------------------------------------------------------------------
# Create — round trip and field-for-field parity with the MCP tool output
# --------------------------------------------------------------------------


async def test_create_reminder_round_trip(api, monkeypatch) -> None:
    captured = {}

    async def fake_create_reminder(**kwargs):
        captured.update(kwargs)
        return dict(FAKE_CREATE_RESULT)

    monkeypatch.setattr(google_calendar, "create_reminder", fake_create_reminder)

    response = api.post(
        "/api/v1/reminders",
        json={
            "text": "Ligar para o contador",
            "when": "2099-01-01T10:00:00-03:00",
            "notes": "Falar do IR",
            "leadMinutes": 30,
        },
        headers=auth(WRITE_ONLY_TOKEN),
    )

    assert response.status_code == 201
    body = response.json()
    assert body == {
        "id": "cbfakeid123",
        "text": "Ligar para o contador",
        "when": "2099-01-01T10:00:00-03:00",
        "notes": "Falar do IR",
        "leadMinutes": 30,
        "calendarId": "cal-1",
        "timezone": "America/Sao_Paulo",
        "htmlLink": "https://calendar.example/e",
        "created": True,
    }
    assert response.headers["Cache-Control"] == "no-store"

    # Identity comes from the token, never from the body (design-standards.md
    # §4): the caller sent no user id at all.
    assert captured["user_id"] == "writer@example.com"
    assert captured["text"] == "Ligar para o contador"
    assert captured["when"] == "2099-01-01T10:00:00-03:00"
    assert captured["notes"] == "Falar do IR"
    assert captured["lead_minutes"] == 30


async def test_create_response_matches_the_mcp_tool_output_shape_field_for_field(api, monkeypatch) -> None:
    """The test plan's own words: "matches #71's MCP tool output shape

    field-for-field for the same logical request." Builds the exact dict
    `gateway/app/mcp/server.py`'s `create_reminder` handler would receive from
    the shared service for one logical reminder, feeds it through this
    transport's route, and asserts every field the MCP transport would report
    is present here too, under this contract's own (camelCased) name for it.
    """
    async def fake_create_reminder(**kwargs):
        return dict(FAKE_CREATE_RESULT)

    monkeypatch.setattr(google_calendar, "create_reminder", fake_create_reminder)

    response = api.post(
        "/api/v1/reminders",
        json={"text": "Ligar para o contador", "when": "2099-01-01T10:00:00-03:00"},
        headers=auth(WRITE_ONLY_TOKEN),
    )
    body = response.json()

    # The MCP transport hands `structuredContent` from google_calendar.py back
    # to ChatGPT verbatim (tests/integration/test_mcp_reminders.py). Every one
    # of those keys has a REST counterpart under this contract's own name.
    assert body["id"] == FAKE_CREATE_RESULT["reminder_id"]
    assert body["calendarId"] == FAKE_CREATE_RESULT["calendar_id"]
    assert body["text"] == FAKE_CREATE_RESULT["summary"]
    assert body["when"] == FAKE_CREATE_RESULT["scheduled_for"]
    assert body["timezone"] == FAKE_CREATE_RESULT["timezone"]
    assert body["leadMinutes"] == FAKE_CREATE_RESULT["lead_minutes"]
    assert body["created"] == FAKE_CREATE_RESULT["created"]
    assert body["htmlLink"] == FAKE_CREATE_RESULT["html_link"]


async def test_create_reminder_config_error_is_503_with_the_mcp_message_text(api, monkeypatch) -> None:
    """Same actionable message text as `/mcp` — the issue's own requirement."""
    message = "Reminders are not configured on this gateway: no target calendar."

    async def unconfigured(**kwargs):
        raise google_calendar.CalendarConfigError(message)

    monkeypatch.setattr(google_calendar, "create_reminder", unconfigured)

    response = api.post(
        "/api/v1/reminders",
        json={"text": "x", "when": "2099-01-01T10:00:00-03:00"},
        headers=auth(WRITE_ONLY_TOKEN),
    )
    assert response.status_code == 503
    body = response.json()
    assert body["code"] == "dependency_unavailable"
    assert body["message"] == message
    assert body["retryable"] is True


async def test_create_reminder_access_error_names_the_client_email(api, monkeypatch) -> None:
    message = (
        "Calendar 'cal-1' was not found, or it has not been shared with "
        "sa@example.iam.gserviceaccount.com. In Google Calendar, open Settings "
        "for that calendar, choose 'Share with specific people', and add that "
        "address with 'Make changes to events' (read-only access is not enough)."
    )

    async def refused(**kwargs):
        raise google_calendar.CalendarAccessError(message)

    monkeypatch.setattr(google_calendar, "create_reminder", refused)

    response = api.post(
        "/api/v1/reminders",
        json={"text": "x", "when": "2099-01-01T10:00:00-03:00"},
        headers=auth(WRITE_ONLY_TOKEN),
    )
    assert response.status_code == 409
    body = response.json()
    assert body["code"] == "conflict"
    assert body["message"] == message
    assert "sa@example.iam.gserviceaccount.com" in body["message"]


async def test_create_reminder_rejects_a_missing_required_field(api) -> None:
    response = api.post("/api/v1/reminders", json={"when": "2099-01-01T10:00:00-03:00"}, headers=auth(WRITE_ONLY_TOKEN))
    assert response.status_code == 422
    assert response.json()["code"] == "validation_failed"


# --------------------------------------------------------------------------
# Idempotency-Key replay (issue #72's own claim: "for free" from the standard
# middleware, unlike /mcp)
# --------------------------------------------------------------------------


async def test_idempotency_key_replay_calls_the_calendar_service_once(api, monkeypatch) -> None:
    calls = {"n": 0}

    async def fake_create_reminder(**kwargs):
        calls["n"] += 1
        return dict(FAKE_CREATE_RESULT)

    monkeypatch.setattr(google_calendar, "create_reminder", fake_create_reminder)

    payload = {"text": "x", "when": "2099-01-01T10:00:00-03:00"}
    headers = {**auth(WRITE_ONLY_TOKEN), "Idempotency-Key": "retry-1"}

    first = api.post("/api/v1/reminders", json=payload, headers=headers)
    second = api.post("/api/v1/reminders", json=payload, headers=headers)

    assert first.status_code == 201
    assert second.status_code == 201
    assert calls["n"] == 1, "a repeated Idempotency-Key must not call the calendar service twice"
    assert second.headers.get("Idempotent-Replay") == "true"
    assert first.json() == second.json()


async def test_idempotency_key_reused_for_a_different_body_is_refused(api, monkeypatch) -> None:
    async def fake_create_reminder(**kwargs):
        return dict(FAKE_CREATE_RESULT)

    monkeypatch.setattr(google_calendar, "create_reminder", fake_create_reminder)
    headers = {**auth(WRITE_ONLY_TOKEN), "Idempotency-Key": "reused-key"}

    first = api.post("/api/v1/reminders", json={"text": "first", "when": "2099-01-01T10:00:00-03:00"}, headers=headers)
    assert first.status_code == 201

    second = api.post("/api/v1/reminders", json={"text": "second", "when": "2099-01-01T10:00:00-03:00"}, headers=headers)
    assert second.status_code == 409
    assert second.json()["code"] == "conflict"


async def test_without_a_header_a_repeated_body_idempotency_key_still_dedupes_at_the_calendar(api, monkeypatch) -> None:
    """No `Idempotency-Key` header at all -- only the body's own `idempotencyKey`,

    the mechanism `google_calendar.create_reminder` folds into a deterministic
    event id. Two genuinely separate HTTP requests, same result: the second
    reports `created: false` rather than a stored HTTP replay.
    """
    calls = {"n": 0}

    async def fake_create_reminder(**kwargs):
        calls["n"] += 1
        result = dict(FAKE_CREATE_RESULT)
        result["created"] = calls["n"] == 1
        return result

    monkeypatch.setattr(google_calendar, "create_reminder", fake_create_reminder)
    payload = {"text": "x", "when": "2099-01-01T10:00:00-03:00", "idempotencyKey": "dup-1"}

    first = api.post("/api/v1/reminders", json=payload, headers=auth(WRITE_ONLY_TOKEN))
    second = api.post("/api/v1/reminders", json=payload, headers=auth(WRITE_ONLY_TOKEN))

    assert calls["n"] == 2, "no header means the service is called both times"
    assert first.json()["created"] is True
    assert second.json()["created"] is False
    assert first.json()["id"] == second.json()["id"]


# --------------------------------------------------------------------------
# List — scope, source/actor filtering, and pagination shape
# --------------------------------------------------------------------------


async def test_list_reminders_round_trip(api, monkeypatch) -> None:
    captured = {}

    async def fake_list_reminders(**kwargs):
        captured.update(kwargs)
        return {
            "items": [
                {
                    "reminder_id": "cbone",
                    "calendar_id": "cal-1",
                    "summary": "Ligar para o contador",
                    "notes": "Lembrete criado pelo CodexBridge a pedido de both@example.com (via ChatGPT).",
                    "scheduled_for": "2099-01-01T10:00:00-03:00",
                    "timezone": "America/Sao_Paulo",
                    "lead_minutes": 30,
                    "html_link": "https://calendar.example/e1",
                }
            ],
            "next_page_token": None,
        }

    monkeypatch.setattr(google_calendar, "list_reminders", fake_list_reminders)

    response = api.get("/api/v1/reminders", headers=auth(BOTH_TOKEN))
    assert response.status_code == 200
    body = response.json()
    assert body["items"] == [
        {
            "id": "cbone",
            "text": "Ligar para o contador",
            "when": "2099-01-01T10:00:00-03:00",
            "notes": "Lembrete criado pelo CodexBridge a pedido de both@example.com (via ChatGPT).",
            "leadMinutes": 30,
            "calendarId": "cal-1",
            "timezone": "America/Sao_Paulo",
            "htmlLink": "https://calendar.example/e1",
        }
    ]
    assert "created" not in body["items"][0]
    assert body["page"] == {"hasMore": False, "nextCursor": None}
    assert response.headers["Cache-Control"] == "no-store"

    # Never a way to browse the operator's whole calendar: scoped to this
    # actor's own reminders, server-side, by identity from the token.
    assert captured["requested_by"] == "both@example.com"


async def test_list_reminders_reports_a_next_cursor_when_google_has_more(api, monkeypatch) -> None:
    async def fake_list_reminders(**kwargs):
        return {"items": [], "next_page_token": "opaque-google-token"}

    monkeypatch.setattr(google_calendar, "list_reminders", fake_list_reminders)

    response = api.get("/api/v1/reminders", headers=auth(BOTH_TOKEN))
    assert response.json()["page"] == {"hasMore": True, "nextCursor": "opaque-google-token"}


async def test_list_reminders_forwards_cursor_and_limit(api, monkeypatch) -> None:
    captured = {}

    async def fake_list_reminders(**kwargs):
        captured.update(kwargs)
        return {"items": [], "next_page_token": None}

    monkeypatch.setattr(google_calendar, "list_reminders", fake_list_reminders)

    api.get("/api/v1/reminders?cursor=opaque-google-token&limit=10", headers=auth(BOTH_TOKEN))
    assert captured["page_token"] == "opaque-google-token"
    assert captured["limit"] == 10


async def test_list_reminders_config_error_is_503(api, monkeypatch) -> None:
    async def unconfigured(**kwargs):
        raise google_calendar.CalendarConfigError("Reminders are not configured on this gateway: no target calendar.")

    monkeypatch.setattr(google_calendar, "list_reminders", unconfigured)

    response = api.get("/api/v1/reminders", headers=auth(READ_ONLY_TOKEN))
    assert response.status_code == 503
    assert response.json()["code"] == "dependency_unavailable"


# --------------------------------------------------------------------------
# Cancel
# --------------------------------------------------------------------------


async def test_cancel_reminder_round_trip(api, monkeypatch) -> None:
    captured = {}

    async def fake_cancel_reminder(**kwargs):
        captured.update(kwargs)
        return {"reminder_id": kwargs["reminder_id"], "cancelled": True}

    monkeypatch.setattr(google_calendar, "cancel_reminder", fake_cancel_reminder)

    response = api.delete("/api/v1/reminders/cbabc", headers=auth(WRITE_ONLY_TOKEN))
    assert response.status_code == 200
    assert response.json() == {"id": "cbabc", "cancelled": True}
    assert captured["reminder_id"] == "cbabc"


async def test_cancel_reminder_idempotency_key_replay(api, monkeypatch) -> None:
    calls = {"n": 0}

    async def fake_cancel_reminder(**kwargs):
        calls["n"] += 1
        return {"reminder_id": kwargs["reminder_id"], "cancelled": True}

    monkeypatch.setattr(google_calendar, "cancel_reminder", fake_cancel_reminder)
    headers = {**auth(WRITE_ONLY_TOKEN), "Idempotency-Key": "cancel-retry-1"}

    first = api.delete("/api/v1/reminders/cbabc", headers=headers)
    second = api.delete("/api/v1/reminders/cbabc", headers=headers)

    assert first.status_code == 200 and second.status_code == 200
    assert calls["n"] == 1
    assert second.headers.get("Idempotent-Replay") == "true"


async def test_cancel_reminder_config_error_is_503_with_the_mcp_message_text(api, monkeypatch) -> None:
    message = "Reminders are not configured on this gateway: no target calendar."

    async def unconfigured(**kwargs):
        raise google_calendar.CalendarConfigError(message)

    monkeypatch.setattr(google_calendar, "cancel_reminder", unconfigured)

    response = api.delete("/api/v1/reminders/cbabc", headers=auth(WRITE_ONLY_TOKEN))
    assert response.status_code == 503
    assert response.json()["message"] == message
