"""`gateway.app.services.google_calendar`, without ever touching Google.

WK-20260830-chatgpt-entry-provider-and-delivery, issue #71. An injected
`httpx.MockTransport` stands in for the real API, and a fake `signer`
callable stands in for `openssl` (except one dedicated real-openssl test,
skipped when the binary is absent). Nothing here makes a network call.
"""

from __future__ import annotations

import base64
import json
import shutil
import subprocess
from datetime import datetime, timedelta, timezone

import httpx
import pytest

from gateway.app.services import google_calendar as gc


@pytest.fixture(autouse=True)
def _clear_token_cache():
    """The access-token cache is module-level and keyed by `client_email`.

    Every test here reuses the same `FAKE_SERVICE_ACCOUNT`, so without this a
    token minted by one test would silently serve a LATER test that expects
    to see its own mocked token endpoint actually called -- turning a
    correctness bug in the code into a false pass, or an error-mapping test
    into a false failure (a cached token skips the very call whose response
    the test is trying to exercise).
    """
    gc._TOKEN_CACHE.clear()
    yield
    gc._TOKEN_CACHE.clear()


FAKE_SERVICE_ACCOUNT = {
    "type": "service_account",
    "project_id": "codexbridge-test",
    "client_email": "codexbridge-test@codexbridge-test.iam.gserviceaccount.com",
    "private_key": "-----BEGIN PRIVATE KEY-----\nFAKE-NEVER-A-REAL-KEY\n-----END PRIVATE KEY-----\n",
    "token_uri": "https://oauth2.googleapis.com/token",
}


async def _fake_signer(signing_input: bytes, private_key_pem: str) -> bytes:
    assert private_key_pem == FAKE_SERVICE_ACCOUNT["private_key"]
    return b"fake-signature-bytes"


def _write_service_account(tmp_path, data: dict | None = None) -> str:
    path = tmp_path / "sa.json"
    path.write_text(json.dumps(data if data is not None else FAKE_SERVICE_ACCOUNT), encoding="utf-8")
    return str(path)


def _decode_jwt_parts(assertion: str) -> tuple[dict, dict]:
    header_b64, claims_b64, _signature = assertion.split(".")
    def _decode(segment: str) -> dict:
        padded = segment + "=" * (-len(segment) % 4)
        return json.loads(base64.urlsafe_b64decode(padded))
    return _decode(header_b64), _decode(claims_b64)


# --------------------------------------------------------------------------
# JWT assembly
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_jwt_assembly_carries_the_right_claims(tmp_path):
    captured_assertion = {}

    def handler(request: httpx.Request) -> httpx.Response:
        body = request.read().decode("utf-8")
        params = dict(pair.split("=", 1) for pair in body.split("&"))
        import urllib.parse

        captured_assertion["assertion"] = urllib.parse.unquote(params["assertion"])
        return httpx.Response(200, json={"access_token": "tok-1", "expires_in": 3600})

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        token = await gc._access_token(FAKE_SERVICE_ACCOUNT, client=client, signer=_fake_signer)

    assert token == "tok-1"
    header, claims = _decode_jwt_parts(captured_assertion["assertion"])
    assert header == {"alg": "RS256", "typ": "JWT"}
    assert claims["iss"] == FAKE_SERVICE_ACCOUNT["client_email"]
    assert claims["scope"] == gc.CALENDAR_SCOPE
    assert claims["aud"] == FAKE_SERVICE_ACCOUNT["token_uri"]
    assert claims["exp"] - claims["iat"] == 3600


@pytest.mark.asyncio
async def test_access_token_is_cached_across_calls(tmp_path):
    call_count = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        call_count["n"] += 1
        return httpx.Response(200, json={"access_token": f"tok-{call_count['n']}", "expires_in": 3600})

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        first = await gc._access_token(FAKE_SERVICE_ACCOUNT, client=client, signer=_fake_signer)
        second = await gc._access_token(FAKE_SERVICE_ACCOUNT, client=client, signer=_fake_signer)

    assert first == second == "tok-1"
    assert call_count["n"] == 1


# --------------------------------------------------------------------------
# Event-id derivation
# --------------------------------------------------------------------------


def test_event_id_is_deterministic_for_the_same_seed():
    a = gc._event_id("esteban", "key-1", "2026-09-04T15:00:00-03:00", "text")
    b = gc._event_id("esteban", "key-1", "2026-09-04T15:00:00-03:00", "text")
    assert a == b


def test_event_id_differs_for_a_different_user():
    a = gc._event_id("esteban", "key-1", "2026-09-04T15:00:00-03:00", "text")
    b = gc._event_id("someone-else", "key-1", "2026-09-04T15:00:00-03:00", "text")
    assert a != b


def test_event_id_without_a_key_normalizes_text_case_and_whitespace():
    a = gc._event_id("esteban", None, "2026-09-04T15:00:00-03:00", "Ligar Para O Contador  ")
    b = gc._event_id("esteban", None, "2026-09-04T15:00:00-03:00", "ligar para o contador")
    assert a == b


def test_event_id_alphabet_is_base32hex_lowercase():
    import re

    for i in range(10):
        event_id = gc._event_id(f"user-{i}", None, "2026-09-04T15:00:00-03:00", f"text {i}")
        assert re.fullmatch(r"[0-9a-v]+", event_id), event_id
        assert 5 <= len(event_id) <= 1024


# --------------------------------------------------------------------------
# Datetime validation
# --------------------------------------------------------------------------


def test_naive_input_is_rejected_not_defaulted():
    """Issue #71's own Requirements: ChatGPT already resolved the operator's

    timezone and the current instant before calling this tool/endpoint, so a
    naive `when` means something went wrong upstream. Guessing a timezone
    would produce a reminder that silently fires at the wrong hour -- this
    replaces `test_naive_input_gets_the_default_timezone`, which pinned that
    wrong (opposite) behaviour. See this delivery's commit message for why
    the old test was removed rather than kept alongside the new one.
    """
    with pytest.raises(gc.NaiveDatetimeError) as raised:
        gc.parse_when("2026-09-04T15:00:00")
    # Typed AND operator-legible: names what was wrong and the expected shape.
    assert raised.value.when == "2026-09-04T15:00:00"
    assert "no UTC offset" in str(raised.value)
    assert "2026-09-04T15:00:00-03:00" in str(raised.value)  # the expected shape
    # A subclass of CalendarAccessError, so both transports' existing
    # `except (CalendarConfigError, CalendarAccessError)` clauses already
    # catch it -- no per-transport special-casing needed.
    assert isinstance(raised.value, gc.CalendarAccessError)


def test_offset_aware_input_keeps_its_own_offset():
    when_dt = gc.parse_when("2026-09-04T15:00:00-03:00")
    assert when_dt.utcoffset() == timedelta(hours=-3)


def test_trailing_z_suffix_parses():
    when_dt = gc.parse_when("2026-09-04T18:00:00Z")
    assert when_dt.utcoffset() == timedelta(0)


def test_malformed_datetime_is_a_calendar_access_error():
    with pytest.raises(gc.CalendarAccessError, match="not a valid ISO 8601"):
        gc.parse_when("not-a-date")


# --------------------------------------------------------------------------
# create_reminder: validation before any network call
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_unconfigured_gateway_refuses_before_touching_the_network(tmp_path):
    config = gc.CalendarConfig(credentials_file="", calendar_id="")

    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("must not make a network call when unconfigured")

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        with pytest.raises(gc.CalendarConfigError, match="not configured"):
            await gc.create_reminder(
                config=config, client=client, signer=_fake_signer,
                user_id="esteban", text="lembrete", when="2099-01-01T10:00:00-03:00",
            )


@pytest.mark.asyncio
async def test_a_time_in_the_past_is_refused(tmp_path):
    config = gc.CalendarConfig(credentials_file=_write_service_account(tmp_path), calendar_id="cal-1")
    transport = httpx.MockTransport(lambda r: (_ for _ in ()).throw(AssertionError("no network call expected")))
    async with httpx.AsyncClient(transport=transport) as client:
        with pytest.raises(gc.CalendarAccessError, match="not far enough in the future"):
            await gc.create_reminder(
                config=config, client=client, signer=_fake_signer,
                user_id="esteban", text="lembrete",
                when=(datetime.now(timezone.utc) - timedelta(hours=1)).isoformat(),
            )


@pytest.mark.asyncio
async def test_create_reminder_refuses_a_naive_when_before_touching_the_network(tmp_path):
    """The end-to-end path, not just `parse_when` in isolation: a naive

    `when` reaching `create_reminder` (as it would from either transport)
    is rejected before minting a token or calling Google.
    """
    config = gc.CalendarConfig(credentials_file=_write_service_account(tmp_path), calendar_id="cal-1")
    transport = httpx.MockTransport(lambda r: (_ for _ in ()).throw(AssertionError("no network call expected")))
    async with httpx.AsyncClient(transport=transport) as client:
        with pytest.raises(gc.NaiveDatetimeError, match="no UTC offset"):
            await gc.create_reminder(
                config=config, client=client, signer=_fake_signer,
                user_id="esteban", text="lembrete", when="2099-01-01T10:00:00",
            )


@pytest.mark.asyncio
async def test_more_than_two_years_out_is_refused(tmp_path):
    config = gc.CalendarConfig(credentials_file=_write_service_account(tmp_path), calendar_id="cal-1")
    transport = httpx.MockTransport(lambda r: (_ for _ in ()).throw(AssertionError("no network call expected")))
    async with httpx.AsyncClient(transport=transport) as client:
        with pytest.raises(gc.CalendarAccessError, match="more than 2 years"):
            await gc.create_reminder(
                config=config, client=client, signer=_fake_signer,
                user_id="esteban", text="lembrete",
                when=(datetime.now(timezone.utc) + timedelta(days=800)).isoformat(),
            )


# --------------------------------------------------------------------------
# create_reminder: the body sent to Google, and the never-attendees rule
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_the_event_body_matches_the_documented_shape_and_never_has_attendees(tmp_path):
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/token"):
            return httpx.Response(200, json={"access_token": "tok", "expires_in": 3600})
        captured["body"] = json.loads(request.read())
        return httpx.Response(200, json={**captured["body"], "htmlLink": "https://calendar.example/e"})

    config = gc.CalendarConfig(credentials_file=_write_service_account(tmp_path), calendar_id="cal-1")
    transport = httpx.MockTransport(handler)
    when = (datetime.now(timezone.utc) + timedelta(days=1)).replace(microsecond=0).isoformat()
    async with httpx.AsyncClient(transport=transport) as client:
        result = await gc.create_reminder(
            config=config, client=client, signer=_fake_signer,
            user_id="esteban", text="Ligar para o contador", when=when, lead_minutes=0,
            idempotency_key="smoke-1",
        )

    body = captured["body"]
    assert "attendees" not in body
    assert body["transparency"] == "transparent"
    assert body["reminders"] == {"useDefault": False, "overrides": [{"method": "popup", "minutes": 0}]}
    private = body["extendedProperties"]["private"]
    assert private["source"] == "codexbridge"
    assert private["requested_by"] == "esteban"
    # From day one (issue #71): what makes #72's list_reminders able to
    # filter and correlate without retroactively tagging events created
    # before these fields existed.
    assert private["created_via"] == "mcp"  # the default -- no transport named itself
    assert private["idempotency_key"] == "smoke-1"
    assert body["start"]["timeZone"] == gc.DEFAULT_TIMEZONE
    assert result["created"] is True
    assert result["reminder_id"] == body["id"]


@pytest.mark.asyncio
async def test_created_via_is_recorded_per_transport(tmp_path):
    """The REST route passes `created_via="rest"` explicitly

    (`gateway/app/api/routes/reminders.py`); `/mcp` never names one (that
    call site is out of this delivery's scope), so it gets the default.
    """
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/token"):
            return httpx.Response(200, json={"access_token": "tok", "expires_in": 3600})
        captured["body"] = json.loads(request.read())
        return httpx.Response(200, json=captured["body"])

    config = gc.CalendarConfig(credentials_file=_write_service_account(tmp_path), calendar_id="cal-1")
    transport = httpx.MockTransport(handler)
    when = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()
    async with httpx.AsyncClient(transport=transport) as client:
        await gc.create_reminder(
            config=config, client=client, signer=_fake_signer,
            user_id="esteban", text="lembrete", when=when, created_via="rest",
        )

    assert captured["body"]["extendedProperties"]["private"]["created_via"] == "rest"
    # No idempotency_key was passed -- still a string, never a JSON null,
    # because Google's extendedProperties.private requires string values.
    assert captured["body"]["extendedProperties"]["private"]["idempotency_key"] == ""


@pytest.mark.asyncio
async def test_a_lead_time_that_would_already_have_passed_is_clamped_to_zero(tmp_path):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/token"):
            return httpx.Response(200, json={"access_token": "tok", "expires_in": 3600})
        body = json.loads(request.read())
        return httpx.Response(200, json={**body, "htmlLink": None})

    config = gc.CalendarConfig(credentials_file=_write_service_account(tmp_path), calendar_id="cal-1")
    transport = httpx.MockTransport(handler)
    # 40 seconds out, 60-minute lead requested -- the lead would already be
    # in the past, so it must clamp to 0 rather than send a negative offset.
    when = (datetime.now(timezone.utc) + timedelta(seconds=40)).isoformat()
    async with httpx.AsyncClient(transport=transport) as client:
        result = await gc.create_reminder(
            config=config, client=client, signer=_fake_signer,
            user_id="esteban", text="urgent", when=when, lead_minutes=60,
        )
    assert result["lead_minutes"] == 0


@pytest.mark.asyncio
async def test_idempotent_replay_returns_created_false_with_the_same_id(tmp_path):
    state = {"posted": False}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/token"):
            return httpx.Response(200, json={"access_token": "tok", "expires_in": 3600})
        if request.method == "POST":
            if state["posted"]:
                return httpx.Response(409, json={"error": {"message": "already exists"}})
            state["posted"] = True
            body = json.loads(request.read())
            state["body"] = body
            return httpx.Response(200, json={**body, "htmlLink": "https://calendar.example/e"})
        if request.method == "GET":
            return httpx.Response(200, json={**state["body"], "htmlLink": "https://calendar.example/e"})
        raise AssertionError(f"unexpected method {request.method}")

    config = gc.CalendarConfig(credentials_file=_write_service_account(tmp_path), calendar_id="cal-1")
    transport = httpx.MockTransport(handler)
    when = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()
    async with httpx.AsyncClient(transport=transport) as client:
        first = await gc.create_reminder(
            config=config, client=client, signer=_fake_signer,
            user_id="esteban", text="lembrete", when=when, idempotency_key="dup-key",
        )
        second = await gc.create_reminder(
            config=config, client=client, signer=_fake_signer,
            user_id="esteban", text="lembrete", when=when, idempotency_key="dup-key",
        )

    assert first["created"] is True
    assert second["created"] is False
    assert first["reminder_id"] == second["reminder_id"]


@pytest.mark.asyncio
async def test_replaying_a_deleted_reminder_id_is_refused(tmp_path):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/token"):
            return httpx.Response(200, json={"access_token": "tok", "expires_in": 3600})
        if request.method == "POST":
            return httpx.Response(409, json={"error": {"message": "already exists"}})
        return httpx.Response(200, json={"id": "cbsomeid", "status": "cancelled"})

    config = gc.CalendarConfig(credentials_file=_write_service_account(tmp_path), calendar_id="cal-1")
    transport = httpx.MockTransport(handler)
    when = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()
    async with httpx.AsyncClient(transport=transport) as client:
        with pytest.raises(gc.CalendarAccessError, match="deleted"):
            await gc.create_reminder(
                config=config, client=client, signer=_fake_signer,
                user_id="esteban", text="lembrete", when=when, idempotency_key="deleted-key",
            )


# --------------------------------------------------------------------------
# Error mapping -- must name the share instruction and NEVER the private key
# --------------------------------------------------------------------------


@pytest.mark.parametrize("status", [403, 404])
@pytest.mark.asyncio
async def test_permission_or_not_found_names_the_client_email_and_share_instruction(tmp_path, status):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/token"):
            return httpx.Response(200, json={"access_token": "tok", "expires_in": 3600})
        return httpx.Response(status, json={"error": {"message": "denied"}})

    config = gc.CalendarConfig(credentials_file=_write_service_account(tmp_path), calendar_id="cal-1")
    transport = httpx.MockTransport(handler)
    when = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()
    async with httpx.AsyncClient(transport=transport) as client:
        with pytest.raises(gc.CalendarAccessError) as raised:
            await gc.create_reminder(
                config=config, client=client, signer=_fake_signer,
                user_id="esteban", text="lembrete", when=when,
            )
    message = str(raised.value)
    assert FAKE_SERVICE_ACCOUNT["client_email"] in message
    assert "Share with specific people" in message
    assert FAKE_SERVICE_ACCOUNT["private_key"] not in message


@pytest.mark.asyncio
async def test_invalid_grant_mentions_the_clock_as_a_possible_cause(tmp_path):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"error": "invalid_grant"})

    config = gc.CalendarConfig(credentials_file=_write_service_account(tmp_path), calendar_id="cal-1")
    transport = httpx.MockTransport(handler)
    when = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()
    async with httpx.AsyncClient(transport=transport) as client:
        with pytest.raises(gc.CalendarAccessError, match="timedatectl"):
            await gc.create_reminder(
                config=config, client=client, signer=_fake_signer,
                user_id="esteban", text="lembrete", when=when,
            )


@pytest.mark.asyncio
async def test_no_fixture_private_key_value_ever_appears_in_any_raised_message(tmp_path):
    """A blanket check across every error path this module can raise --

    a real assertion, not a comment, that `private_key` never leaks.
    """
    secret_marker = FAKE_SERVICE_ACCOUNT["private_key"]

    def handler_403(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/token"):
            return httpx.Response(200, json={"access_token": "tok", "expires_in": 3600})
        return httpx.Response(403, json={})

    def handler_invalid_grant(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"error": "invalid_grant"})

    config = gc.CalendarConfig(credentials_file=_write_service_account(tmp_path), calendar_id="cal-1")
    when = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()

    for handler in (handler_403, handler_invalid_grant):
        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(transport=transport) as client:
            with pytest.raises(gc.CalendarAccessError) as raised:
                await gc.create_reminder(
                    config=config, client=client, signer=_fake_signer,
                    user_id="esteban", text="lembrete", when=when,
                )
            assert secret_marker not in str(raised.value)


# --------------------------------------------------------------------------
# Credential file problems -- actionable, never a stacktrace
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_missing_credential_file_is_actionable(tmp_path):
    config = gc.CalendarConfig(credentials_file=str(tmp_path / "does-not-exist.json"), calendar_id="cal-1")
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(500))) as client:
        with pytest.raises(gc.CalendarConfigError, match="does not exist"):
            await gc.create_reminder(
                config=config, client=client, signer=_fake_signer,
                user_id="esteban", text="x", when=(datetime.now(timezone.utc) + timedelta(days=1)).isoformat(),
            )


@pytest.mark.asyncio
async def test_credential_file_missing_a_required_field_is_actionable(tmp_path):
    broken = dict(FAKE_SERVICE_ACCOUNT)
    del broken["private_key"]
    config = gc.CalendarConfig(credentials_file=_write_service_account(tmp_path, broken), calendar_id="cal-1")
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(500))) as client:
        with pytest.raises(gc.CalendarConfigError, match="private_key"):
            await gc.create_reminder(
                config=config, client=client, signer=_fake_signer,
                user_id="esteban", text="x", when=(datetime.now(timezone.utc) + timedelta(days=1)).isoformat(),
            )


# --------------------------------------------------------------------------
# cancel_reminder
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cancel_reminder_succeeds(tmp_path):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/token"):
            return httpx.Response(200, json={"access_token": "tok", "expires_in": 3600})
        assert request.method == "DELETE"
        return httpx.Response(204)

    config = gc.CalendarConfig(credentials_file=_write_service_account(tmp_path), calendar_id="cal-1")
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await gc.cancel_reminder(config=config, client=client, signer=_fake_signer, reminder_id="cbabc")
    assert result == {"reminder_id": "cbabc", "cancelled": True}


@pytest.mark.asyncio
async def test_cancel_reminder_already_gone_is_success(tmp_path):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/token"):
            return httpx.Response(200, json={"access_token": "tok", "expires_in": 3600})
        return httpx.Response(410)

    config = gc.CalendarConfig(credentials_file=_write_service_account(tmp_path), calendar_id="cal-1")
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await gc.cancel_reminder(config=config, client=client, signer=_fake_signer, reminder_id="cbabc")
    assert result["cancelled"] is True


# --------------------------------------------------------------------------
# list_reminders (issue #72)
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_reminders_filters_by_source_and_normalizes_the_shape(tmp_path):
    captured_query: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/token"):
            return httpx.Response(200, json={"access_token": "tok", "expires_in": 3600})
        captured_query["params"] = list(request.url.params.multi_items())
        return httpx.Response(
            200,
            json={
                "items": [
                    {
                        "id": "cbone",
                        "summary": "Ligar para o contador",
                        "description": "Lembrete criado pelo CodexBridge a pedido de esteban@example.com (via ChatGPT).",
                        "start": {"dateTime": "2099-01-01T10:00:00-03:00", "timeZone": "America/Sao_Paulo"},
                        "htmlLink": "https://calendar.example/e1",
                        "reminders": {"useDefault": False, "overrides": [{"method": "popup", "minutes": 30}]},
                    }
                ],
                "nextPageToken": "next-1",
            },
        )

    config = gc.CalendarConfig(credentials_file=_write_service_account(tmp_path), calendar_id="cal-1")
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await gc.list_reminders(
            config=config, client=client, signer=_fake_signer, requested_by="esteban@example.com"
        )

    assert result["items"] == [
        {
            "reminder_id": "cbone",
            "calendar_id": "cal-1",
            "summary": "Ligar para o contador",
            "notes": "Lembrete criado pelo CodexBridge a pedido de esteban@example.com (via ChatGPT).",
            "scheduled_for": "2099-01-01T10:00:00-03:00",
            "timezone": "America/Sao_Paulo",
            "lead_minutes": 30,
            "html_link": "https://calendar.example/e1",
        }
    ]
    assert result["next_page_token"] == "next-1"

    params = captured_query["params"]
    assert ("privateExtendedProperty", "source=codexbridge") in params
    assert ("privateExtendedProperty", "requested_by=esteban@example.com") in params
    assert ("singleEvents", "true") in params
    assert ("orderBy", "startTime") in params


@pytest.mark.asyncio
async def test_list_reminders_drops_a_cancelled_event_defensively(tmp_path):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/token"):
            return httpx.Response(200, json={"access_token": "tok", "expires_in": 3600})
        return httpx.Response(
            200,
            json={
                "items": [
                    {"id": "cbgone", "status": "cancelled"},
                    {
                        "id": "cbstill-here",
                        "summary": "x",
                        "start": {"dateTime": "2099-01-01T10:00:00-03:00"},
                    },
                ]
            },
        )

    config = gc.CalendarConfig(credentials_file=_write_service_account(tmp_path), calendar_id="cal-1")
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await gc.list_reminders(config=config, client=client, signer=_fake_signer)

    assert [item["reminder_id"] for item in result["items"]] == ["cbstill-here"]


@pytest.mark.asyncio
async def test_list_reminders_unconfigured_gateway_refuses_before_touching_the_network(tmp_path):
    config = gc.CalendarConfig(credentials_file="", calendar_id="")

    async def _boom(request: httpx.Request) -> httpx.Response:  # pragma: no cover - must not run
        raise AssertionError("must not touch the network when unconfigured")

    async with httpx.AsyncClient(transport=httpx.MockTransport(_boom)) as client:
        with pytest.raises(gc.CalendarConfigError):
            await gc.list_reminders(config=config, client=client, signer=_fake_signer)


@pytest.mark.asyncio
async def test_list_reminders_sharing_error_names_the_client_email(tmp_path):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/token"):
            return httpx.Response(200, json={"access_token": "tok", "expires_in": 3600})
        return httpx.Response(404)

    config = gc.CalendarConfig(credentials_file=_write_service_account(tmp_path), calendar_id="cal-1")
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(gc.CalendarAccessError) as raised:
            await gc.list_reminders(config=config, client=client, signer=_fake_signer)
    assert FAKE_SERVICE_ACCOUNT["client_email"] in str(raised.value)
    assert "Make changes to events" in str(raised.value)


# --------------------------------------------------------------------------
# check_access
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_check_access_reports_calendar_summary_and_timezone(tmp_path):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/token"):
            return httpx.Response(200, json={"access_token": "tok", "expires_in": 3600})
        return httpx.Response(200, json={"summary": "CodexBridge", "timeZone": "America/Sao_Paulo"})

    config = gc.CalendarConfig(credentials_file=_write_service_account(tmp_path), calendar_id="cal-1")
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await gc.check_access(config, client=client, signer=_fake_signer)
    assert result == {"summary": "CodexBridge", "timeZone": "America/Sao_Paulo"}


# --------------------------------------------------------------------------
# Real openssl signing -- skipped if the binary is absent (e.g. some CI images)
# --------------------------------------------------------------------------


requires_openssl = pytest.mark.skipif(shutil.which("openssl") is None, reason="openssl binary not on PATH")


@requires_openssl
@pytest.mark.asyncio
async def test_openssl_sign_rs256_produces_a_verifiable_signature(tmp_path):
    key_path = tmp_path / "key.pem"
    pub_path = tmp_path / "key.pub.pem"
    subprocess.run(
        ["openssl", "genpkey", "-algorithm", "RSA", "-pkeyopt", "rsa_keygen_bits:2048", "-out", str(key_path)],
        check=True, capture_output=True,
    )
    subprocess.run(["openssl", "rsa", "-in", str(key_path), "-pubout", "-out", str(pub_path)], check=True, capture_output=True)

    signing_input = b"header.claims"
    signature = await gc.openssl_sign_rs256(signing_input, key_path.read_text())

    sig_path = tmp_path / "sig.bin"
    data_path = tmp_path / "data.bin"
    sig_path.write_bytes(signature)
    data_path.write_bytes(signing_input)
    result = subprocess.run(
        ["openssl", "dgst", "-sha256", "-verify", str(pub_path), "-signature", str(sig_path), str(data_path)],
        capture_output=True, text=True,
    )
    assert result.returncode == 0
    assert "Verified OK" in result.stdout
