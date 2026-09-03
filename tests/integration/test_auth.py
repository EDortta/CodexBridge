"""The mobile credential lifecycle — issue #4.

Weighted towards the four failure cases the issue names — expired, revoked,
unauthenticated, insufficient permission — plus the two properties that are
easy to claim and easy to get wrong: that a revocation actually takes effect on
the credential store the *other* transport reads, and that what
`GET /api/v1/auth/me` tells a client it may do is what the endpoints do.

The sessions, decisions, missions, epics and issues routers are mounted
alongside the auth router on purpose. A permission report tested against
itself proves only that a dictionary was copied; tested against the
endpoints it describes, it proves
the claim.
"""

from __future__ import annotations

import base64
import hashlib
import json
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from gateway.app.api import permissions
from gateway.app.api.routes import artifacts as artifacts_routes
from gateway.app.api.routes import auth as auth_routes
from gateway.app.api.routes import authorizations as authorizations_routes
from gateway.app.api.routes import conversations as conversations_routes
from gateway.app.api.routes import decisions as decisions_routes
from gateway.app.api.routes import enrollment as enrollment_routes
from gateway.app.api.routes import discovery as discovery_routes
from gateway.app.api.routes import epics as epics_routes
from gateway.app.api.routes import events as events_routes
from gateway.app.api.routes import issues as issues_routes
from gateway.app.api.routes import nodes as nodes_routes
from gateway.app.api.routes import missions as missions_routes
from gateway.app.api.routes import notifications as notifications_routes
from gateway.app.api.routes import projects as projects_routes
from gateway.app.api.routes import sessions as sessions_routes
from gateway.app.api.setup import install_api_conventions
from gateway.app.db.base import Base
from gateway.app.db.session import get_session
from gateway.app.models.entities import (
    AuditEventModel,
    OAuthAccessTokenModel,
    OAuthRefreshTokenModel,
)
from gateway.app.services import store
from shared.protocol import (
    ExecutorRegistration,
    ProjectRegistration,
    SubmitTaskRequest,
    TaskMode,
    TaskPriority,
)
from shared.security import hash_token


PASSWORD = "correct-horse-battery-staple"
OTHER_PASSWORD = "not-the-password"


def _hash(password: str, iterations: int = 1000) -> str:
    """A registry hash, cheap on purpose.

    `verify_password` reads the iteration count out of the hash, so a test
    fixture can cost a thousand iterations while production costs six hundred
    thousand. The decoy path is the one place a test still pays full price, and
    that is the point of it.
    """
    salt = b"codexbridge-test-salt"
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    encode = lambda raw: base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")  # noqa: E731
    return "$".join(("pbkdf2_sha256", str(iterations), encode(salt), encode(digest)))


def _registry(*, alice_scopes: list[str] | None = None, alice_enabled: bool = True) -> dict:
    return {
        "users": [
            {
                "user_id": "alice",
                "email": "alice@example.com",
                "password_hash": _hash(PASSWORD),
                "roles": [],
                "allowed_projects": ["p1"],
                "scopes": alice_scopes
                if alice_scopes is not None
                else ["codexbridge.read", "codexbridge.task.cancel"],
                "enabled": alice_enabled,
            },
            {
                "user_id": "reader",
                "email": "reader@example.com",
                "password_hash": _hash(PASSWORD),
                "roles": [],
                "allowed_projects": ["p1"],
                "scopes": ["codexbridge.read"],
                "enabled": True,
            },
            {
                "user_id": "admin",
                "email": "admin@example.com",
                "password_hash": _hash(PASSWORD),
                "roles": ["admin"],
                "allowed_projects": [],
                "scopes": ["codexbridge.admin"],
                "enabled": True,
            },
            {
                "user_id": "retired",
                "email": "retired@example.com",
                "password_hash": _hash(PASSWORD),
                "roles": [],
                "allowed_projects": ["p1"],
                "scopes": ["codexbridge.read"],
                "enabled": False,
            },
        ]
    }


@pytest.fixture
def users_file(tmp_path):
    path = tmp_path / "users.json"
    path.write_text(json.dumps(_registry()), encoding="utf-8")
    return path


@pytest.fixture
async def api(users_file, monkeypatch):
    """The auth and sessions routers over a real database."""
    from gateway.app.core.config import settings

    monkeypatch.setattr(settings, "user_registry_file", str(users_file))

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
                    allowed_projects=["p1"], enabled=True,
                )
            ],
            projects=[
                ProjectRegistration(
                    project_id="p1", name="p1", path="/srv/p1",
                    allowed_modes=[TaskMode.ANALYZE], max_timeout_seconds=600,
                    sensitive_patterns=[], enabled=True,
                )
            ],
        )

    app = FastAPI(openapi_url=None, docs_url=None, redoc_url=None)
    install_api_conventions(app)
    app.include_router(auth_routes.router)
    app.include_router(sessions_routes.router)
    app.include_router(projects_routes.router)
    app.include_router(decisions_routes.router)
    app.include_router(missions_routes.router)
    app.include_router(epics_routes.router)
    app.include_router(issues_routes.router)
    app.include_router(conversations_routes.router)
    app.include_router(artifacts_routes.router)
    app.include_router(events_routes.router)
    app.include_router(notifications_routes.router)
    app.include_router(nodes_routes.router)
    app.include_router(enrollment_routes.router)
    app.include_router(discovery_routes.router)
    app.include_router(authorizations_routes.router)

    async def override():
        async with factory() as s:
            yield s

    app.dependency_overrides[get_session] = override

    client = TestClient(app, raise_server_exceptions=False)
    client.factory = factory      # type: ignore[attr-defined]
    client.users_file = users_file  # type: ignore[attr-defined]
    yield client
    await engine.dispose()


def sign_in(api, username: str = "alice", password: str = PASSWORD):
    return api.post("/api/v1/auth/sign-in", json={"username": username, "password": password})


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


async def audit_events(factory, event_type: str) -> list[AuditEventModel]:
    async with factory() as s:
        rows = await s.execute(
            select(AuditEventModel).where(AuditEventModel.event_type == event_type)
        )
        return list(rows.scalars())


# --------------------------------------------------------------------------
# Sign-in
# --------------------------------------------------------------------------


async def test_sign_in_returns_a_pair_that_works(api) -> None:
    response = sign_in(api)
    assert response.status_code == 200
    body = response.json()
    assert body["tokenType"] == "Bearer"
    assert body["accessToken"] and body["refreshToken"]
    assert body["accessToken"] != body["refreshToken"]
    assert body["scopes"] == ["codexbridge.read", "codexbridge.task.cancel"]
    assert body["accessTokenExpiresAt"].endswith("Z")

    assert api.get("/api/v1/sessions", headers=auth(body["accessToken"])).status_code == 200


async def test_a_token_response_is_never_cached(api) -> None:
    """It carries credentials. RFC 6749 §5.1."""
    assert sign_in(api).headers["Cache-Control"] == "no-store"


@pytest.mark.parametrize(
    ("username", "password"),
    [
        ("alice", OTHER_PASSWORD),   # wrong password
        ("nobody", PASSWORD),        # unknown account
        ("retired", PASSWORD),       # disabled account, right password
    ],
)
async def test_every_sign_in_failure_answers_the_same(api, username: str, password: str) -> None:
    """Anything finer turns the sign-in form into a user directory."""
    response = sign_in(api, username, password)
    assert response.status_code == 401
    body = response.json()
    assert body["code"] == "unauthenticated"
    assert body["message"] == "Sign-in failed."
    assert "Bearer" in response.headers.get("WWW-Authenticate", "")


async def test_a_failed_sign_in_is_attributed_without_storing_what_was_typed(api) -> None:
    """The reason is worth keeping. The input is not: it is unvalidated, and an
    operator who mistypes a password into the username field would otherwise
    have it committed to the audit trail."""
    assert sign_in(api, "alice", OTHER_PASSWORD).status_code == 401
    assert sign_in(api, "s3cr3t-typed-in-the-wrong-box", PASSWORD).status_code == 401

    events = await audit_events(api.factory, "auth.sign_in_failed")
    assert [event.entity_id for event in events] == ["alice", "unknown"]
    assert json.loads(events[0].payload_json)["reason"] == "bad_password"
    assert json.loads(events[1].payload_json)["reason"] == "unknown_user"
    everything = " ".join(event.payload_json for event in events)
    assert "s3cr3t-typed-in-the-wrong-box" not in everything
    assert OTHER_PASSWORD not in everything


async def test_an_unconfigured_gateway_has_no_account_to_sign_in_as(api, monkeypatch) -> None:
    """`security-standards.md` §1: no default user password; fail-fast on missing config.

    `user_registry_file` defaulted to `examples/users.json`, which ships one
    `admin` account granting every scope including `codexbridge.admin` — and the
    plaintext of its hash is committed in this repository. Before issue #4 the
    only network path to that credential was the browser form, which needs a
    registered `client_id`, an allowlisted `redirect_uri` prefix and PKCE, and
    which caps the grant below `codexbridge.admin`. `POST /api/v1/auth/sign-in`
    made it one unauthenticated JSON body.

    A deployment that sets nothing now has no registry at all: the file is
    absent, so every sign-in is refused, at the same cost as any other.
    """
    from gateway.app.core.config import Settings, settings

    default = Settings.model_fields["user_registry_file"].default
    assert "examples" not in default, (
        f"the default registry resolves to a file in this repository: {default}"
    )

    monkeypatch.setattr(settings, "user_registry_file", default)
    response = sign_in(api, "admin", "change-me-now")
    assert response.status_code == 401


async def test_an_unconfigured_gateway_says_so_instead_of_failing_in_silence(
    tmp_path, monkeypatch, caplog
) -> None:
    """Fail-closed is only half of it; the other half is saying why.

    The upgrade path is the one that lands here: a deployment that never set
    `CODEX_BRIDGE_USER_REGISTRY_FILE` worked while the default resolved to a
    bundled file, and the fix that stopped it resolving there gave that
    deployment no registry at all. It then starts clean — `/health` ok, `/ready`
    ready, `/api/version` served — and refuses every credential with the
    deliberately opaque `Sign-in failed.`, while `/mcp` refuses ChatGPT's live
    token as an unknown-or-disabled *account*. Nothing named the file.
    """
    import logging

    from gateway.app.core.config import settings
    from gateway.app.core.users import unusable_registry_reason
    from gateway.app.main import report_user_registry_state

    absent = tmp_path / "etc" / "users.json"
    monkeypatch.setattr(settings, "user_registry_file", str(absent))

    # Named logger, because `configure_logging()` clears the root handlers at
    # import and takes pytest's capture handler with them.
    with caplog.at_level(logging.ERROR, logger="gateway.app.main"):
        caplog.handler.setLevel(logging.ERROR)
        logging.getLogger("gateway.app.main").addHandler(caplog.handler)
        try:
            report_user_registry_state()
        finally:
            logging.getLogger("gateway.app.main").removeHandler(caplog.handler)

    assert any(str(absent) in record.getMessage() for record in caplog.records), (
        "a gateway that can authenticate nobody started without naming the "
        f"registry it could not read: {[r.getMessage() for r in caplog.records]}"
    )
    assert "CODEX_BRIDGE_USER_REGISTRY_FILE" in " ".join(
        record.getMessage() for record in caplog.records
    ), "the message does not say which setting to fix"

    # And startup is where it is emitted. A complaint nothing calls is the same
    # silence with more code in it.
    import inspect

    from gateway.app.main import startup

    assert "report_user_registry_state()" in inspect.getsource(startup), (
        "the startup handler does not emit the user-registry complaint"
    )

    # A registry that parses and has accounts is silent — a startup that
    # complains every time is a startup nobody reads.
    good = tmp_path / "users.json"
    good.write_text(json.dumps(_registry()), encoding="utf-8")
    assert unusable_registry_reason(str(good)) is None

    # Present but unreadable is the same failure with a different cause, and it
    # must not take the boot down with it (`design-standards.md` §6).
    broken = tmp_path / "broken.json"
    broken.write_text("{not json", encoding="utf-8")
    assert unusable_registry_reason(str(broken)) is not None


async def test_the_published_example_credential_is_refused_even_when_configured(api, monkeypatch) -> None:
    """Defence in depth: the operator who copies the example and forgets.

    `docs/installation.md` says to change the initial password. The operator who
    does not read that line is precisely the operator this protects, so the
    refusal is in `users.authenticate`, not in the prose.
    """
    from pathlib import Path

    from gateway.app.core.config import settings

    example = Path(__file__).resolve().parents[2] / "examples" / "users.json"
    monkeypatch.setattr(settings, "user_registry_file", str(example))

    response = sign_in(api, "admin", "change-me-now")

    assert response.status_code == 401
    events = await audit_events(api.factory, "auth.sign_in_failed")
    assert json.loads(events[-1].payload_json)["reason"] == "published_example_credential"


async def test_sign_in_cannot_mint_a_scope_the_server_allowlist_withholds(api, monkeypatch) -> None:
    """Two issuers, one token table, and only one of them had a ceiling.

    `/oauth/authorize` intersects the account's scopes with
    `CODEX_BRIDGE_OAUTH_DEFAULT_SCOPES` and strips the rest. `/api/v1/auth/sign-in`
    used `sorted(set(user.scopes))` with no intersection — and both write to the
    same `oauth_access_tokens` table that `POST /mcp` authenticates against. A
    mobile token was therefore a live MCP credential carrying scopes the
    deployment's own allowlist exists to withhold: `codexbridge.task.approve`
    gates the approval tool, and `codexbridge.admin` makes `is_admin()` true for
    an account with no admin role, which returns every project's sessions.

    No unusual configuration is needed to reach it — the shipped
    `examples/users.json` grants both of those scopes and neither is in the
    shipped allowlist.
    """
    from gateway.app.core.config import settings

    monkeypatch.setattr(settings, "oauth_default_scopes", "codexbridge.read")
    api.users_file.write_text(
        json.dumps(
            _registry(
                alice_scopes=[
                    "codexbridge.read",
                    "codexbridge.task.cancel",
                    "codexbridge.task.approve",
                    "codexbridge.admin",
                ]
            )
        ),
        encoding="utf-8",
    )

    body = sign_in(api).json()

    assert body["scopes"] == ["codexbridge.read"], (
        "sign-in minted scopes outside the server allowlist: "
        f"{sorted(set(body['scopes']) - settings.oauth_scopes())}"
    )
    async with api.factory() as s:
        item = await store.get_oauth_access_token(s, body["accessToken"])
        assert json.loads(item.scopes_json) == ["codexbridge.read"], (
            "the row `POST /mcp` authenticates against still carries them"
        )


async def test_rotation_cannot_restore_a_scope_the_allowlist_has_since_dropped(api, monkeypatch) -> None:
    """A 30-day grant must not outlive a narrowing of the allowlist."""
    from gateway.app.core.config import settings

    first = sign_in(api).json()
    assert "codexbridge.task.cancel" in first["scopes"]

    monkeypatch.setattr(settings, "oauth_default_scopes", "codexbridge.read")
    rotated = api.post(
        "/api/v1/auth/refresh", json={"refreshToken": first["refreshToken"]}
    ).json()

    assert rotated["scopes"] == ["codexbridge.read"]


async def test_the_audit_trail_names_the_actor_by_id_and_never_by_email(api) -> None:
    """`security-standards.md` §2 lists e-mail among the fields never logged.

    `entity_id` already carries the opaque `user_id`, so the payload's
    `user_email` was a second, personal copy of an identifier the row already
    had — in a table with a retention policy, whose default `database_url` is a
    SQLite file inside this checkout, which sits under `~/Sync`.
    """
    body = sign_in(api).json()
    api.post("/api/v1/auth/refresh", json={"refreshToken": body["refreshToken"]})

    for event_type in ("auth.signed_in", "auth.token_refreshed"):
        events = await audit_events(api.factory, event_type)
        assert events, event_type
        for event in events:
            assert event.entity_id == "alice"
            payload = json.loads(event.payload_json)
            assert "user_email" not in payload, payload
            assert "@" not in event.payload_json, payload


async def test_a_credential_row_names_the_actor_by_id_and_never_by_email(api) -> None:
    """The scope of the test above was the defect, not its assertion.

    `store.issue_auth_grant` argued `security-standards.md` §2 in its own
    docstring — "never … a personal identifier", "a table with a retention
    policy and a default SQLite file inside a synced directory" — and then wrote
    `user_email` into `oauth_access_tokens` and `oauth_refresh_tokens` twenty
    and thirty lines below. The test that backed the argument read
    `audit_events` alone, so the reasoning retired the risk in the next reader's
    mind while the field shipped twice per sign-in, in a table this delivery
    created.

    The whole row is searched for `@` rather than the column checked by name, so
    a differently-named field cannot reintroduce it.
    """
    body = sign_in(api).json()
    api.post("/api/v1/auth/refresh", json={"refreshToken": body["refreshToken"]})

    async with api.factory() as s:
        access = list((await s.execute(select(OAuthAccessTokenModel))).scalars())
        refresh = list((await s.execute(select(OAuthRefreshTokenModel))).scalars())

    assert access and refresh
    for row in access + refresh:
        assert row.user_id == "alice"
        stored = json.dumps(
            {key: value for key, value in row.__dict__.items() if not key.startswith("_")},
            default=str,
        )
        assert "@" not in stored, (
            f"a credential row carries a personal identifier: {stored}"
        )


async def test_audit_rows_past_the_retention_window_are_swept(api) -> None:
    """Rejected sign-ins are the first unauthenticated write into `audit_events`.

    Every other `record_event` call site sits behind authentication. The rate
    limiter bounds the write *rate* (120/minute/bucket), not the table, and
    nothing removed an audit row at all — the startup sweep collected
    `idempotency_records` only. One address could grow the operator's database
    indefinitely with traffic that never authenticated.
    """
    sign_in(api, "alice", OTHER_PASSWORD)
    kept = sign_in(api, "alice", OTHER_PASSWORD)
    assert kept.status_code == 401

    async with api.factory() as s:
        rows = list((await s.execute(select(AuditEventModel))).scalars())
        assert len(rows) == 2
        rows[0].created_at = datetime.now(timezone.utc) - timedelta(days=120)
        await s.commit()

        purged = await store.purge_expired_audit_events(s, retention_days=90)

        assert purged == 1
        remaining = list((await s.execute(select(AuditEventModel))).scalars())
        assert len(remaining) == 1


async def test_the_retention_sweep_does_not_age_out_the_approval_record(api) -> None:
    """The window bounds sign-in spam. It must not decide anything else.

    The sweep was added to stop an unauthenticated caller growing the database
    with rejected sign-ins, and it deleted by timestamp alone — so on the first
    restart of a gateway older than the window it also removed `task.approved`,
    the record of who authorized a sensitive task, along with
    `task.stopped_by_actor`, `task.state_changed` and `task.result`. Eleven
    `record_event` call sites write to this table; two are auth. Whether an
    approval record may be aged out at 90 days is the operator's decision about
    their own compliance, and inheriting it from a spam control is how it gets
    made without them.
    """
    sign_in(api, "alice", OTHER_PASSWORD)

    async with api.factory() as s:
        s.add(
            AuditEventModel(
                entity_type="task",
                entity_id="t1",
                event_type="task.approved",
                payload_json="{}",
                created_at=datetime.now(timezone.utc) - timedelta(days=120),
            )
        )
        await s.commit()

        for row in (await s.execute(select(AuditEventModel))).scalars():
            row.created_at = datetime.now(timezone.utc) - timedelta(days=120)
        await s.commit()

        purged = await store.purge_expired_audit_events(s, retention_days=90)
        survivors = [
            row.event_type for row in (await s.execute(select(AuditEventModel))).scalars()
        ]

    assert purged == 1, "the sweep removed rows outside its own scope"
    assert survivors == ["task.approved"], (
        "the retention window chosen to bound rejected sign-ins deleted the "
        f"record of who approved a sensitive task: {survivors}"
    )


async def test_retention_of_zero_keeps_everything(api) -> None:
    """An operator who exports the table elsewhere opts out explicitly."""
    sign_in(api, "alice", OTHER_PASSWORD)
    async with api.factory() as s:
        row = (await s.execute(select(AuditEventModel))).scalars().first()
        row.created_at = datetime.now(timezone.utc) - timedelta(days=4000)
        await s.commit()
        assert await store.purge_expired_audit_events(s, retention_days=0) == 0
        assert len(list((await s.execute(select(AuditEventModel))).scalars())) == 1


async def test_a_sensitive_action_is_tied_to_the_actor_that_signed_in(api) -> None:
    assert sign_in(api).status_code == 200
    events = await audit_events(api.factory, "auth.signed_in")
    assert len(events) == 1
    assert events[0].entity_id == "alice"
    payload = json.loads(events[0].payload_json)
    assert payload["client_id"] == "codexbridge-mobile"
    assert payload["scopes"] == ["codexbridge.read", "codexbridge.task.cancel"]


async def test_no_credential_is_stored_in_the_clear(api) -> None:
    body = sign_in(api).json()
    async with api.factory() as s:
        access = (await s.execute(select(OAuthAccessTokenModel))).scalars().all()
        refresh = (await s.execute(select(OAuthRefreshTokenModel))).scalars().all()

    assert [row.token_hash for row in access] == [hash_token(body["accessToken"])]
    assert [row.token_hash for row in refresh] == [hash_token(body["refreshToken"])]
    stored = json.dumps([row.__dict__ for row in access + refresh], default=str)
    assert body["accessToken"] not in stored
    assert body["refreshToken"] not in stored


# --------------------------------------------------------------------------
# Refresh
# --------------------------------------------------------------------------


async def test_refresh_returns_a_new_pair(api) -> None:
    first = sign_in(api).json()
    second = api.post(
        "/api/v1/auth/refresh", json={"refreshToken": first["refreshToken"]}
    )
    assert second.status_code == 200
    body = second.json()
    assert body["accessToken"] != first["accessToken"]
    assert body["refreshToken"] != first["refreshToken"]
    assert api.get("/api/v1/sessions", headers=auth(body["accessToken"])).status_code == 200


async def test_rotation_does_not_extend_the_grant(api) -> None:
    """A refresh token that renewed its own deadline would never expire, which
    is the difference between a session and a permanent credential."""
    first = sign_in(api).json()
    rotated = api.post(
        "/api/v1/auth/refresh", json={"refreshToken": first["refreshToken"]}
    ).json()
    assert rotated["refreshTokenExpiresAt"] == first["refreshTokenExpiresAt"]


async def test_replaying_a_spent_refresh_token_kills_the_whole_grant(api) -> None:
    """Replay and theft are indistinguishable here, so it is read as theft."""
    first = sign_in(api).json()
    rotated = api.post(
        "/api/v1/auth/refresh", json={"refreshToken": first["refreshToken"]}
    ).json()

    replay = api.post("/api/v1/auth/refresh", json={"refreshToken": first["refreshToken"]})
    assert replay.status_code == 401

    # Not merely "the old token is dead": everything issued under the grant is.
    assert api.get("/api/v1/sessions", headers=auth(rotated["accessToken"])).status_code == 401
    assert (
        api.post("/api/v1/auth/refresh", json={"refreshToken": rotated["refreshToken"]}).status_code
        == 401
    )


async def test_only_one_rotation_of_a_refresh_token_can_win(api) -> None:
    """Single use has to survive two requests arriving together.

    Read-then-write lets both callers see an unconsumed token and both mint a
    pair, so "single use" would hold only for as long as nobody tested it. This
    drives the store directly because a race is not reproducible through the
    client — what it asserts is that the second write is refused and leaves
    nothing behind.
    """
    body = sign_in(api).json()
    spent = hash_token(body["refreshToken"])

    async def rotate(access: str, refresh: str) -> bool:
        async with api.factory() as s:
            return await store.issue_auth_grant(
                s,
                grant_id="g-race",
                access_token=access,
                refresh_token=refresh,
                client_id="codexbridge-mobile",
                user_id="alice",
                scopes=["codexbridge.read"],
                access_expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
                refresh_expires_at=datetime.now(timezone.utc) + timedelta(days=1),
                event_type="auth.token_refreshed",
                rotated_from_hash=spent,
            )

    assert await rotate("access-winner", "refresh-winner") is True
    assert await rotate("access-loser", "refresh-loser") is False

    async with api.factory() as s:
        assert await store.get_oauth_access_token(s, "access-winner") is not None
        assert await store.get_oauth_access_token(s, "access-loser") is None, (
            "the losing rotation wrote a usable token anyway"
        )


async def test_an_expired_refresh_token_is_refused(api) -> None:
    async with api.factory() as s:
        await store.issue_auth_grant(
            s,
            grant_id="g-expired",
            access_token="access-expired",
            refresh_token="refresh-expired",
            client_id="codexbridge-mobile",
            user_id="alice",
            scopes=["codexbridge.read"],
            access_expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
            refresh_expires_at=datetime.now(timezone.utc) - timedelta(seconds=1),
            event_type="auth.signed_in",
        )

    response = api.post("/api/v1/auth/refresh", json={"refreshToken": "refresh-expired"})
    assert response.status_code == 401
    assert response.json()["code"] == "unauthenticated"


async def test_an_unknown_refresh_token_is_refused(api) -> None:
    assert api.post("/api/v1/auth/refresh", json={"refreshToken": "never-issued"}).status_code == 401


async def test_refresh_narrows_to_what_the_registry_says_now(api) -> None:
    """A 30-day refresh token must not keep minting yesterday's permissions."""
    first = sign_in(api).json()
    task = await make_task(api.factory)
    assert (
        api.post(f"/api/v1/sessions/{task.id}/stop", headers=auth(first["accessToken"])).status_code
        == 428
    ), "alice may stop before the change (428 = the permission passed, If-Match did not)"

    api.users_file.write_text(
        json.dumps(_registry(alice_scopes=["codexbridge.read"])), encoding="utf-8"
    )

    rotated = api.post(
        "/api/v1/auth/refresh", json={"refreshToken": first["refreshToken"]}
    ).json()
    assert rotated["scopes"] == ["codexbridge.read"]
    assert (
        api.post(
            f"/api/v1/sessions/{task.id}/stop", headers=auth(rotated["accessToken"])
        ).status_code
        == 403
    )


async def test_refresh_ends_the_grant_when_the_account_is_disabled(api) -> None:
    """Otherwise disabling an account takes as long as the refresh TTL."""
    first = sign_in(api).json()
    api.users_file.write_text(
        json.dumps(_registry(alice_enabled=False)), encoding="utf-8"
    )

    assert (
        api.post("/api/v1/auth/refresh", json={"refreshToken": first["refreshToken"]}).status_code
        == 401
    )
    async with api.factory() as s:
        assert await store.get_oauth_access_token(s, first["accessToken"]) is None


# --------------------------------------------------------------------------
# Revocation
# --------------------------------------------------------------------------


async def test_revoking_stops_the_access_token_immediately(api) -> None:
    body = sign_in(api).json()
    assert api.get("/api/v1/sessions", headers=auth(body["accessToken"])).status_code == 200

    revoked = api.post("/api/v1/auth/revoke", headers=auth(body["accessToken"]))
    assert revoked.status_code == 200
    assert revoked.json()["revoked"] is True
    assert revoked.json()["accessTokensRevoked"] == 1
    assert revoked.json()["refreshTokensRevoked"] == 1

    assert api.get("/api/v1/sessions", headers=auth(body["accessToken"])).status_code == 401
    assert (
        api.post("/api/v1/auth/refresh", json={"refreshToken": body["refreshToken"]}).status_code
        == 401
    )


async def test_revocation_reaches_the_credential_store_the_mcp_transport_reads(api) -> None:
    """One store, or a revocation honoured by one surface and not the other.

    `store.get_oauth_access_token` is what `POST /mcp` authenticates with. If
    revocation lived in the HTTP layer, a token revoked from the phone would
    keep driving the executor through ChatGPT.
    """
    body = sign_in(api).json()
    async with api.factory() as s:
        assert await store.get_oauth_access_token(s, body["accessToken"]) is not None

    api.post("/api/v1/auth/revoke", headers=auth(body["accessToken"]))

    async with api.factory() as s:
        assert await store.get_oauth_access_token(s, body["accessToken"]) is None


async def test_a_refresh_token_alone_can_sign_out(api) -> None:
    """The usual moment to sign out is after the access token has expired."""
    body = sign_in(api).json()
    response = api.post("/api/v1/auth/revoke", json={"refreshToken": body["refreshToken"]})
    assert response.status_code == 200
    assert api.get("/api/v1/sessions", headers=auth(body["accessToken"])).status_code == 401


async def test_revocation_is_idempotent_and_says_nothing_about_the_token(api) -> None:
    body = sign_in(api).json()
    api.post("/api/v1/auth/revoke", headers=auth(body["accessToken"]))

    again = api.post("/api/v1/auth/revoke", json={"refreshToken": body["refreshToken"]})
    unknown = api.post("/api/v1/auth/revoke", json={"refreshToken": "never-issued"})

    assert again.status_code == unknown.status_code == 200
    assert again.json()["accessTokensRevoked"] == 0
    assert unknown.json() | {"revokedAt": None} == again.json() | {"revokedAt": None}, (
        "an unknown credential and an already-revoked one must be indistinguishable"
    )


async def test_signing_out_twice_with_only_an_access_token_is_still_a_sign_out(api) -> None:
    """The second call is the one a flaky mobile connection actually makes.

    A client holding no refresh token signs out, the connection drops, the
    client retries the identical request. By then the token is revoked, so the
    store returns nothing — and answering `401` there turns a *completed*
    sign-out into an authentication failure for every client with the usual
    global 401 interceptor. The contract says the opposite in two places
    (`revoked` is "always true"; an already-revoked credential is answered 200
    "like any other"), and the OpenAPI gate compares route inventories only, so
    nothing caught the disagreement.
    """
    body = sign_in(api).json()
    headers = auth(body["accessToken"])

    first = api.post("/api/v1/auth/revoke", headers=headers)
    second = api.post("/api/v1/auth/revoke", headers=headers)

    assert first.status_code == 200
    assert second.status_code == 200, f"the second identical sign-out was refused: {second.json()}"
    assert second.json()["revoked"] is True
    assert second.json()["accessTokensRevoked"] == 0


async def _artifact_in_p1(factory):
    """One artifact row, no bytes on disk.

    The download endpoint checks the credential before it looks for the file,
    so a row with nothing behind it separates the two answers this test needs:
    `404` means "the token was accepted and the content is missing", `401`
    means "the token is gone". No file is written, and nothing outside the
    database is touched.
    """
    async with factory() as session:
        return await store.create_artifact(
            session,
            project_id="p1",
            artifact_type="report",
            name="build-report.txt",
            size_bytes=3,
            sha256="ab" * 32,
            origin="ci",
            storage_path="p1/build-report.txt",
            content_type="text/plain",
        )


async def test_signing_out_kills_a_download_token_minted_before_it(api) -> None:
    """Sign-out has to close every credential, not the two it was written for.

    An artifact download token (issue #11) is a third credential this actor
    holds, and the first cut of #11 left it alive through a sign-out: the
    session died and the minted token went on streaming an APK for the rest of
    its TTL — up to an hour at the configured ceiling. Two council lenses
    reproduced it independently (`200`, full body, after a `200` from
    `/auth/revoke`), and it is verbatim the failure this endpoint's own
    docstring says it exists to prevent.

    Revoked by actor rather than by grant: `artifact_download_tokens` carries
    no `grant_id`, and revoking too little is the failure above while revoking
    too much costs the holder one extra tap on Download.
    """
    artifact = await _artifact_in_p1(api.factory)
    body = sign_in(api).json()
    headers = auth(body["accessToken"])

    minted = api.post(f"/api/v1/artifacts/{artifact.id}/download-token", headers=headers)
    assert minted.status_code == 201
    download_headers = {"Authorization": f"Bearer {minted.json()['token']}"}

    accepted = api.get(f"/api/v1/artifacts/{artifact.id}/download", headers=download_headers)
    assert accepted.status_code == 404, "precondition: the credential is live and the bytes are not"

    revoked = api.post("/api/v1/auth/revoke", headers=headers)
    assert revoked.status_code == 200

    assert api.get("/api/v1/artifacts", headers=headers).status_code == 401
    after = api.get(f"/api/v1/artifacts/{artifact.id}/download", headers=download_headers)
    assert after.status_code == 401, "the download token outlived the session that minted it"


async def test_revoking_by_refresh_token_also_kills_the_download_tokens(api) -> None:
    """The other revocation door closes the same set.

    `/auth/revoke` reaches `revoke_auth_grant` when a refresh token is
    presented and `revoke_access_token` when only a bearer is. Which door the
    caller used must not decide what stays alive (`design-standards.md` §3) —
    the guard lives in one helper both call for exactly that reason.
    """
    artifact = await _artifact_in_p1(api.factory)
    body = sign_in(api).json()
    headers = auth(body["accessToken"])

    minted = api.post(f"/api/v1/artifacts/{artifact.id}/download-token", headers=headers)
    download_headers = {"Authorization": f"Bearer {minted.json()['token']}"}
    assert api.get(f"/api/v1/artifacts/{artifact.id}/download", headers=download_headers).status_code == 404

    assert api.post("/api/v1/auth/revoke", json={"refreshToken": body["refreshToken"]}).status_code == 200

    after = api.get(f"/api/v1/artifacts/{artifact.id}/download", headers=download_headers)
    assert after.status_code == 401


async def test_a_replayed_dead_refresh_token_cannot_kill_a_live_grants_download(api) -> None:
    """Revocation stops at the grant it names — the round-1 fix reached past it.

    `/auth/revoke` deliberately acts on a refresh token it has already
    classified as consumed, revoked or expired (see the endpoint's docstring:
    fail-closed, and the abuse is "one forced re-authentication of one grant").
    That bound held because both `UPDATE`s are scoped to `grant_id` and are
    no-ops on a dead token.

    The first cut of the download-token revocation was scoped to `user_id`
    alone, which made it the one statement a replay still hit: an attacker
    holding a long-dead refresh token — from a phone backup, an old client log
    — could destroy the download credential of a *live* grant, unauthenticated
    and repeatably, while the response reported that nothing was revoked. Found
    by a second council round; the fix records `grant_id` on the download token
    and revokes inside it.
    """
    artifact = await _artifact_in_p1(api.factory)

    dead = sign_in(api).json()
    api.post("/api/v1/auth/revoke", headers=auth(dead["accessToken"]))

    live = sign_in(api).json()
    live_headers = auth(live["accessToken"])
    minted = api.post(f"/api/v1/artifacts/{artifact.id}/download-token", headers=live_headers)
    download_headers = {"Authorization": f"Bearer {minted.json()['token']}"}
    assert api.get(f"/api/v1/artifacts/{artifact.id}/download", headers=download_headers).status_code == 404

    for _ in range(3):
        replay = api.post("/api/v1/auth/revoke", json={"refreshToken": dead["refreshToken"]})
        assert replay.status_code == 200
        assert replay.json()["accessTokensRevoked"] == 0

    assert api.get("/api/v1/artifacts", headers=live_headers).status_code == 200
    survived = api.get(f"/api/v1/artifacts/{artifact.id}/download", headers=download_headers)
    assert survived.status_code == 404, (
        "an unauthenticated replay of a dead refresh token destroyed a live grant's "
        "download credential"
    )


async def test_a_grantless_sign_out_does_not_abort_the_phones_download(api) -> None:
    """Signing out of ChatGPT must not kill an APK transfer on the phone.

    The browser OAuth flow issues access tokens that belong to no grant;
    revoking one lands in `store.revoke_access_token`. Scoped by actor alone,
    that deleted the phone's download tokens too — the operator's 40 MB
    transfer aborting at 90% because they closed a browser tab, with the phone
    session still perfectly alive. `grant_id=None` is a value here, addressing
    exactly the grantless session's own download tokens.
    """
    from datetime import timedelta

    artifact = await _artifact_in_p1(api.factory)

    phone = sign_in(api).json()
    phone_headers = auth(phone["accessToken"])
    minted = api.post(f"/api/v1/artifacts/{artifact.id}/download-token", headers=phone_headers)
    download_headers = {"Authorization": f"Bearer {minted.json()['token']}"}

    async with api.factory() as session:
        await store.create_oauth_access_token(
            session,
            token="chatgpt-browser-token",
            client_id="chatgpt",
            user_id="alice",
            scopes=["codexbridge.read"],
            expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
        )

    signed_out = api.post("/api/v1/auth/revoke", headers=auth("chatgpt-browser-token"))
    assert signed_out.status_code == 200
    assert signed_out.json()["accessTokensRevoked"] == 1

    survived = api.get(f"/api/v1/artifacts/{artifact.id}/download", headers=download_headers)
    assert survived.status_code == 404, (
        "a grantless (browser OAuth) sign-out destroyed a download token minted by "
        "the phone's own grant"
    )


async def test_an_access_token_that_was_never_issued_signs_out_quietly(api) -> None:
    """Same rule, reached from the other side: incurious about the credential."""
    response = api.post("/api/v1/auth/revoke", headers=auth("never-issued"))
    assert response.status_code == 200
    assert response.json()["revoked"] is True


async def test_a_consumed_refresh_token_still_ends_its_own_grant(api) -> None:
    """Pinned on purpose — this behaviour is a decision, not an accident.

    `/revoke` does not consult `inspect_refresh_token`'s verdict: a consumed,
    revoked or expired refresh token still revokes the grant it belongs to. That
    is the fail-closed direction (`design-standards.md` §6) — refusing would let
    a client's sign-out report success while the session stayed alive — and
    `/refresh` already reads a replayed token as theft, so reading the same
    token as harmless here would make the two endpoints disagree about one
    credential.

    The residual risk is written down in `docs/security.md`: whoever holds any
    refresh token ever issued under a live grant can force one
    re-authentication, unauthenticated. If that trade is ever revisited, this
    test is the thing that must change with it.
    """
    first = sign_in(api).json()
    rotated = api.post(
        "/api/v1/auth/refresh", json={"refreshToken": first["refreshToken"]}
    ).json()

    spent = api.post("/api/v1/auth/revoke", json={"refreshToken": first["refreshToken"]})

    assert spent.status_code == 200
    assert spent.json()["accessTokensRevoked"] >= 1
    assert api.get("/api/v1/auth/me", headers=auth(rotated["accessToken"])).status_code == 401


async def test_revoking_nothing_is_refused(api) -> None:
    response = api.post("/api/v1/auth/revoke")
    assert response.status_code == 401
    assert response.json()["code"] == "unauthenticated"


async def test_revocation_is_recorded_against_the_actor(api) -> None:
    body = sign_in(api).json()
    api.post("/api/v1/auth/revoke", headers=auth(body["accessToken"]))

    events = await audit_events(api.factory, "auth.credentials_revoked")
    assert [event.entity_id for event in events] == ["alice"]
    assert json.loads(events[0].payload_json)["reason"] == "signed_out"


async def test_a_no_op_revoke_writes_no_audit_row(api) -> None:
    """A retry the endpoint blesses must not add a `0/0` audit row.

    `/revoke` is idempotent and its contract invites the retry a flaky mobile
    connection makes. A refresh token whose grant is already revoked is still
    *found* by `inspect_refresh_token` (it returns the row, revoked), so the
    handler calls `revoke_auth_grant` again — revoking nothing. Recording
    `auth.credentials_revoked` on that no-op buries the real revocations under
    `0/0` rows, the more so now that the retention sweep no longer ages them out.
    """
    body = sign_in(api).json()
    first = api.post("/api/v1/auth/revoke", json={"refreshToken": body["refreshToken"]})
    assert first.status_code == 200 and first.json()["accessTokensRevoked"] >= 1

    # The same, now-revoked refresh token again: the grant is found but already
    # revoked, so this call revokes nothing.
    second = api.post("/api/v1/auth/revoke", json={"refreshToken": body["refreshToken"]})
    assert second.status_code == 200 and second.json()["accessTokensRevoked"] == 0

    events = await audit_events(api.factory, "auth.credentials_revoked")
    assert len(events) == 1, (
        f"a no-op revoke wrote an audit row: {[json.loads(e.payload_json) for e in events]}"
    )


async def test_a_last_minute_rotation_does_not_outlive_the_grant_deadline(api) -> None:
    """A rotation near the grant's end must not mint an access token past it.

    The grant has an absolute lifetime (`refreshTokenExpiresAt`, carried forward
    unchanged). Minting `access_expires_at = now + access_TTL` on the last legal
    rotation put the access token's expiry *after* the grant deadline, and
    `GET /auth/me` answered 200 with it past the deadline the grant is documented
    to enforce. The access expiry is capped at the grant deadline.
    """
    deadline = datetime.now(timezone.utc) + timedelta(seconds=30)
    async with api.factory() as s:
        await store.issue_auth_grant(
            s,
            grant_id="g-deadline",
            access_token="old-access",
            refresh_token="old-refresh",
            client_id="codexbridge-mobile",
            user_id="alice",
            scopes=["codexbridge.read"],
            access_expires_at=datetime.now(timezone.utc) + timedelta(seconds=30),
            refresh_expires_at=deadline,
            event_type="auth.signed_in",
        )

    rotated = api.post("/api/v1/auth/refresh", json={"refreshToken": "old-refresh"})
    assert rotated.status_code == 200
    body = rotated.json()

    access_exp = datetime.fromisoformat(body["accessTokenExpiresAt"].replace("Z", "+00:00"))
    refresh_exp = datetime.fromisoformat(body["refreshTokenExpiresAt"].replace("Z", "+00:00"))
    assert access_exp <= refresh_exp, (
        f"the rotated access token expires at {access_exp}, past the grant deadline {refresh_exp}"
    )
    # expiresIn is capped too, not left at the full TTL — it is the field the
    # contract tells the client to schedule its refresh from. Lower bound as well
    # as upper: an over-truncation that returned an already-expired access token
    # (the tz-misread the normalization guards against) would satisfy `<= 30` too.
    assert 0 < body["expiresIn"] <= 30, f"expiresIn out of range: {body['expiresIn']}"


async def test_a_rotation_far_from_the_deadline_still_gets_the_full_access_ttl(api) -> None:
    """The deadline cap must not shorten a normal rotation — the fix's floor.

    Capping `access_expires_at` at the grant deadline is right only when the
    deadline is nearer than the TTL. A rotation 30 days out must still mint an
    access token good for the full access TTL, not the whole grant; dropping the
    `min` and always using the deadline would hand out a 30-day access token and
    this is what catches it.
    """
    from gateway.app.core.config import settings

    ttl = settings.oauth_access_token_ttl_seconds
    async with api.factory() as s:
        await store.issue_auth_grant(
            s,
            grant_id="g-far",
            access_token="far-access",
            refresh_token="far-refresh",
            client_id="codexbridge-mobile",
            user_id="alice",
            scopes=["codexbridge.read"],
            access_expires_at=datetime.now(timezone.utc) + timedelta(seconds=ttl),
            refresh_expires_at=datetime.now(timezone.utc) + timedelta(days=30),
            event_type="auth.signed_in",
        )

    body = api.post("/api/v1/auth/refresh", json={"refreshToken": "far-refresh"}).json()
    now = datetime.now(timezone.utc)
    access_exp = datetime.fromisoformat(body["accessTokenExpiresAt"].replace("Z", "+00:00"))
    assert access_exp - now <= timedelta(seconds=ttl + 5), (
        f"a far-deadline rotation minted an access token good for {access_exp - now}, "
        f"past the {ttl}s TTL"
    )
    assert body["expiresIn"] <= ttl + 5


async def test_the_retention_sweep_keeps_a_refresh_reuse_record(api) -> None:
    """The spam sweep must not age out the record that a token was replayed.

    `auth.credentials_revoked{reason:"refresh_token_reuse"}` is the one durable
    artefact saying a stolen refresh token was replayed on a grant. Scoping the
    retention window to `entity_type == "auth"` deleted it along with rejected
    sign-ins; it is scoped to `AUTH_SWEEPABLE_EVENT_TYPES` (the high-volume
    `auth.sign_in_failed`, `auth.token_refreshed`, `auth.signed_in`), which
    excludes `auth.credentials_revoked`, so the theft record survives while a
    rejected sign-in of the same age is still swept.
    """
    async with api.factory() as s:
        old = datetime.now(timezone.utc) - timedelta(days=120)
        s.add(
            AuditEventModel(
                entity_type="auth",
                entity_id="alice",
                event_type="auth.credentials_revoked",
                payload_json=json.dumps({"grant_id": "g1", "reason": "refresh_token_reuse"}),
                created_at=old,
            )
        )
        s.add(
            AuditEventModel(
                entity_type="auth",
                entity_id="alice",
                event_type="auth.sign_in_failed",
                payload_json=json.dumps({"reason": "bad_password"}),
                created_at=old,
            )
        )
        await s.commit()

        purged = await store.purge_expired_audit_events(s, retention_days=90)
        survivors = sorted(
            row.event_type for row in (await s.execute(select(AuditEventModel))).scalars()
        )

    assert purged == 1, "the sweep took something other than the rejected sign-in"
    assert survivors == ["auth.credentials_revoked"], (
        f"the theft record was aged out by a spam control: survivors={survivors}"
    )


# --------------------------------------------------------------------------
# Who am I, and what may I do
# --------------------------------------------------------------------------


async def test_me_requires_a_token(api) -> None:
    response = api.get("/api/v1/auth/me")
    assert response.status_code == 401
    assert response.json()["code"] == "unauthenticated"
    assert "Bearer" in response.headers.get("WWW-Authenticate", "")


async def test_me_refuses_an_expired_token(api) -> None:
    async with api.factory() as s:
        await store.create_oauth_access_token(
            s,
            token="stale",
            client_id="c",
            user_id="alice",
            scopes=["codexbridge.read"],
            expires_at=datetime.now(timezone.utc) - timedelta(seconds=1),
        )
    assert api.get("/api/v1/auth/me", headers=auth("stale")).status_code == 401


async def test_every_401_on_this_surface_is_the_same_401(api) -> None:
    """Four places claimed this and it was not true.

    An absent header answered "This endpoint requires a bearer token." and an
    invented token answered "The bearer token is not valid." — under a docstring
    saying every one of them says the same thing whatever went wrong. The
    property that matters (real-but-dead is indistinguishable from never-real)
    did hold, so nothing leaked; what failed is that the next reader who checks
    the claim reads the docstring and stops there. That is exactly how the
    2026-07-16 anchor got its false coverage.
    """
    body = sign_in(api).json()
    api.post("/api/v1/auth/revoke", headers=auth(body["accessToken"]))

    responses = {
        "no header": api.get("/api/v1/auth/me"),
        "never issued": api.get("/api/v1/auth/me", headers=auth("never-issued")),
        "revoked": api.get("/api/v1/auth/me", headers=auth(body["accessToken"])),
        "not a bearer scheme": api.get(
            "/api/v1/auth/me", headers={"Authorization": "Basic sdfsdf"}
        ),
    }

    bodies = {
        label: response.json() | {"requestId": None} for label, response in responses.items()
    }
    assert all(response.status_code == 401 for response in responses.values()), {
        label: response.status_code for label, response in responses.items()
    }
    assert len({json.dumps(body, sort_keys=True) for body in bodies.values()}) == 1, bodies


async def test_a_disabled_account_is_asked_to_sign_in_again_not_told_it_may_not(api) -> None:
    """401, not 403 — and `/api/v1/auth/me` declares no 403 at all.

    The operator disables the account (or removes it) while a live access token
    is still in the client's hands. A `403 permission_denied` told that client
    "you are authenticated and not permitted", which is the branch documented as
    *not* meaning "sign in again", so the client showed a permissions error and
    kept the dead session. It also made `/api/v1/auth/me` — the endpoint whose
    whole purpose is reporting authorization — answer a status its contract does
    not declare, and the OpenAPI gate compares route inventories only, so nothing
    caught it.

    The credential is dead, and the only recovery is to present another one.
    That is what 401 means. It also makes the rule the rest of this surface is
    documented by true: on `/api/v1`, 403 comes from `require_action` and from
    nowhere else.
    """
    body = sign_in(api).json()
    headers = auth(body["accessToken"])
    assert api.get("/api/v1/auth/me", headers=headers).status_code == 200

    api.users_file.write_text(json.dumps(_registry(alice_enabled=False)), encoding="utf-8")

    for path in ("/api/v1/auth/me", "/api/v1/sessions"):
        response = api.get(path, headers=headers)
        assert response.status_code == 401, f"{path} answered {response.status_code}"
        assert response.json()["code"] == "unauthenticated"
        assert "Bearer" in response.headers.get("WWW-Authenticate", "")


async def test_me_reports_the_actor_and_its_projects(api) -> None:
    body = sign_in(api).json()
    me = api.get("/api/v1/auth/me", headers=auth(body["accessToken"]))
    assert me.status_code == 200
    assert me.headers["Cache-Control"] == "no-store"

    reported = me.json()
    assert reported["actor"] == {
        "kind": "user",
        "id": "alice",
        "email": "alice@example.com",
    }
    assert reported["projects"] == {"all": False, "ids": ["p1"]}
    assert reported["scopes"] == ["codexbridge.read", "codexbridge.task.cancel"]


async def test_me_marks_an_admin_as_seeing_every_project(api) -> None:
    body = sign_in(api, "admin").json()
    reported = api.get("/api/v1/auth/me", headers=auth(body["accessToken"])).json()
    assert reported["projects"]["all"] is True
    assert all(entry["allowed"] for entry in reported["permissions"])


async def test_me_separates_read_operational_and_administrative(api) -> None:
    """The three classes the issue asks for, reported per action."""
    body = sign_in(api, "reader").json()
    reported = api.get("/api/v1/auth/me", headers=auth(body["accessToken"])).json()
    by_action = {entry["action"]: entry for entry in reported["permissions"]}

    assert by_action["sessions.read"]["category"] == "read"
    assert by_action["sessions.read"]["allowed"] is True
    assert by_action["sessions.stop"]["category"] == "operational"
    assert by_action["sessions.stop"]["allowed"] is False
    assert by_action["sessions.pause"]["category"] == "operational"
    assert by_action["sessions.pause"]["allowed"] is False
    assert by_action["sessions.resume"]["category"] == "operational"
    assert by_action["sessions.resume"]["allowed"] is False
    assert by_action["sessions.restart"]["category"] == "operational"
    assert by_action["sessions.restart"]["allowed"] is False
    assert by_action["sessions.readAllProjects"]["category"] == "administrative"
    assert by_action["sessions.readAllProjects"]["allowed"] is False


# One request per action, so the report can be checked against the thing it
# describes.
ENDPOINT_FOR_ACTION = {
    "nodes.read": ("GET", "/api/v1/nodes"),
    # Neither test principal below carries `codexbridge.admin`, so both are
    # refused by `require_action` itself before the body (invite) or the path
    # id (revoke, which does not resolve to a real node) is ever looked at —
    # same reasoning as `decisions.decide` below.
    "nodes.invite": ("POST", "/api/v1/nodes/invite"),
    "nodes.revoke": ("POST", "/api/v1/nodes/{id}/revoke"),
    # `{id}` here is a `TaskModel.id` (see `make_task` below), not a real node
    # id -- fine for this parity check, whose only claim is about the 403
    # boundary: `require_action` runs before the route body ever looks a
    # node/resource up, so a caller lacking the scope gets 403 regardless of
    # what {id} resolves to, and one holding it gets whatever the (possibly
    # 404) lookup produces -- never 403 either way. Same reasoning the
    # `epics`/`issues` entries above already document.
    "nodes.discoveries.read": ("GET", "/api/v1/nodes/{id}/discovered-resources"),
    "nodes.discoveries.decide": ("POST", "/api/v1/discovered-resources/{id}/deny"),
    # `revoke`, not `authorize`, for the same reason `nodes.discoveries.decide`
    # above picks `deny` over `adopt`: `revoke` carries no request body, so a
    # caller lacking the scope is refused by `require_action` before any body
    # would even need to validate, keeping this parity check about the 403
    # boundary alone. `{id}` fills both `{nodeId}` and `{projectId}` — neither
    # resolves to a real row, which is fine here for the same reason the
    # `{id}` comment above gives: this only asserts the 403/not-403 boundary.
    "nodes.authorizations.manage": ("POST", "/api/v1/nodes/{id}/projects/{id}/revoke"),
    "sessions.read": ("GET", "/api/v1/sessions"),
    "sessions.readLogs": ("GET", "/api/v1/sessions/{id}/logs"),
    "sessions.explainError": ("POST", "/api/v1/sessions/{id}/explain-error"),
    "projects.read": ("GET", "/api/v1/projects"),
    "sessions.stop": ("POST", "/api/v1/sessions/{id}/stop"),
    "sessions.pause": ("POST", "/api/v1/sessions/{id}/pause"),
    "sessions.resume": ("POST", "/api/v1/sessions/{id}/resume"),
    "sessions.restart": ("POST", "/api/v1/sessions/{id}/restart"),
    "decisions.read": ("GET", "/api/v1/decisions"),
    # Neither test principal below carries `codexbridge.task.approve`, so this
    # is refused by `require_action` itself — the same reason `sessions.stop`
    # above is exercised against a task that is not necessarily stoppable.
    "decisions.decide": ("POST", "/api/v1/decisions/{id}/approve"),
    "missions.read": ("GET", "/api/v1/missions"),
    "missions.readTimeline": ("GET", "/api/v1/missions/{id}/timeline"),
    "missions.explain": ("POST", "/api/v1/missions/{id}/explain"),
    "missions.cancel": ("POST", "/api/v1/missions/{id}/cancel"),
    # Issue #68. No body sent, on purpose, same reasoning as
    # `notifications.manage` below: `require_action` is a sub-dependency and
    # runs before the request body is validated, so a caller lacking the
    # scope gets the 403 this loop looks for regardless of the missing
    # `projectId`/`objective`; one that has it gets 422 for the missing body,
    # a non-403, which is exactly what the loop asserts either way.
    "missions.create": ("POST", "/api/v1/missions"),
    # These six don't need a task/epic/issue to exist behind {id} — a
    # permission dependency runs before the route body ever looks the id up,
    # so a 403 for a caller lacking the scope, or a non-403 for one that has
    # it, is reliable regardless of what {id} resolves to.
    "epics.read": ("GET", "/api/v1/projects/p1/epics"),
    "issues.read": ("GET", "/api/v1/projects/p1/issues"),
    "issues.create": ("POST", "/api/v1/issues"),
    "issues.update": ("PATCH", "/api/v1/issues/{id}"),
    "epics.create": ("POST", "/api/v1/epics"),
    "epics.update": ("PATCH", "/api/v1/epics/{id}"),
    "epics.linkIssue": ("POST", "/api/v1/epics/e1/issues/{id}"),
    "conversations.read": ("GET", "/api/v1/conversations"),
    "conversations.create": ("POST", "/api/v1/conversations"),
    "conversations.postMessage": ("POST", "/api/v1/conversations/{id}/messages"),
    # Issue #11. Same reasoning as the six above: `require_action` runs before
    # the handler resolves `{id}`, so a 403 for a caller lacking the scope — or
    # a non-403 for one that has it — is reliable even though no artifact row
    # exists behind that id (nothing in this build produces one).
    "artifacts.read": ("GET", "/api/v1/artifacts"),
    "artifacts.download": ("POST", "/api/v1/artifacts/{id}/download-token"),
    # The backlog endpoint, never `/events/stream`: this loop issues a plain
    # request and reads the status, and an SSE body does not end until the
    # server closes it, so pointing the parity check at the stream would hang
    # the suite for `event_stream_max_duration_seconds`. Both are guarded by
    # the same `events.read` action, which is what is being checked here.
    "events.read": ("GET", "/api/v1/events"),
    "notifications.read": ("GET", "/api/v1/notifications/preferences"),
    # No body sent, on purpose. `require_action` is a sub-dependency and runs
    # before the request body is validated, so a caller lacking the scope gets
    # the 403 this loop looks for; one that has it gets a 422 for the missing
    # body, which is a non-403 and is exactly what the loop asserts.
    "notifications.manage": ("PUT", "/api/v1/notifications/preferences"),
}

# Actions with no endpoint of their own, each naming the test that covers it
# instead. Named one at a time on purpose: this used to be a blanket exemption
# for the whole `ADMINISTRATIVE` category, written into the very guard whose job
# is to catch an action shipping unchecked — so the next administrative action
# would have shipped with no parity assertion at all and a green suite, which is
# the state the guard's own docstring says cannot happen.
COVERED_ELSEWHERE = {
    # Not an endpoint: it is the admin widening of the two read endpoints.
    "sessions.readAllProjects": "test_the_administrative_action_describes_what_the_list_endpoint_does",
    "missions.readAllProjects": "test_the_administrative_action_describes_what_the_missions_list_endpoint_does",
    # `epics.publish` (issue #78, WK-20260902-issue-materialize) has no REST
    # endpoint of its own -- it is `publish_epic_to_repo`, MCP-only, the same
    # way every other epic/issue tool is exposed over `/mcp` in addition to
    # (never instead of) REST. `test_module` here is a placeholder name this
    # module's own `test_each_exemption_names_a_test_that_exists` will refuse
    # unless the real test module below actually defines it.
    "epics.publish": "test_epics_publish_is_exercised_over_mcp",
}


def test_epics_publish_is_exercised_over_mcp() -> None:
    """Not a real assertion -- a pointer so `COVERED_ELSEWHERE`'s own guard

    (`test_each_exemption_names_a_test_that_exists`) has a callable to find.
    The actual coverage for `epics.publish` is
    `tests/integration/test_mcp_epics_issues.py::
    test_publish_epic_to_repo_dispatches_to_a_connected_executor` and its
    sibling negative-control tests in that file -- MCP-only actions cannot be
    driven through `ENDPOINT_FOR_ACTION`'s REST `TestClient`, so they are
    proven in the MCP tool's own test module instead, the same way `epics.
    read`/`epics.create` are proven twice: once here over REST, once in
    `test_mcp_epics_issues.py` over MCP -- this action only has the second.
    """


def test_every_catalogued_action_is_exercised_below() -> None:
    """A new action must extend the table, or it ships unchecked."""
    unexercised = {
        action.name
        for action in permissions.CATALOGUE
        if action.name not in ENDPOINT_FOR_ACTION and action.name not in COVERED_ELSEWHERE
    }
    assert not unexercised, f"catalogued but never called: {sorted(unexercised)}"


def test_each_exemption_names_a_test_that_exists() -> None:
    """An exemption pointing at nothing is an exemption with no coverage behind it."""
    module = globals()
    for action, test_name in COVERED_ELSEWHERE.items():
        assert callable(module.get(test_name)), (
            f"{action} is exempted from the parity check by {test_name}, "
            "which is not a test in this module"
        )


def test_the_guard_flags_a_new_administrative_action(monkeypatch) -> None:
    """The guard is only worth having if it fires — so fire it.

    Evaluated against a catalogue extended with an administrative action that
    has neither an endpoint nor an exemption. Under the category-wide exemption
    this passed silently, which is the defect.
    """
    invented = permissions.Action(
        name="projects.deleteAny",
        category=permissions.ADMINISTRATIVE,
        scope=permissions.ADMIN_SCOPE,
        summary="Invented for this test. Never added to the catalogue.",
    )
    monkeypatch.setattr(permissions, "CATALOGUE", permissions.CATALOGUE + (invented,))

    with pytest.raises(AssertionError, match="projects.deleteAny"):
        test_every_catalogued_action_is_exercised_below()


@pytest.mark.parametrize("who", ["alice", "reader"])
async def test_the_report_and_the_endpoints_agree(api, who: str) -> None:
    """The claim the whole endpoint exists for.

    A client decides whether to *show* a control from `permissions`. If the
    report and the guard disagree, the client either hides something the
    operator may do or offers something that answers 403 — and the second one
    is how an operator learns not to trust the app.
    """
    body = sign_in(api, who).json()
    headers = auth(body["accessToken"])
    reported = api.get("/api/v1/auth/me", headers=headers).json()["permissions"]
    allowed = {entry["action"]: entry["allowed"] for entry in reported}

    task = await make_task(api.factory)
    for action, (method, template) in ENDPOINT_FOR_ACTION.items():
        path = template.format(id=task.id)
        response = api.request(method, path, headers=headers)
        forbidden = response.status_code == 403
        assert forbidden is not allowed[action], (
            f"{who}: /auth/me says allowed={allowed[action]} for {action} but "
            f"{method} {path} answered {response.status_code}"
        )


async def test_the_administrative_action_describes_what_the_list_endpoint_does(api) -> None:
    """`sessions.readAllProjects` is administrative because it crosses projects."""
    await make_task(api.factory, "p1")

    alice = sign_in(api).json()
    admin = sign_in(api, "admin").json()

    def reads_all(token: str) -> bool:
        reported = api.get("/api/v1/auth/me", headers=auth(token)).json()["permissions"]
        return next(
            entry["allowed"] for entry in reported if entry["action"] == "sessions.readAllProjects"
        )

    assert reads_all(alice["accessToken"]) is False
    assert reads_all(admin["accessToken"]) is True

    alice_projects = api.get("/api/v1/auth/me", headers=auth(alice["accessToken"])).json()["projects"]
    admin_projects = api.get("/api/v1/auth/me", headers=auth(admin["accessToken"])).json()["projects"]
    assert alice_projects["all"] is False and alice_projects["ids"] == ["p1"]
    assert admin_projects["all"] is True


async def test_the_administrative_action_describes_what_the_missions_list_endpoint_does(api) -> None:
    """`missions.readAllProjects` mirrors `sessions.readAllProjects` — same widening."""
    await make_task(api.factory, "p1")

    alice = sign_in(api).json()
    admin = sign_in(api, "admin").json()

    def reads_all(token: str) -> bool:
        reported = api.get("/api/v1/auth/me", headers=auth(token)).json()["permissions"]
        return next(
            entry["allowed"] for entry in reported if entry["action"] == "missions.readAllProjects"
        )

    assert reads_all(alice["accessToken"]) is False
    assert reads_all(admin["accessToken"]) is True
