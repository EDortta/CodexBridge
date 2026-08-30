"""The `create_reminder`/`cancel_reminder` MCP tools, at the `handle_mcp_call` layer.

WK-20260830-chatgpt-entry-provider-and-delivery, issue #71. Google is never
touched here -- `gateway.app.services.google_calendar.create_reminder`/
`cancel_reminder` are monkeypatched with fakes; the real HTTP/JWT logic is
`tests/unit/test_google_calendar.py`'s job. This file's job is the MCP glue:
scope enforcement, error mapping, and -- critically -- proving reminders
being unconfigured never breaks the rest of the gateway.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from gateway.app.core.users import AuthenticatedPrincipal
from gateway.app.db.base import Base
from gateway.app.mcp.server import handle_mcp_call
from gateway.app.services import google_calendar, store
from shared.protocol import ExecutorRegistration, ProjectRegistration, SubmitTaskRequest, TaskMode, TaskPriority


class DummyHub:
    def is_connected(self, executor_id: str) -> bool:
        return False

    async def dispatch_next(self, executor_id: str):
        return None

    async def send(self, executor_id: str, envelope) -> None:
        pass


WITH_REMINDERS = AuthenticatedPrincipal(
    user_id="esteban", email="esteban@example.com",
    allowed_projects=["p1"],
    scopes=["codexbridge.read", "codexbridge.task.submit", "codexbridge.reminders.write"],
)

WITHOUT_REMINDERS = AuthenticatedPrincipal(
    user_id="alice", email="alice@example.com",
    allowed_projects=["p1"],
    scopes=["codexbridge.read", "codexbridge.task.submit"],
)


@pytest.fixture
async def db_session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with session_factory() as session:
        await store.upsert_registry(
            session,
            executors=[ExecutorRegistration(executor_id="T610", display_name="T610", machine_token="t", allowed_projects=["p1"], max_concurrent_tasks=1)],
            projects=[ProjectRegistration(project_id="p1", name="Projeto 1", path="/srv/p1", max_timeout_seconds=600)],
        )
        yield session
    await engine.dispose()


async def _call(session, hub, principal, name: str, arguments: dict) -> dict:
    return await handle_mcp_call(
        {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": name, "arguments": arguments}},
        session, hub, principal,
    )


@pytest.mark.asyncio
async def test_tools_list_includes_both_reminder_tools(db_session):
    response = await handle_mcp_call({"jsonrpc": "2.0", "id": 1, "method": "tools/list"}, db_session, DummyHub(), WITH_REMINDERS)
    names = [tool["name"] for tool in response["result"]["tools"]]
    assert "create_reminder" in names
    assert "cancel_reminder" in names


@pytest.mark.asyncio
async def test_missing_scope_is_refused(db_session):
    with pytest.raises(Exception) as raised:
        await _call(db_session, DummyHub(), WITHOUT_REMINDERS, "create_reminder", {"text": "x", "when": "2099-01-01T10:00:00-03:00"})
    assert "missing_scope:codexbridge.reminders.write" in str(raised.value)


@pytest.mark.asyncio
async def test_happy_path_returns_the_fake_calendars_structured_content(db_session, monkeypatch):
    fake_result = {
        "reminder_id": "cbfakeid123", "calendar_id": "cal-1", "summary": "Ligar para o contador",
        "scheduled_for": "2099-01-01T10:00:00-03:00", "timezone": "America/Sao_Paulo",
        "lead_minutes": 0, "created": True, "html_link": "https://calendar.example/e",
    }
    captured = {}

    async def fake_create_reminder(**kwargs):
        captured.update(kwargs)
        return fake_result

    monkeypatch.setattr(google_calendar, "create_reminder", fake_create_reminder)

    response = await _call(db_session, DummyHub(), WITH_REMINDERS, "create_reminder", {
        "text": "Ligar para o contador", "when": "2099-01-01T10:00:00-03:00",
    })

    structured = response["result"]["structuredContent"]
    assert structured == fake_result
    assert captured["user_id"] == "esteban@example.com"
    assert captured["text"] == "Ligar para o contador"


@pytest.mark.asyncio
async def test_second_call_with_the_same_idempotency_key_reports_created_false(db_session, monkeypatch):
    calls = {"n": 0}

    async def fake_create_reminder(**kwargs):
        calls["n"] += 1
        return {"reminder_id": "cbsame", "created": calls["n"] == 1, "scheduled_for": kwargs["when"], "timezone": "America/Sao_Paulo", "lead_minutes": 0, "calendar_id": "cal-1", "summary": kwargs["text"], "html_link": None}

    monkeypatch.setattr(google_calendar, "create_reminder", fake_create_reminder)

    first = await _call(db_session, DummyHub(), WITH_REMINDERS, "create_reminder", {
        "text": "x", "when": "2099-01-01T10:00:00-03:00", "idempotency_key": "dup-1",
    })
    second = await _call(db_session, DummyHub(), WITH_REMINDERS, "create_reminder", {
        "text": "x", "when": "2099-01-01T10:00:00-03:00", "idempotency_key": "dup-1",
    })

    assert first["result"]["structuredContent"]["created"] is True
    assert second["result"]["structuredContent"]["created"] is False
    assert first["result"]["structuredContent"]["reminder_id"] == second["result"]["structuredContent"]["reminder_id"]


@pytest.mark.asyncio
async def test_calendar_error_is_reported_as_a_client_error_not_a_500(db_session, monkeypatch):
    async def failing_create_reminder(**kwargs):
        raise google_calendar.CalendarAccessError(
            "Calendar 'cal-1' was not found, or it has not been shared with sa@example.iam.gserviceaccount.com."
        )

    monkeypatch.setattr(google_calendar, "create_reminder", failing_create_reminder)

    with pytest.raises(Exception) as raised:
        await _call(db_session, DummyHub(), WITH_REMINDERS, "create_reminder", {"text": "x", "when": "2099-01-01T10:00:00-03:00"})
    assert "has not been shared with" in str(raised.value)


@pytest.mark.asyncio
async def test_cancel_reminder_happy_path(db_session, monkeypatch):
    async def fake_cancel_reminder(**kwargs):
        return {"reminder_id": kwargs["reminder_id"], "cancelled": True}

    monkeypatch.setattr(google_calendar, "cancel_reminder", fake_cancel_reminder)

    response = await _call(db_session, DummyHub(), WITH_REMINDERS, "cancel_reminder", {"reminder_id": "cbabc"})
    assert response["result"]["structuredContent"] == {"reminder_id": "cbabc", "cancelled": True}


@pytest.mark.asyncio
async def test_an_unconfigured_gateway_still_serves_submit_codex_task_normally(db_session, monkeypatch):
    """The most important test in this file: reminders being unconfigured,

    or Google being unreachable, must never make the CORE product (task
    dispatch) stop working. This is what makes reminders a genuinely
    optional capability rather than a new single point of failure.
    """
    async def unconfigured_create_reminder(**kwargs):
        raise google_calendar.CalendarConfigError(
            "Reminders are not configured on this gateway: no target calendar."
        )

    monkeypatch.setattr(google_calendar, "create_reminder", unconfigured_create_reminder)

    with pytest.raises(Exception) as raised:
        await _call(db_session, DummyHub(), WITH_REMINDERS, "create_reminder", {"text": "x", "when": "2099-01-01T10:00:00-03:00"})
    assert "not configured" in str(raised.value)

    # submit_codex_task, unrelated to reminders, must be completely unaffected.
    response = await _call(db_session, DummyHub(), WITH_REMINDERS, "submit_codex_task", {
        "executor_id": "T610", "project_id": "p1", "instruction": "analisar",
        "mode": "analyze", "timeout_seconds": 60, "priority": "normal",
        "run_when_available": True, "expires_at": (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat(),
    })
    assert response["result"]["structuredContent"]["task_id"]
