"""A Google Calendar client for reminders, built to be tested without ever

touching Google. WK-20260830-chatgpt-entry-provider-and-delivery, issues
#71 (MCP tools) / #72 (REST surface).

## Why the gateway, not the executor

A reminder's value is a synchronous reply in the same conversation
("Pronto, lembrete criado para sexta as 15h"). Routing through the executor
would make the answer "queued" with nothing to close the loop -- there is no
scheduler and no push channel (see `gateway/app/main.py`'s own comment: "no
scheduler, and adding one is a bigger change"). And `devel3` is a
workstation: asleep, the reminder would be silently queued, and a reminder
that does not exist is worse than an error.

## Why openssl by subprocess, not a crypto dependency

The service-account JWT is RS256, which the stdlib cannot sign. This
project's `pyproject.toml` declares no `google-*` and no crypto library.
`/usr/bin/openssl` is already the ecosystem's precedent for exactly this
(`job-outreach/src/outreach/calendar_client.py`), so the private key is
written to a mode-0600 temp file, deleted immediately after signing, and the
signing itself is `openssl dgst -sha256 -sign <keyfile>` with the JWT
signing-input on stdin. The access token is cached in-process for ~55
minutes (Google issues 60-minute tokens), so this subprocess spawn is rare,
not per-call.

## Why a deterministic event id instead of a new table

`/mcp` is deliberately outside the `Idempotency-Key` middleware
(`gateway/app/api/scope.py`). An optional `idempotency_key` argument is
folded into a base32hex event id -- exactly the alphabet Google's Calendar
API accepts for a caller-supplied id -- so a retry with the same key hits
Google's own `409` and this module answers `created: False` with the same
id, durable across gateway restarts, no migration required.

## `list_reminders` (issue #72)

#71 deliberately shipped no `list_reminders` MCP tool -- the operator already
has the Google Calendar app for browsing. #72's whole reason to exist is a
phone client that does not have that app open, so the REST surface needs a
list this module did not have. Added here, additive: `create_reminder` and
`cancel_reminder` are byte-for-byte what #71 shipped.

Filters on `extendedProperties.private.source = "codexbridge"` -- Google's own
`privateExtendedProperty` query parameter, not a client-side filter -- so this
can never become a way to read the rest of the shared calendar. It also
narrows to the calling user's own `requested_by`, ANDed the same way: nothing
in this build depends on it (one operator, one calendar, today), but the value
was populated from day one for exactly this, and filtering by the caller's own
identity by default is the safer failure direction the moment a second user is
ever granted the scope.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import os
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Awaitable, Callable

import httpx
from dateutil import parser as dateutil_parser


TOKEN_URI_DEFAULT = "https://oauth2.googleapis.com/token"
CALENDAR_API_BASE = "https://www.googleapis.com/calendar/v3"
CALENDAR_SCOPE = "https://www.googleapis.com/auth/calendar"
DEFAULT_TIMEZONE = "America/Sao_Paulo"

# Google's own event-id constraint: base32hex characters only (0-9, a-v),
# 5 to 1024 characters. "cb" (both valid characters) marks these as
# CodexBridge-created without affecting the alphabet.
_EVENT_ID_PREFIX = "cb"
_EVENT_ID_LENGTH = 26  # + the 2-char prefix = 28, well inside [5, 1024]

_REMINDER_LEAD_MAX_MINUTES = 40320  # 28 days
_REMINDER_MAX_FUTURE = timedelta(days=730)
_REMINDER_MIN_LEAD_FROM_NOW = timedelta(seconds=30)

# Access tokens last ~3600s; refreshed with 5 minutes of margin so a call
# never straddles expiry mid-flight.
_TOKEN_TTL_MARGIN_SECONDS = 300

_HTTP_TIMEOUT = httpx.Timeout(connect=10.0, read=20.0, write=10.0, pool=10.0)

Signer = Callable[[bytes, str], Awaitable[bytes]]


class CalendarConfigError(RuntimeError):
    """The gateway itself is not set up for reminders -- an operator problem,

    never the caller's fault. Always actionable: names the missing setting
    or the specific reason a credential file could not be used.
    """


class CalendarAccessError(RuntimeError):
    """Google refused the request, or it could not be reached in time.

    Message text is always safe to relay to ChatGPT (and from there, read
    aloud to the operator) -- it may name the service account's
    `client_email` (not a secret) but never its `private_key`.
    """


class NaiveDatetimeError(CalendarAccessError):
    """`when` had no UTC offset.

    Issue #71's own Requirements are explicit about why this is a hard
    rejection rather than a guess: ChatGPT already holds the operator's
    timezone and the current instant before it ever calls this tool/endpoint
    (see `google_calendar.py`'s module docstring and #71's "why the tool
    takes a computed datetime, not free text"), so an offset-less value
    means something went wrong upstream -- not that the caller forgot and
    meant "here". Silently assuming a timezone would produce a reminder that
    fires at the wrong hour with nobody noticing until it doesn't. Typed
    (rather than a bare `CalendarAccessError`) so a caller that wants to
    special-case it can, while both transports still catch it as the
    `CalendarAccessError` it is a subclass of, and answer it exactly like
    every other `when` validation failure.
    """

    def __init__(self, when: str):
        self.when = when
        super().__init__(
            f"'when' ({when!r}) has no UTC offset. Send ISO 8601 with an explicit "
            "offset, e.g. '2026-09-04T15:00:00-03:00', or a trailing 'Z' for UTC. "
            "The caller is expected to resolve the operator's own timezone before "
            "calling -- this server does not guess one."
        )


@dataclass(frozen=True)
class CalendarConfig:
    credentials_file: str
    calendar_id: str


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


async def openssl_sign_rs256(signing_input: bytes, private_key_pem: str) -> bytes:
    """The default `Signer`: shells out to `openssl dgst -sha256 -sign`.

    The private key touches disk only in a mode-0600 temp file that is
    unlinked in a `finally`, for exactly as long as the one `openssl`
    invocation needs it -- never passed as a command-line argument (which
    would land in `/proc/*/cmdline` and process listings), and never logged.
    """
    with NamedTemporaryFile(mode="w", suffix=".pem", delete=False) as handle:
        handle.write(private_key_pem)
        key_path = handle.name
    try:
        os.chmod(key_path, 0o600)
        process = await asyncio.create_subprocess_exec(
            "openssl", "dgst", "-sha256", "-sign", key_path,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await process.communicate(signing_input)
        if process.returncode != 0:
            raise CalendarConfigError(
                f"openssl failed to sign the reminder JWT: {stderr.decode('utf-8', errors='replace').strip()}"
            )
        return stdout
    finally:
        os.unlink(key_path)


def _load_service_account(path: str) -> dict:
    file_path = Path(path).expanduser()
    if not file_path.is_file():
        raise CalendarConfigError(
            f"the Google service-account credential file at {path!r} does not exist or is not readable."
        )
    try:
        data = json.loads(file_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CalendarConfigError(f"the credential file at {path!r} is not valid JSON: {exc}") from exc
    for key in ("client_email", "private_key", "token_uri"):
        if key not in data:
            raise CalendarConfigError(f"the credential file at {path!r} is missing required field {key!r}.")
    return data


_TOKEN_CACHE: dict[str, tuple[str, float]] = {}


async def _mint_access_token(service_account: dict, *, client: httpx.AsyncClient, signer: Signer) -> tuple[str, float]:
    now = int(time.time())
    header = _b64url(json.dumps({"alg": "RS256", "typ": "JWT"}, separators=(",", ":")).encode("utf-8"))
    claims = _b64url(
        json.dumps(
            {
                "iss": service_account["client_email"],
                "scope": CALENDAR_SCOPE,
                "aud": service_account.get("token_uri", TOKEN_URI_DEFAULT),
                "iat": now,
                "exp": now + 3600,
            },
            separators=(",", ":"),
        ).encode("utf-8")
    )
    signing_input = f"{header}.{claims}"
    signature = await signer(signing_input.encode("ascii"), service_account["private_key"])
    assertion = f"{signing_input}.{_b64url(signature)}"

    try:
        response = await client.post(
            service_account.get("token_uri", TOKEN_URI_DEFAULT),
            data={"grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer", "assertion": assertion},
            timeout=_HTTP_TIMEOUT,
        )
    except httpx.TimeoutException as exc:
        raise CalendarAccessError("timed out contacting Google's token endpoint.") from exc
    except httpx.HTTPError as exc:
        raise CalendarAccessError(f"could not reach Google's token endpoint: {exc}") from exc

    if response.status_code == 400 and "invalid_grant" in response.text:
        raise CalendarAccessError(
            "Google rejected the service-account key (invalid_grant). Usual causes: the key was "
            "revoked or deleted, or this host's clock is wrong (a JWT's iat/exp are checked "
            "server-side). Check `timedatectl status` on the gateway."
        )
    if response.status_code != 200:
        raise CalendarAccessError(f"Google's token endpoint returned HTTP {response.status_code}: {response.text[:300]}")

    body = response.json()
    return body["access_token"], now + int(body.get("expires_in", 3600))


async def _access_token(service_account: dict, *, client: httpx.AsyncClient, signer: Signer) -> str:
    cache_key = service_account["client_email"]
    cached = _TOKEN_CACHE.get(cache_key)
    now = time.time()
    if cached is not None and cached[1] - _TOKEN_TTL_MARGIN_SECONDS > now:
        return cached[0]
    token, expires_at = await _mint_access_token(service_account, client=client, signer=signer)
    _TOKEN_CACHE[cache_key] = (token, expires_at)
    return token


def _raise_for_calendar_error(response: httpx.Response, service_account: dict, config: CalendarConfig) -> None:
    client_email = service_account.get("client_email", "<unknown>")
    if response.status_code in (403, 404):
        raise CalendarAccessError(
            f"Calendar {config.calendar_id!r} was not found, or it has not been shared with "
            f"{client_email}. In Google Calendar, open Settings for that calendar, choose "
            "'Share with specific people', and add that address with 'Make changes to events' "
            "(read-only access is not enough)."
        )
    raise CalendarAccessError(f"Google Calendar API returned HTTP {response.status_code}: {response.text[:300]}")


def _event_id(user_id: str, idempotency_key: str | None, when_iso: str, text: str) -> str:
    seed = f"{user_id}|{idempotency_key}" if idempotency_key else f"{user_id}|{when_iso}|{text.strip().casefold()}"
    digest = hashlib.sha256(seed.encode("utf-8")).digest()
    encoded = base64.b32hexencode(digest).decode("ascii").lower().rstrip("=")
    return f"{_EVENT_ID_PREFIX}{encoded[:_EVENT_ID_LENGTH]}"


def parse_when(when: str) -> datetime:
    """Parses `when` as ISO 8601 with an explicit UTC offset.

    A naive (offset-less) value is rejected, not assumed into
    `DEFAULT_TIMEZONE` -- see `NaiveDatetimeError` for why. `isoparse`
    rather than `datetime.fromisoformat`: the latter rejects a trailing `Z`
    on Python 3.10.
    """
    try:
        parsed = dateutil_parser.isoparse(when)
    except (ValueError, OverflowError) as exc:
        raise CalendarAccessError(f"'when' is not a valid ISO 8601 datetime: {when!r}.") from exc
    if parsed.tzinfo is None:
        raise NaiveDatetimeError(when)
    return parsed


async def create_reminder(
    *,
    config: CalendarConfig,
    client: httpx.AsyncClient,
    signer: Signer = openssl_sign_rs256,
    user_id: str,
    text: str,
    when: str,
    notes: str | None = None,
    lead_minutes: int = 0,
    idempotency_key: str | None = None,
    created_via: str = "mcp",
) -> dict:
    if not config.calendar_id or not config.credentials_file:
        raise CalendarConfigError(
            "Reminders are not configured on this gateway: no target calendar. The operator must "
            "set CODEX_BRIDGE_GOOGLE_CALENDAR_ID and CODEX_BRIDGE_GOOGLE_CALENDAR_CREDENTIALS_FILE."
        )
    service_account = _load_service_account(config.credentials_file)

    when_dt = parse_when(when)
    now = datetime.now(timezone.utc)
    if when_dt <= now + _REMINDER_MIN_LEAD_FROM_NOW:
        raise CalendarAccessError(
            f"'when' ({when_dt.isoformat()}) is not far enough in the future (server now is "
            f"{now.isoformat()})."
        )
    if when_dt - now > _REMINDER_MAX_FUTURE:
        raise CalendarAccessError("'when' is more than 2 years in the future.")

    lead_minutes = max(0, min(int(lead_minutes), _REMINDER_LEAD_MAX_MINUTES))
    clamped_lead = lead_minutes
    if lead_minutes and (when_dt - timedelta(minutes=lead_minutes)) <= now:
        clamped_lead = 0

    event_id = _event_id(user_id, idempotency_key, when_dt.isoformat(), text)
    end_dt = when_dt + timedelta(minutes=15)
    description = f"Lembrete criado pelo CodexBridge a pedido de {user_id} (via ChatGPT)."
    if notes:
        description += f"\n\n{notes}"

    body = {
        "id": event_id,
        "summary": text[:200],
        "description": description,
        "start": {"dateTime": when_dt.isoformat(), "timeZone": DEFAULT_TIMEZONE},
        "end": {"dateTime": end_dt.isoformat(), "timeZone": DEFAULT_TIMEZONE},
        # A reminder must never mark the operator busy or eat a free/busy
        # slot -- the single most common mistake with this pattern.
        "transparency": "transparent",
        "reminders": {"useDefault": False, "overrides": [{"method": "popup", "minutes": clamped_lead}]},
        # No "attendees" key, ever: a service account without Domain-Wide
        # Delegation gets 403 forbiddenForServiceAccounts for adding one. The
        # reminder reaches the operator by calendar MEMBERSHIP, not invitation.
        #
        # `created_via` and `idempotency_key` are populated from day one
        # (issue #71's own "event shape" requirement), the same reasoning as
        # `requested_by`: adding them later would not retroactively tag
        # events already created, and #72's `list_reminders` exists
        # specifically to filter and correlate on fields written here.
        # Google requires string values, so an absent `idempotency_key`
        # writes "" rather than a JSON null.
        "extendedProperties": {
            "private": {
                "source": "codexbridge",
                "kind": "reminder",
                "requested_by": user_id,
                "created_via": created_via,
                "idempotency_key": idempotency_key or "",
            }
        },
    }

    token = await _access_token(service_account, client=client, signer=signer)
    headers = {"Authorization": f"Bearer {token}"}
    events_url = f"{CALENDAR_API_BASE}/calendars/{config.calendar_id}/events"

    try:
        response = await client.post(events_url, headers=headers, json=body, timeout=_HTTP_TIMEOUT)
    except httpx.TimeoutException as exc:
        raise CalendarAccessError("timed out reaching the Google Calendar API.") from exc
    except httpx.HTTPError as exc:
        raise CalendarAccessError(f"could not reach the Google Calendar API: {exc}") from exc

    created = True
    if response.status_code == 409:
        created = False
        try:
            response = await client.get(f"{events_url}/{event_id}", headers=headers, timeout=_HTTP_TIMEOUT)
        except httpx.TimeoutException as exc:
            raise CalendarAccessError("timed out reaching the Google Calendar API.") from exc
        if response.status_code != 200:
            _raise_for_calendar_error(response, service_account, config)
        payload = response.json()
        if payload.get("status") == "cancelled":
            raise CalendarAccessError(
                f"a reminder with this idempotency key ({event_id!r}) already existed and was "
                "deleted from the calendar. The same key cannot be reused for a new reminder."
            )
    elif response.status_code not in (200, 201):
        _raise_for_calendar_error(response, service_account, config)
        payload = {}  # unreachable -- _raise_for_calendar_error always raises
    else:
        payload = response.json()

    return {
        "reminder_id": payload.get("id", event_id),
        "calendar_id": config.calendar_id,
        "summary": payload.get("summary", body["summary"]),
        "scheduled_for": when_dt.isoformat(),
        "timezone": DEFAULT_TIMEZONE,
        "lead_minutes": clamped_lead,
        "created": created,
        "html_link": payload.get("htmlLink"),
    }


async def cancel_reminder(
    *,
    config: CalendarConfig,
    client: httpx.AsyncClient,
    signer: Signer = openssl_sign_rs256,
    reminder_id: str,
) -> dict:
    if not config.calendar_id or not config.credentials_file:
        raise CalendarConfigError(
            "Reminders are not configured on this gateway: no target calendar. The operator must "
            "set CODEX_BRIDGE_GOOGLE_CALENDAR_ID and CODEX_BRIDGE_GOOGLE_CALENDAR_CREDENTIALS_FILE."
        )
    service_account = _load_service_account(config.credentials_file)
    token = await _access_token(service_account, client=client, signer=signer)
    headers = {"Authorization": f"Bearer {token}"}
    url = f"{CALENDAR_API_BASE}/calendars/{config.calendar_id}/events/{reminder_id}"
    try:
        response = await client.delete(url, headers=headers, timeout=_HTTP_TIMEOUT)
    except httpx.TimeoutException as exc:
        raise CalendarAccessError("timed out reaching the Google Calendar API.") from exc
    except httpx.HTTPError as exc:
        raise CalendarAccessError(f"could not reach the Google Calendar API: {exc}") from exc
    # 410 (Gone): already deleted -- treated as success, the caller's goal
    # ("this reminder should not exist") is already true.
    if response.status_code not in (200, 204, 410):
        _raise_for_calendar_error(response, service_account, config)
    return {"reminder_id": reminder_id, "cancelled": True}


def _reminder_from_event(event: dict, config: CalendarConfig) -> dict:
    """Normalizes one Google Calendar event into this module's reminder shape.

    Mirrors `create_reminder`'s return dict field-for-field, minus `created`
    (meaningless for something already listed) -- so a caller of both
    functions handles one shape. `notes` is a best-effort read of
    `description`: `create_reminder` writes a boilerplate attribution line
    ahead of the caller's own notes (see its own body), and that line is not
    stripped back out here -- splitting it out again would be a second,
    drifting definition of what the boilerplate looks like. Honest, not
    exact.
    """
    start = event.get("start") or {}
    overrides = ((event.get("reminders") or {}).get("overrides")) or []
    lead_minutes = overrides[0].get("minutes", 0) if overrides else 0
    return {
        "reminder_id": event.get("id"),
        "calendar_id": config.calendar_id,
        "summary": event.get("summary", ""),
        "notes": event.get("description"),
        "scheduled_for": start.get("dateTime"),
        "timezone": start.get("timeZone") or DEFAULT_TIMEZONE,
        "lead_minutes": lead_minutes,
        "html_link": event.get("htmlLink"),
    }


async def list_reminders(
    *,
    config: CalendarConfig,
    client: httpx.AsyncClient,
    signer: Signer = openssl_sign_rs256,
    requested_by: str | None = None,
    limit: int = 50,
    page_token: str | None = None,
) -> dict:
    """CodexBridge-created reminders on the configured calendar, newest first.

    Always constrained to `extendedProperties.private.source = "codexbridge"`
    via Google's own query filter -- see the module docstring's "why" -- and,
    when `requested_by` is given, additionally to that value. Both constraints
    are server-side (`privateExtendedProperty` is repeatable and ANDed), never
    applied after the fact to a broader read.
    """
    if not config.calendar_id or not config.credentials_file:
        raise CalendarConfigError(
            "Reminders are not configured on this gateway: no target calendar. The operator must "
            "set CODEX_BRIDGE_GOOGLE_CALENDAR_ID and CODEX_BRIDGE_GOOGLE_CALENDAR_CREDENTIALS_FILE."
        )
    service_account = _load_service_account(config.credentials_file)
    token = await _access_token(service_account, client=client, signer=signer)
    headers = {"Authorization": f"Bearer {token}"}
    params: list[tuple[str, str]] = [
        ("privateExtendedProperty", "source=codexbridge"),
        ("singleEvents", "true"),
        ("orderBy", "startTime"),
        ("maxResults", str(max(1, min(int(limit), 2500)))),
    ]
    if requested_by:
        params.append(("privateExtendedProperty", f"requested_by={requested_by}"))
    if page_token:
        params.append(("pageToken", page_token))

    url = f"{CALENDAR_API_BASE}/calendars/{config.calendar_id}/events"
    try:
        response = await client.get(url, headers=headers, params=params, timeout=_HTTP_TIMEOUT)
    except httpx.TimeoutException as exc:
        raise CalendarAccessError("timed out reaching the Google Calendar API.") from exc
    except httpx.HTTPError as exc:
        raise CalendarAccessError(f"could not reach the Google Calendar API: {exc}") from exc
    if response.status_code != 200:
        _raise_for_calendar_error(response, service_account, config)

    payload = response.json()
    items = [
        _reminder_from_event(event, config)
        for event in payload.get("items", [])
        # `showDeleted` defaults to False, so this is defence in depth, not
        # the only guard against a cancelled event slipping into a list.
        if event.get("status") != "cancelled"
    ]
    return {"items": items, "next_page_token": payload.get("nextPageToken")}


async def check_access(config: CalendarConfig, *, client: httpx.AsyncClient, signer: Signer = openssl_sign_rs256) -> dict:
    """Confirms the configured credential can actually read the configured

    calendar -- the manual verifier this module's own `__main__` block runs,
    and a useful first call for any live smoke test. Never prints or returns
    anything from `private_key`.
    """
    service_account = _load_service_account(config.credentials_file)
    token = await _access_token(service_account, client=client, signer=signer)
    url = f"{CALENDAR_API_BASE}/calendars/{config.calendar_id}"
    try:
        response = await client.get(url, headers={"Authorization": f"Bearer {token}"}, timeout=_HTTP_TIMEOUT)
    except httpx.TimeoutException as exc:
        raise CalendarAccessError("timed out reaching the Google Calendar API.") from exc
    if response.status_code != 200:
        _raise_for_calendar_error(response, service_account, config)
    payload = response.json()
    return {"summary": payload.get("summary"), "timeZone": payload.get("timeZone")}


if __name__ == "__main__":
    import asyncio
    import sys

    async def _main() -> int:
        config = CalendarConfig(
            credentials_file=os.environ.get("CODEX_BRIDGE_GOOGLE_CALENDAR_CREDENTIALS_FILE", ""),
            calendar_id=os.environ.get("CODEX_BRIDGE_GOOGLE_CALENDAR_ID", ""),
        )
        async with httpx.AsyncClient() as client:
            try:
                result = await check_access(config, client=client)
            except (CalendarConfigError, CalendarAccessError) as exc:
                print(f"failed: {exc}", file=sys.stderr)
                return 1
        print(f"ok: {result['summary']} / {result['timeZone']}")
        return 0

    raise SystemExit(asyncio.run(_main()))
