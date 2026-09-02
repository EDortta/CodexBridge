"""`gateway.app.services.notify` -- the task-finished completion email.

WK-20260830-chatgpt-entry-provider-and-delivery, issue #70. `aiosmtplib.send`
is monkeypatched everywhere here; nothing in this file makes a network call.
An in-memory SQLite session stands in for the gateway's real database, the
same pattern `tests/integration/test_agent_ack_handling.py` already uses.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from gateway.app.core.config import Settings
from gateway.app.db.base import Base
from gateway.app.models.entities import AuditEventModel, ExecutorModel, ProjectModel, TaskModel
from gateway.app.services import notify


@pytest.fixture
async def session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with session_factory() as db_session:
        db_session.add(ExecutorModel(id="E1", display_name="E1"))
        db_session.add(ProjectModel(id="p1", name="Projeto Um", path="/srv/p1"))
        await db_session.commit()
        yield db_session
    await engine.dispose()


def _make_task(**overrides) -> TaskModel:
    now = datetime.now(timezone.utc)
    defaults = dict(
        id="task-1",
        executor_id="E1",
        project_id="p1",
        instruction="do it",
        mode="implement",
        state="completed",
        priority="normal",
        run_when_available=False,
        expires_at=now + timedelta(hours=1),
        timeout_seconds=600,
        created_at=now,
        correlation_id="corr-1",
        started_at=now - timedelta(minutes=4, seconds=32),
        completed_at=now,
        engine="claude",
        issue_ref="docs:57",
    )
    defaults.update(overrides)
    return TaskModel(**defaults)


def _settings(**overrides) -> Settings:
    return Settings(**overrides)


async def _notification_events(session, task_id: str) -> list[dict]:
    rows = (
        await session.execute(
            select(AuditEventModel).where(
                AuditEventModel.entity_id == task_id,
                AuditEventModel.event_type == "task.notification_failed",
            )
        )
    ).scalars().all()
    return [json.loads(row.payload_json) for row in rows]


@pytest.mark.asyncio
async def test_no_config_is_a_silent_no_op(session, monkeypatch) -> None:
    sent = []

    async def _fake_send(*args, **kwargs):
        sent.append((args, kwargs))

    monkeypatch.setattr("aiosmtplib.send", _fake_send)

    task = _make_task()
    session.add(task)
    await session.commit()

    await notify.notify_task_finished(session, task, _settings())

    assert sent == []
    assert await _notification_events(session, task.id) == []


@pytest.mark.asyncio
async def test_a_non_terminal_state_is_a_no_op(session, tmp_path, monkeypatch) -> None:
    config_path = tmp_path / "yahoo.conf"
    config_path.write_text("account=a@example.com\napp_password=x\nsmtp_host=smtp.example.com\nsmtp_port=465\n")
    config_path.chmod(0o600)

    sent = []
    monkeypatch.setattr("aiosmtplib.send", lambda *a, **k: sent.append((a, k)))

    task = _make_task(state="running", completed_at=None)
    session.add(task)
    await session.commit()

    await notify.notify_task_finished(
        session, task, _settings(notification_email_config_file=str(config_path), notification_to="to@example.com")
    )

    assert sent == []


@pytest.mark.asyncio
async def test_a_world_readable_config_file_is_refused(session, tmp_path, monkeypatch) -> None:
    config_path = tmp_path / "yahoo.conf"
    config_path.write_text("account=a@example.com\napp_password=x\nsmtp_host=smtp.example.com\nsmtp_port=465\n")
    config_path.chmod(0o644)  # world-readable -- must be refused

    sent = []

    async def _fake_send(*args, **kwargs):
        sent.append((args, kwargs))

    monkeypatch.setattr("aiosmtplib.send", _fake_send)

    task = _make_task()
    session.add(task)
    await session.commit()

    await notify.notify_task_finished(
        session, task, _settings(notification_email_config_file=str(config_path), notification_to="to@example.com")
    )

    assert sent == []  # never attempted
    events = await _notification_events(session, task.id)
    assert len(events) == 1
    assert events[0] == {"exception_type": "NotifyConfigError"}


@pytest.mark.asyncio
async def test_a_missing_config_file_is_refused(session, tmp_path, monkeypatch) -> None:
    sent = []
    monkeypatch.setattr("aiosmtplib.send", lambda *a, **k: sent.append((a, k)))

    task = _make_task()
    session.add(task)
    await session.commit()

    await notify.notify_task_finished(
        session,
        task,
        _settings(
            notification_email_config_file=str(tmp_path / "does-not-exist.conf"),
            notification_to="to@example.com",
        ),
    )

    assert sent == []
    events = await _notification_events(session, task.id)
    assert events == [{"exception_type": "NotifyConfigError"}]


@pytest.mark.asyncio
async def test_a_sender_that_raises_never_fails_the_task_and_records_only_the_exception_type(
    session, tmp_path, monkeypatch
) -> None:
    config_path = tmp_path / "yahoo.conf"
    config_path.write_text(
        "account = a@example.com\napp_password = a-secret-app-password\nsmtp_host = smtp.example.com\nsmtp_port = 465\n"
    )
    config_path.chmod(0o600)

    async def _raising_send(message, **kwargs):
        raise RuntimeError(f"SMTP 535 authentication failed for a@example.com with a-secret-app-password")

    monkeypatch.setattr("aiosmtplib.send", _raising_send)

    task = _make_task(state="failed", last_error="boom")
    session.add(task)
    await session.commit()

    await notify.notify_task_finished(
        session, task, _settings(notification_email_config_file=str(config_path), notification_to="to@example.com")
    )

    # The task's own state is untouched by the notification failure.
    refreshed = await session.get(TaskModel, task.id)
    assert refreshed.state == "failed"

    events = await _notification_events(session, task.id)
    assert events == [{"exception_type": "RuntimeError"}]
    # Never the exception message -- it can echo the server banner or the
    # credential itself (issue #70's explicit requirement).
    all_payloads = json.dumps(events)
    assert "a-secret-app-password" not in all_payloads
    assert "authentication failed" not in all_payloads


@pytest.mark.asyncio
async def test_a_config_file_with_spaces_around_equals_parses_correctly(session, tmp_path, monkeypatch) -> None:
    """This ecosystem's own credential files are inconsistent: most are
    `key=value`, at least one (`dortta-yahoo.conf`) is `key = value`. Both
    must parse to the same credential, with no leading/trailing whitespace
    left on either side."""
    config_path = tmp_path / "yahoo.conf"
    config_path.write_text(
        "account = a@example.com\napp_password = secret123\nsmtp_host = smtp.example.com\nsmtp_port = 465\n"
    )
    config_path.chmod(0o600)

    sent = {}

    async def _fake_send(message, *, hostname, port, username, password, **kwargs):
        sent["hostname"] = hostname
        sent["port"] = port
        sent["username"] = username
        sent["password"] = password

    monkeypatch.setattr("aiosmtplib.send", _fake_send)

    task = _make_task()
    session.add(task)
    await session.commit()

    await notify.notify_task_finished(
        session, task, _settings(notification_email_config_file=str(config_path), notification_to="to@example.com")
    )

    assert sent == {
        "hostname": "smtp.example.com",
        "port": 465,
        "username": "a@example.com",
        "password": "secret123",
    }


@pytest.mark.asyncio
async def test_task_last_error_is_never_included_in_the_email(session, tmp_path, monkeypatch) -> None:
    """Issue #70 enumerates exactly what the body may carry -- task id,
    project, engine, final state, issue reference, branch, commit, push
    outcome, delivery refusal reason, duration -- and explicitly forbids
    "log lines" and "repository file content". `task.last_error` is neither
    enumerated nor a value `redact()` can make safe in general (it only
    strips known secret/path *shapes*, not arbitrary log or diff content),
    so it must never reach the composed body at all, regardless of what it
    contains.
    """
    config_path = tmp_path / "yahoo.conf"
    config_path.write_text("account=a@example.com\napp_password=x\nsmtp_host=smtp.example.com\nsmtp_port=465\n")
    config_path.chmod(0o600)

    captured = {}

    async def _fake_send(message, **kwargs):
        captured["body"] = message.get_body(preferencelist=("html",)).get_content()

    monkeypatch.setattr("aiosmtplib.send", _fake_send)

    task = _make_task(
        state="failed",
        last_error=(
            "diff --git a/secret.txt b/secret.txt\n+++ b/secret.txt\n@@ -1 +1 @@\n-old\n+new\n"
            "traceback at /home/esteban/Sync/Projects/AI/CodexBridge/agent/service.py line 42"
        ),
    )
    session.add(task)
    await session.commit()

    await notify.notify_task_finished(
        session, task, _settings(notification_email_config_file=str(config_path), notification_to="to@example.com")
    )

    body = captured["body"]
    assert "diff --git" not in body
    assert "/home/esteban" not in body
    assert "traceback" not in body


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "delivery_reason",
    [
        "Bearer sk-abcdefghijklmnopqrstuvwxyz012345",
        "push failed: password=hunter2secret in remote url",
        "refused at /home/esteban/Sync/Projects/AI/CodexBridge/.git",
    ],
)
async def test_a_delivery_refusal_reason_is_redacted(session, tmp_path, monkeypatch, delivery_reason) -> None:
    """`reason` is the one delivery field allowed to carry free text (issue
    #70's own enumerated field list names "refusal reason if any"), so it is
    the one field this module runs through `redact()` -- the same helper
    already used for the identical class of value in `get_session_detail`."""
    config_path = tmp_path / "yahoo.conf"
    config_path.write_text("account=a@example.com\napp_password=x\nsmtp_host=smtp.example.com\nsmtp_port=465\n")
    config_path.chmod(0o600)

    captured = {}

    async def _fake_send(message, **kwargs):
        captured["body"] = message.get_body(preferencelist=("html",)).get_content()

    monkeypatch.setattr("aiosmtplib.send", _fake_send)

    delivery_json = json.dumps({"branch": "feature/x", "pushed": False, "reason": delivery_reason})
    task = _make_task(state="failed", delivery_result_json=delivery_json)
    session.add(task)
    await session.commit()

    await notify.notify_task_finished(
        session, task, _settings(notification_email_config_file=str(config_path), notification_to="to@example.com")
    )

    body = captured["body"]
    assert "sk-abcdefghijklmnopqrstuvwxyz012345" not in body
    assert "hunter2secret" not in body
    assert "/home/esteban" not in body
    assert "@@ -1 +1 @@" not in body


@pytest.mark.asyncio
async def test_a_successful_send_writes_no_audit_event(session, tmp_path, monkeypatch) -> None:
    config_path = tmp_path / "yahoo.conf"
    config_path.write_text("account=a@example.com\napp_password=x\nsmtp_host=smtp.example.com\nsmtp_port=465\n")
    config_path.chmod(0o600)

    async def _fake_send(message, **kwargs):
        return None

    monkeypatch.setattr("aiosmtplib.send", _fake_send)

    task = _make_task()
    session.add(task)
    await session.commit()

    await notify.notify_task_finished(
        session, task, _settings(notification_email_config_file=str(config_path), notification_to="to@example.com")
    )

    events = (
        await session.execute(select(AuditEventModel).where(AuditEventModel.entity_id == task.id))
    ).scalars().all()
    assert events == []
