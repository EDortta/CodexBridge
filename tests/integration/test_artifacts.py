"""Artifacts, Android build metadata and the download flow — issue #11.

Weighted towards the four acceptance criteria the issue names: project-scoped
access, a short-lived download authorization that never exposes a server
filesystem path, checksums and signing metadata available *before* the
download, and a typed answer for every missing / expired / unauthorized case.

## These fixtures create artifacts at the store layer, on purpose

**Nothing in this build produces an artifact.** There is no ingestion path, no
upload endpoint and no executor message that writes an `artifacts` row; the
catalogue endpoints exist and the producer is a future issue
(`gateway/app/services/artifact_types.py` says so in its own module docstring).
So every row below is created by calling `store.create_artifact` directly and
writing the bytes into the artifacts root by hand. That is an honest statement
of what is under test — the *serving* half of the feature — and not a
convenience: there is no producer to drive.

What that means for confidence: these tests exercise the API, the
authorization, the confinement rule and the download lifecycle end to end over
a real database and a real filesystem. They do not exercise how an artifact
comes to exist, because nothing does yet.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from gateway.app.api.routes import artifacts as artifacts_routes
from gateway.app.api.setup import install_api_conventions
from gateway.app.db.base import Base
from gateway.app.db.session import get_session
from gateway.app.services import store
from gateway.app.services.artifact_storage import (
    ArtifactContentMissing,
    parse_range_header,
    resolve_artifact_file,
    validate_storage_path,
)
from gateway.app.services.artifact_types import ArtifactError
from shared.protocol import ExecutorRegistration, ProjectRegistration, TaskMode


ALICE_TOKEN = "token-alice"    # p1 only
OUTSIDER_TOKEN = "token-bob"   # p2 only
ADMIN_TOKEN = "token-admin"    # every project

APK_CONTENT_TYPE = "application/vnd.android.package-archive"

FINGERPRINT = ":".join(["AB"] * 32)


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
                        "user_id": "bob", "email": "bob@example.com", "password_hash": "x",
                        "roles": [], "allowed_projects": ["p2"],
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
def artifacts_root(tmp_path, monkeypatch):
    """The one directory artifact bytes may be read from, for this test run.

    Pointed at a temporary directory rather than at the checkout's `data/`
    default: these tests write files, and a test that writes into the
    repository is a test that leaves the repository dirty.
    """
    from gateway.app.core.config import settings

    root = tmp_path / "artifacts"
    root.mkdir()
    monkeypatch.setattr(settings, "artifacts_root", str(root))
    return root


@pytest.fixture
async def api(users_file, artifacts_root, monkeypatch):
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
            (ALICE_TOKEN, "alice", ["codexbridge.read"]),
            (OUTSIDER_TOKEN, "bob", ["codexbridge.read"]),
            (ADMIN_TOKEN, "admin", ["codexbridge.admin"]),
        ):
            await store.create_oauth_access_token(
                seed, token=token, client_id="c", user_id=user_id, scopes=scopes, expires_at=future
            )

    app = FastAPI(openapi_url=None, docs_url=None, redoc_url=None)
    install_api_conventions(app)
    app.include_router(artifacts_routes.router)

    async def override():
        async with factory() as s:
            yield s

    app.dependency_overrides[get_session] = override

    client = TestClient(app, raise_server_exceptions=False)
    client.factory = factory  # type: ignore[attr-defined]
    client.artifacts_root = artifacts_root  # type: ignore[attr-defined]
    yield client
    await engine.dispose()


def auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def android_metadata(**overrides) -> dict:
    metadata = {
        "package_name": "com.example.codexbridge",
        "version_name": "1.2.3",
        "version_code": 42,
        "environment": "production",
        "min_sdk_version": 26,
        "changelog": "First build recorded by hand.",
        "signing_fingerprint": FINGERPRINT,
    }
    metadata.update(overrides)
    return metadata


async def make_artifact(
    api,
    *,
    project_id: str = "p1",
    name: str = "app-release.apk",
    artifact_type: str = "apk",
    content: bytes = b"PK\x03\x04 pretend this is an apk",
    origin: str = "ci",
    version: str | None = "1.2.3",
    content_type: str | None = APK_CONTENT_TYPE,
    retained_until: datetime | None = None,
    android: dict | None = None,
    storage_path: str | None = None,
    write_bytes: bool = True,
):
    """Record one artifact and, unless told otherwise, write its bytes.

    Directly at the store layer — see the module docstring: there is no
    producer in this build to drive instead.
    """
    storage_path = storage_path or f"{project_id}/{name}"
    if write_bytes:
        target = api.artifacts_root / storage_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
    if artifact_type == "apk" and android is None:
        android = android_metadata()
    async with api.factory() as session:
        return await store.create_artifact(
            session,
            project_id=project_id,
            artifact_type=artifact_type,
            name=name,
            size_bytes=len(content),
            sha256=hashlib.sha256(content).hexdigest(),
            origin=origin,
            storage_path=storage_path,
            version=version,
            content_type=content_type,
            retained_until=retained_until,
            android=android,
        )


def mint(api, artifact_id: str, token: str = ALICE_TOKEN):
    return api.post(f"/api/v1/artifacts/{artifact_id}/download-token", headers=auth(token))


def download(api, artifact_id: str, download_token: str, **kwargs):
    headers = {"Authorization": f"Bearer {download_token}"}
    headers.update(kwargs.pop("headers", {}))
    return api.get(f"/api/v1/artifacts/{artifact_id}/download", headers=headers, **kwargs)


def _strings(value) -> list[str]:
    """Every string anywhere inside a decoded JSON body."""
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        return [s for item in value.values() for s in _strings(item)] + list(value.keys())
    if isinstance(value, list):
        return [s for item in value for s in _strings(item)]
    return []


# --------------------------------------------------------------------------
# The catalogue
# --------------------------------------------------------------------------


async def test_the_list_carries_the_checksum_and_the_signing_metadata(api) -> None:
    """Issue #11's "checksums and signing metadata before download/install".

    Before means *in the catalogue*, not only in the download response: a
    client decides whether to start a multi-megabyte transfer from what the
    list already told it.
    """
    artifact = await make_artifact(api)

    body = api.get("/api/v1/artifacts", headers=auth(ALICE_TOKEN)).json()
    assert [item["id"] for item in body["items"]] == [artifact.id]

    item = body["items"][0]
    assert item["sha256"] == artifact.sha256 and len(item["sha256"]) == 64
    assert item["android"]["signingFingerprint"] == FINGERPRINT
    assert item["android"]["packageName"] == "com.example.codexbridge"
    assert item["android"]["versionCode"] == 42
    assert item["sizeBytes"] == artifact.size_bytes
    assert item["retained"] is True


async def test_detail_reports_the_same_shape_as_the_list(api) -> None:
    artifact = await make_artifact(api)
    detail = api.get(f"/api/v1/artifacts/{artifact.id}", headers=auth(ALICE_TOKEN))
    assert detail.status_code == 200
    body = detail.json()
    assert body["id"] == artifact.id
    assert body["projectId"] == "p1"
    assert body["type"] == "apk"
    assert body["contentType"] == APK_CONTENT_TYPE
    assert body["createdAt"].endswith("Z")
    assert body["android"]["environment"] == "production"


async def test_a_non_apk_artifact_carries_no_android_block(api) -> None:
    """`android` is absent, not null: an archive has no build metadata to show."""
    artifact = await make_artifact(
        api, name="logs.tar", artifact_type="archive", content_type="application/x-tar",
        android=None, content=b"not an apk",
    )
    body = api.get(f"/api/v1/artifacts/{artifact.id}", headers=auth(ALICE_TOKEN)).json()
    assert "android" not in body


async def test_pagination_walks_every_artifact_exactly_once(api) -> None:
    """Stable ordering across a paged walk — the issue's pagination criterion."""
    created = [await make_artifact(api, name=f"build-{index}.apk") for index in range(7)]

    seen: list[str] = []
    cursor = None
    for _ in range(10):
        query = "/api/v1/artifacts?limit=3" + (f"&cursor={cursor}" if cursor else "")
        page = api.get(query, headers=auth(ALICE_TOKEN)).json()
        seen.extend(item["id"] for item in page["items"])
        cursor = page["page"]["nextCursor"]
        if not page["page"]["hasMore"]:
            break

    assert cursor is None
    assert len(seen) == len(set(seen)) == len(created)
    assert set(seen) == {artifact.id for artifact in created}


# --------------------------------------------------------------------------
# Project scope
# --------------------------------------------------------------------------


async def test_an_artifact_in_another_project_is_absent_from_the_list(api) -> None:
    mine = await make_artifact(api, project_id="p1")
    await make_artifact(api, project_id="p2", name="other.apk")

    body = api.get("/api/v1/artifacts", headers=auth(ALICE_TOKEN)).json()
    assert [item["id"] for item in body["items"]] == [mine.id]


async def test_an_artifact_in_another_project_is_indistinguishable_from_a_missing_one(api) -> None:
    """The exact cross-project answer every other resource in this contract gives.

    Not merely "some 404": the status, the `code` and the `message` must be
    byte-identical to the answer for an id that does not exist, or the pair of
    responses is an existence oracle — a caller learns which ids are real in
    projects they cannot see. `routes/conversations.py` and
    `routes/sessions.py` answer the same way, and this asserts equality rather
    than trusting two similar-looking constants.
    """
    hidden = await make_artifact(api, project_id="p2", name="secret.apk")

    forbidden = api.get(f"/api/v1/artifacts/{hidden.id}", headers=auth(ALICE_TOKEN))
    invented = api.get("/api/v1/artifacts/no-such-artifact-id", headers=auth(ALICE_TOKEN))

    assert forbidden.status_code == invented.status_code == 404
    assert forbidden.json()["code"] == invented.json()["code"] == "not_found"
    assert forbidden.json()["message"] == invented.json()["message"]
    # requestId differs per request by construction; everything else must not.
    assert {k: v for k, v in forbidden.json().items() if k != "requestId"} == {
        k: v for k, v in invented.json().items() if k != "requestId"
    }


async def test_minting_a_token_for_a_hidden_artifact_gives_the_same_404(api) -> None:
    """The mint endpoint must not be the oracle the read endpoint refuses to be."""
    hidden = await make_artifact(api, project_id="p2", name="secret.apk")

    forbidden = mint(api, hidden.id)
    invented = mint(api, "no-such-artifact-id")

    assert forbidden.status_code == invented.status_code == 404
    assert forbidden.json()["message"] == invented.json()["message"]


async def test_the_project_query_cannot_widen_what_the_caller_may_see(api) -> None:
    """`?project=p2` from a p1-only actor narrows to nothing, never widens."""
    await make_artifact(api, project_id="p2", name="other.apk")
    body = api.get("/api/v1/artifacts?project=p2", headers=auth(ALICE_TOKEN)).json()
    assert body["items"] == []


async def test_an_admin_sees_every_project(api) -> None:
    first = await make_artifact(api, project_id="p1")
    second = await make_artifact(api, project_id="p2", name="other.apk")
    body = api.get("/api/v1/artifacts", headers=auth(ADMIN_TOKEN)).json()
    assert {item["id"] for item in body["items"]} == {first.id, second.id}


async def test_a_download_token_cannot_reach_across_projects(api) -> None:
    """The bytes are behind the same project scope the metadata is.

    An account that may mint for its own project must not be able to present
    that credential against an artifact in a project it cannot see — and the
    refusal is the same `401` as every other download refusal, not a `403`
    that would confirm the artifact exists.
    """
    mine = await make_artifact(api, project_id="p1")
    theirs = await make_artifact(api, project_id="p2", name="other.apk")

    token = mint(api, mine.id).json()["token"]
    refused = download(api, theirs.id, token)
    assert refused.status_code == 401
    assert refused.json()["code"] == "unauthenticated"


# --------------------------------------------------------------------------
# The download token lifecycle
# --------------------------------------------------------------------------


async def test_mint_then_download_returns_the_bytes(api) -> None:
    content = b"PK\x03\x04 pretend this is an apk"
    artifact = await make_artifact(api, content=content)

    minted = mint(api, artifact.id)
    assert minted.status_code == 201
    body = minted.json()
    assert body["artifactId"] == artifact.id
    assert body["tokenType"] == "Bearer"
    assert body["downloadPath"] == f"/api/v1/artifacts/{artifact.id}/download"
    assert body["sha256"] == artifact.sha256
    assert body["expiresAt"].endswith("Z")
    assert minted.headers["Cache-Control"] == "no-store"

    fetched = download(api, artifact.id, body["token"])
    assert fetched.status_code == 200
    assert fetched.content == content
    assert fetched.headers["X-Artifact-Sha256"] == artifact.sha256
    assert hashlib.sha256(fetched.content).hexdigest() == body["sha256"]
    assert fetched.headers["Content-Disposition"] == 'attachment; filename="app-release.apk"'
    assert fetched.headers["Accept-Ranges"] == "bytes"


async def test_the_minted_credential_never_travels_in_the_url(api) -> None:
    """`security-standards.md` §2: a credential in a query string reaches logs.

    The design note for this issue floated `?token=…`. What the mint endpoint
    hands back is a *path* with no credential in it; the token goes in a
    header. A regression here is silent — the download would still work — so
    it is asserted rather than left to the docstring that argues it.
    """
    artifact = await make_artifact(api)
    body = mint(api, artifact.id).json()
    assert body["token"] not in body["downloadPath"]
    assert "?" not in body["downloadPath"]


async def test_a_session_bearer_token_does_not_download(api) -> None:
    """The session credential is not what fetches the bytes.

    If it were, the split that keeps the app's session token out of the system
    downloader would be decoration.
    """
    artifact = await make_artifact(api)
    refused = download(api, artifact.id, ALICE_TOKEN)
    assert refused.status_code == 401
    assert refused.headers["WWW-Authenticate"].startswith("Bearer")


async def test_a_download_with_no_credential_is_refused(api) -> None:
    artifact = await make_artifact(api)
    response = api.get(f"/api/v1/artifacts/{artifact.id}/download")
    assert response.status_code == 401
    assert response.json()["code"] == "unauthenticated"


async def test_an_expired_token_is_refused_with_the_typed_error(api) -> None:
    artifact = await make_artifact(api)
    async with api.factory() as session:
        await store.create_artifact_download_token(
            session,
            artifact_id=artifact.id,
            user_id="alice",
            token="already-dead",
            expires_at=datetime.now(timezone.utc) - timedelta(seconds=1),
        )

    refused = download(api, artifact.id, "already-dead")
    assert refused.status_code == 401
    assert refused.json()["code"] == "unauthenticated"
    assert refused.json()["retryable"] is False


async def test_a_token_minted_for_one_artifact_is_refused_on_another(api) -> None:
    first = await make_artifact(api, name="first.apk")
    second = await make_artifact(api, name="second.apk")

    token = mint(api, first.id).json()["token"]
    assert download(api, first.id, token).status_code == 200
    assert download(api, second.id, token).status_code == 401


async def test_an_unknown_token_is_refused(api) -> None:
    artifact = await make_artifact(api)
    refused = download(api, artifact.id, "never-minted-anywhere")
    assert refused.status_code == 401


async def test_every_download_refusal_is_the_same_refusal(api) -> None:
    """Absent, unknown, expired and wrong-artifact must be indistinguishable.

    Telling them apart tells the holder of a token they were never given
    whether it was ever real, and which artifact it was for — the same rule
    `gateway/app/api/auth.py:unauthenticated` states for session credentials.
    """
    first = await make_artifact(api, name="first.apk")
    second = await make_artifact(api, name="second.apk")
    other_token = mint(api, second.id).json()["token"]
    async with api.factory() as session:
        await store.create_artifact_download_token(
            session, artifact_id=first.id, user_id="alice", token="stale",
            expires_at=datetime.now(timezone.utc) - timedelta(seconds=1),
        )

    bodies = []
    for response in (
        api.get(f"/api/v1/artifacts/{first.id}/download"),
        download(api, first.id, "never-minted"),
        download(api, first.id, "stale"),
        download(api, first.id, other_token),
    ):
        assert response.status_code == 401
        bodies.append({k: v for k, v in response.json().items() if k != "requestId"})

    assert all(body == bodies[0] for body in bodies), bodies


async def test_minting_for_an_unknown_artifact_is_a_typed_404(api) -> None:
    response = mint(api, "no-such-artifact")
    assert response.status_code == 404
    assert response.json()["code"] == "not_found"


async def test_the_download_token_is_never_stored_in_the_clear(api) -> None:
    """The fourth narrowing, which the module docstring claimed was tested.

    It was not: a council round's claim auditor found that changing
    `hash_token(token)` to `token` in `store.create_artifact_download_token`
    kept the whole suite green, while `routes/artifacts.py` and
    `docs/api/README.md` both asserted "each one is tested". The behaviour was
    already right; the coverage claim was the false part.

    Asserted against the table, not against the function: what matters is that
    a reader of the database cannot download anything with what they find.
    """
    from sqlalchemy import select

    from gateway.app.models.entities import ArtifactDownloadTokenModel
    from shared.security import hash_token

    artifact = await make_artifact(api)
    token = mint(api, artifact.id).json()["token"]

    async with api.factory() as session:
        rows = list((await session.execute(select(ArtifactDownloadTokenModel))).scalars())

    assert len(rows) == 1
    assert rows[0].token_hash != token
    assert rows[0].token_hash == hash_token(token)
    assert token not in rows[0].token_hash


async def test_a_token_stops_at_the_projects_the_account_still_has(api) -> None:
    """"...or narrows" — the half of the re-read claim that had no test.

    Disabling was pinned; narrowing `allowed_projects` was asserted in prose
    only. An operator who moves an account off a project expects that account's
    outstanding download tokens for that project to stop, not to run out their
    TTL.
    """
    import json as _json

    from gateway.app.core.config import settings

    artifact = await make_artifact(api)
    token = mint(api, artifact.id).json()["token"]
    assert download(api, artifact.id, token).status_code == 200

    registry = _json.loads(open(settings.user_registry_file, encoding="utf-8").read())
    for user in registry["users"]:
        if user["user_id"] == "alice":
            user["allowed_projects"] = []
    with open(settings.user_registry_file, "w", encoding="utf-8") as handle:
        _json.dump(registry, handle)

    assert download(api, artifact.id, token).status_code == 401


@pytest.mark.parametrize(
    "header",
    ["bytes=" + "9" * 5000 + "-", "bytes=-" + "9" * 5000, "bytes=0-" + "9" * 5000],
)
async def test_an_absurdly_long_range_is_not_a_five_hundred(api, header: str) -> None:
    """A `Range` of 4301+ digits was an unhandled `ValueError`.

    `int()` refuses a decimal string past CPython's 4300-digit conversion limit
    (the CVE-2020-10735 mitigation), so `_RANGE_RE`'s unbounded `\\d*` turned one
    header into `500 internal_error` with `retryable: true` — inviting the
    client to send it again — plus a stack trace per request, reachable by
    anyone holding a five-minute download token. Found by a council round's
    adversarial-user lens; the fix bounds the digit run in the pattern, so an
    over-long range is simply a malformed one.
    """
    artifact = await make_artifact(api, content=b"0123456789")
    token = mint(api, artifact.id).json()["token"]

    response = download(api, artifact.id, token, headers={"Range": header})
    assert response.status_code < 500, header
    assert response.status_code in (200, 416)


async def test_a_zero_padded_range_is_still_a_range(api) -> None:
    """Leading zeros are legal and carry no meaning — RFC 9110 §14.1.1 is `1*DIGIT`.

    The first fix for the 500 above bounded the digit run at 19, on the
    reasoning that no file needs more. But the bound counts *digits*, not
    magnitude: a twenty-digit spelling of `1` stopped matching, the header was
    dropped, and the endpoint re-sent the whole file with `200` where a `206`
    was asked for — the exact failure `Range` support exists to prevent, and
    silent, because an ignored range is by design indistinguishable from an
    unsupported one. Caught by the second round of the same council.
    """
    artifact = await make_artifact(api, content=b"0123456789")
    token = mint(api, artifact.id).json()["token"]

    padded = download(api, artifact.id, token, headers={"Range": "bytes=" + "0" * 19 + "1-2"})
    assert padded.status_code == 206
    assert padded.content == b"12"
    assert padded.headers["Content-Range"] == "bytes 1-2/10"


async def test_the_missing_content_404_writes_a_log_line_the_request_id_finds(api, caplog) -> None:
    """The `requestId` has to resolve to something, or the refusal is a dead end.

    `_content_missing` told the operator to find the artifact "from the
    `requestId` in the log" while no log line existed: `ApiError` is rendered by
    the error handlers, which log nothing, and this gateway has no access log.
    A council round reproduced the silence with `caplog` at DEBUG over a whole
    request — every record was harness noise.
    """
    import logging

    artifact = await make_artifact(api, write_bytes=False)
    token = mint(api, artifact.id).json()["token"]

    with caplog.at_level(logging.WARNING, logger="gateway.app.api.routes.artifacts"):
        response = download(api, artifact.id, token)

    assert response.status_code == 404
    records = [r for r in caplog.records if r.message == "artifact_content_unavailable"]
    assert len(records) == 1
    assert records[0].artifact_id == artifact.id
    assert records[0].correlation_id == response.headers["X-Request-Id"]
    # The operator gets the identifier; the log must not become the place the
    # filesystem leaks instead of the response body.
    assert str(api.artifacts_root) not in caplog.text


async def test_a_token_survives_reuse_inside_its_lifetime(api) -> None:
    """Deliberately **not** single-use — the lifetime is the control.

    Issue #11 asks for range and resumable downloads in the same breath as
    short-lived authorization. A token consumed by the first request makes a
    resumed transfer impossible: the downloader would have to re-authenticate
    mid-stream, which is the thing this endpoint exists to avoid. Asserted so
    the property is a decision on the record rather than an accident — see
    `gateway/app/api/routes/artifacts.py`'s module docstring.

    The narrowing controls that *are* in force each have their own test above:
    bound to one artifact, bound to one account, and expiring in minutes.
    """
    artifact = await make_artifact(api)
    token = mint(api, artifact.id).json()["token"]

    first = download(api, artifact.id, token)
    resumed = download(api, artifact.id, token, headers={"Range": "bytes=4-"})
    assert first.status_code == 200
    assert resumed.status_code == 206


async def test_issuing_a_download_authorization_is_audited(api) -> None:
    """A credential for bytes leaves a trail, like every other credential here.

    `store.issue_auth_grant` audits an access/refresh pair and
    `revoke_access_token` audits its revocation; minting an artifact download
    token wrote nothing, so an operator investigating a leaked APK could not
    answer "who was authorized to fetch it, and when" — the token row itself
    is deleted the moment it expires.

    Recorded under the `auth` entity type rather than `artifact`, which is what
    puts it inside `purge_expired_audit_events`'s retention window. The payload
    must never carry the token: writing a credential into the audit table would
    undo the hashing beside it.
    """
    from sqlalchemy import select

    from gateway.app.models.entities import AuditEventModel

    artifact = await make_artifact(api)
    minted = mint(api, artifact.id).json()

    async with api.factory() as session:
        rows = list(
            (
                await session.execute(
                    select(AuditEventModel).where(
                        AuditEventModel.event_type == "auth.artifact_download_authorized"
                    )
                )
            ).scalars()
        )

    assert len(rows) == 1
    assert rows[0].entity_type == "auth"
    assert rows[0].entity_id == "alice"
    assert artifact.id in rows[0].payload_json
    assert minted["token"] not in rows[0].payload_json
    assert "alice@example.com" not in rows[0].payload_json


def test_the_default_artifacts_root_follows_the_working_directory() -> None:
    """The default is a development convenience, not a stable location.

    `str(Path("data/artifacts").resolve())` resolves against the cwd at import,
    so the unconfigured default moves with the directory the service started
    from. The comment in `gateway/app/core/config.py` used to claim the
    opposite ("rather than a relative string whose meaning depends on the
    working directory"), which is the kind of claim a reader retires a risk on.
    Pinned here so the comment and the behaviour cannot drift apart again: a
    deployment sets `CODEX_BRIDGE_ARTIFACTS_ROOT`, and `.env.example` says so.
    """
    import importlib.util
    import os
    import tempfile
    from pathlib import Path

    from gateway.app.core import config as installed

    source = Path(installed.__file__).resolve()
    previous = os.getcwd()
    with tempfile.TemporaryDirectory() as elsewhere:
        try:
            os.chdir(elsewhere)
            # A private, unregistered copy of the module: the default is
            # captured once when the class body runs, so only a fresh import
            # can show what it captures. Not `importlib.reload`, which would
            # swap the `settings` singleton every other module already holds.
            spec = importlib.util.spec_from_file_location("_artifacts_root_probe", source)
            probe = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(probe)
            moved = probe.Settings().artifacts_root
        finally:
            os.chdir(previous)
        expected = Path(elsewhere).resolve() / "data" / "artifacts"

    assert Path(moved).is_absolute()
    assert moved == str(expected)
    assert moved != installed.Settings().artifacts_root


async def test_a_token_whose_account_was_disabled_stops_working(api) -> None:
    """The account is re-read at download time, not trusted from minting time.

    A five-minute window is small and it is not zero: an operator who disables
    an account expects the bytes to stop.
    """
    artifact = await make_artifact(api)
    token = mint(api, artifact.id).json()["token"]
    assert download(api, artifact.id, token).status_code == 200

    from gateway.app.core.config import settings

    registry = json.loads(open(settings.user_registry_file, encoding="utf-8").read())
    for user in registry["users"]:
        if user["user_id"] == "alice":
            user["enabled"] = False
    with open(settings.user_registry_file, "w", encoding="utf-8") as handle:
        json.dump(registry, handle)

    assert download(api, artifact.id, token).status_code == 401


# --------------------------------------------------------------------------
# Range requests
# --------------------------------------------------------------------------


async def test_a_satisfiable_range_is_a_206_with_content_range(api) -> None:
    content = b"0123456789"
    artifact = await make_artifact(api, content=content)
    token = mint(api, artifact.id).json()["token"]

    response = download(api, artifact.id, token, headers={"Range": "bytes=2-5"})
    assert response.status_code == 206
    assert response.content == b"2345"
    assert response.headers["Content-Range"] == "bytes 2-5/10"
    assert response.headers["Content-Length"] == "4"


async def test_a_suffix_range_returns_the_tail(api) -> None:
    content = b"0123456789"
    artifact = await make_artifact(api, content=content)
    token = mint(api, artifact.id).json()["token"]

    response = download(api, artifact.id, token, headers={"Range": "bytes=-3"})
    assert response.status_code == 206
    assert response.content == b"789"
    assert response.headers["Content-Range"] == "bytes 7-9/10"


async def test_an_unsatisfiable_range_is_a_416_naming_the_size(api) -> None:
    content = b"0123456789"
    artifact = await make_artifact(api, content=content)
    token = mint(api, artifact.id).json()["token"]

    response = download(api, artifact.id, token, headers={"Range": "bytes=99-"})
    assert response.status_code == 416
    assert response.headers["Content-Range"] == "bytes */10"
    assert response.json()["code"] == "validation_failed"


@pytest.mark.parametrize("header", ["items=0-1", "bytes=abc", "bytes=0-1, 5-6", "bytes=5-2", "bytes=-0"])
async def test_a_range_this_endpoint_does_not_serve_falls_back_to_the_whole_file(api, header: str) -> None:
    """RFC 9110 §14.2 lets a server ignore a `Range` it will not honour.

    Answering `416` for a header a client sent speculatively would break that
    client for no gain; the full representation is always a correct answer.
    """
    content = b"0123456789"
    artifact = await make_artifact(api, content=content)
    token = mint(api, artifact.id).json()["token"]

    response = download(api, artifact.id, token, headers={"Range": header})
    assert response.status_code == 200
    assert response.content == content


def test_parse_range_header_agrees_with_the_endpoint() -> None:
    """The unit-level statement of the same rule, over sizes the API cannot reach."""
    assert parse_range_header(None, 10) is None
    assert parse_range_header("bytes=0-", 10).length == 10
    assert parse_range_header("bytes=0-99", 10).end == 9
    with pytest.raises(Exception):
        parse_range_header("bytes=0-1", 0)


# --------------------------------------------------------------------------
# Retention
# --------------------------------------------------------------------------


async def test_a_retired_artifact_is_still_listed_and_says_so(api) -> None:
    artifact = await make_artifact(
        api, retained_until=datetime.now(timezone.utc) - timedelta(hours=1)
    )
    body = api.get("/api/v1/artifacts", headers=auth(ALICE_TOKEN)).json()
    assert body["items"][0]["id"] == artifact.id
    assert body["items"][0]["retained"] is False


async def test_a_retired_artifact_mints_no_token_and_serves_no_bytes(api) -> None:
    artifact = await make_artifact(api)
    token = mint(api, artifact.id).json()["token"]

    async with api.factory() as session:
        row = await store.get_artifact_for_projects(session, artifact.id, None)
        row.retained_until = datetime.now(timezone.utc) - timedelta(seconds=1)
        await session.commit()

    refused_mint = mint(api, artifact.id)
    assert refused_mint.status_code == 409
    assert refused_mint.json()["code"] == "conflict"

    refused_download = download(api, artifact.id, token)
    assert refused_download.status_code == 409


# --------------------------------------------------------------------------
# The filesystem never reaches the client
# --------------------------------------------------------------------------


async def test_no_response_body_carries_the_storage_path(api) -> None:
    """`storage_path` is this table's `ProjectModel.path`.

    `docs/api/README.md` §"Fields that must never ship" forbids a server
    filesystem path in a response. Checked over every read on this surface at
    once, including the artifacts root itself, so a field added later to any
    one of them is caught here rather than in review.
    """
    artifact = await make_artifact(api)
    root = str(api.artifacts_root)

    responses = [
        api.get("/api/v1/artifacts", headers=auth(ALICE_TOKEN)),
        api.get(f"/api/v1/artifacts/{artifact.id}", headers=auth(ALICE_TOKEN)),
        api.get("/api/v1/builds/android", headers=auth(ALICE_TOKEN)),
        api.get(f"/api/v1/builds/android/{artifact.id}", headers=auth(ALICE_TOKEN)),
        mint(api, artifact.id),
    ]

    for response in responses:
        raw = response.text
        assert "storagePath" not in raw and "storage_path" not in raw
        assert root not in raw
        assert "p1/app-release.apk" not in raw
        for value in _strings(response.json()):
            assert not value.startswith("/srv/"), value


async def test_a_traversing_storage_path_cannot_be_stored_at_all(api) -> None:
    """The lexical half of the confinement rule, at the write.

    A path that never enters the table cannot be served, whatever a later
    reader of `storage_path` does with it.
    """
    for hostile in ("../../etc/passwd", "/etc/passwd", "p1/../../etc/passwd", "p1/./x", "..", "p1//x"):
        with pytest.raises(ArtifactError) as raised:
            await make_artifact(api, storage_path=hostile, write_bytes=False)
        assert raised.value.field == "/storagePath"


async def test_a_symlink_inside_the_root_does_not_escape_it(api) -> None:
    """The half the string check cannot see.

    `p1/secrets.txt` is a perfectly legal *stored* path; what it points at is
    not. `Path.resolve` follows the link, and `resolve_artifact_file` refuses
    anything that lands outside the root. Without that second check the
    download would happily stream `/etc/passwd` under an artifact's name.
    """
    outside = api.artifacts_root.parent / "outside-the-root.txt"
    outside.write_bytes(b"this must never be served")
    link = api.artifacts_root / "p1"
    link.mkdir(parents=True, exist_ok=True)
    (link / "escape.txt").symlink_to(outside)

    artifact = await make_artifact(
        api, name="escape.txt", artifact_type="report", android=None,
        content_type="text/plain", storage_path="p1/escape.txt",
        content=b"this must never be served", write_bytes=False,
    )
    token = mint(api, artifact.id).json()["token"]

    response = download(api, artifact.id, token)
    assert response.status_code == 404
    assert response.json()["code"] == "not_found"
    assert b"never be served" not in response.content

    with pytest.raises(ArtifactError):
        resolve_artifact_file("p1/escape.txt")


async def test_a_row_whose_bytes_are_gone_is_a_typed_404_naming_no_path(api) -> None:
    artifact = await make_artifact(api, write_bytes=False)
    token = mint(api, artifact.id).json()["token"]

    response = download(api, artifact.id, token)
    assert response.status_code == 404
    assert response.json()["code"] == "not_found"
    assert str(api.artifacts_root) not in response.text


def test_resolve_refuses_before_it_reports_missing(artifacts_root) -> None:
    """A missing file and a rejected path are different exceptions, not one.

    Takes `artifacts_root` even though it writes nothing: without it this test
    resolved against the real default root (`<cwd>/data/artifacts`) and passed
    only because that directory happens to be absent on a developer's machine —
    a pass coupled to the working directory rather than to the behaviour. A
    council round flagged it.
    """
    with pytest.raises(ArtifactError):
        validate_storage_path("../x")
    with pytest.raises(ArtifactContentMissing):
        resolve_artifact_file("definitely-not-there.bin")


# --------------------------------------------------------------------------
# Android builds
# --------------------------------------------------------------------------


async def test_the_android_list_shows_only_apks(api) -> None:
    apk = await make_artifact(api)
    await make_artifact(
        api, name="logs.tar", artifact_type="archive", android=None,
        content_type="application/x-tar", content=b"tarball",
    )

    body = api.get("/api/v1/builds/android", headers=auth(ALICE_TOKEN)).json()
    assert [item["id"] for item in body["items"]] == [apk.id]
    assert body["items"][0]["android"]["versionName"] == "1.2.3"


async def test_the_android_list_filters_on_metadata_the_catalogue_cannot(api) -> None:
    production = await make_artifact(api, name="prod.apk")
    await make_artifact(
        api, name="staging.apk", android=android_metadata(environment="staging", version_code=43)
    )

    body = api.get("/api/v1/builds/android?environment=production", headers=auth(ALICE_TOKEN)).json()
    assert [item["id"] for item in body["items"]] == [production.id]

    by_package = api.get(
        "/api/v1/builds/android?packageName=com.example.codexbridge", headers=auth(ALICE_TOKEN)
    ).json()
    assert len(by_package["items"]) == 2

    none = api.get("/api/v1/builds/android?packageName=com.other.app", headers=auth(ALICE_TOKEN)).json()
    assert none["items"] == []


async def test_a_build_is_addressed_by_the_artifacts_own_id(api) -> None:
    artifact = await make_artifact(api)
    body = api.get(f"/api/v1/builds/android/{artifact.id}", headers=auth(ALICE_TOKEN)).json()
    assert body["id"] == artifact.id
    assert body["android"]["minSdkVersion"] == 26


async def test_an_artifact_that_is_not_a_build_is_not_a_build(api) -> None:
    """Same `404` as an id that does not exist: from this endpoint's vocabulary
    there is no such build, and "that id is an artifact, just not a build"
    describes the row under the wrong name."""
    archive = await make_artifact(
        api, name="logs.tar", artifact_type="archive", android=None,
        content_type="application/x-tar", content=b"tarball",
    )
    missing = api.get(f"/api/v1/builds/android/{archive.id}", headers=auth(ALICE_TOKEN))
    invented = api.get("/api/v1/builds/android/no-such-id", headers=auth(ALICE_TOKEN))
    assert missing.status_code == invented.status_code == 404
    assert missing.json()["message"] == invented.json()["message"]


async def test_a_build_in_another_project_answers_the_same_404(api) -> None:
    hidden = await make_artifact(api, project_id="p2", name="secret.apk")
    forbidden = api.get(f"/api/v1/builds/android/{hidden.id}", headers=auth(ALICE_TOKEN))
    invented = api.get("/api/v1/builds/android/no-such-id", headers=auth(ALICE_TOKEN))
    assert forbidden.status_code == invented.status_code == 404
    assert forbidden.json()["message"] == invented.json()["message"]


async def test_the_android_list_is_project_scoped(api) -> None:
    mine = await make_artifact(api, project_id="p1")
    await make_artifact(api, project_id="p2", name="other.apk")
    body = api.get("/api/v1/builds/android", headers=auth(ALICE_TOKEN)).json()
    assert [item["id"] for item in body["items"]] == [mine.id]


# --------------------------------------------------------------------------
# Store-level validation
# --------------------------------------------------------------------------


async def test_an_apk_must_carry_build_metadata_and_nothing_else_may(api) -> None:
    async with api.factory() as session:
        with pytest.raises(ArtifactError) as missing:
            # Not through `make_artifact`: that helper supplies the metadata an
            # apk needs, which is exactly the thing withheld here.
            await store.create_artifact(
                session, project_id="p1", artifact_type="apk", name="app-release.apk",
                size_bytes=1, sha256="ab" * 32, origin="ci", storage_path="p1/app-release.apk",
                android=None,
            )
    assert missing.value.field == "/android"

    with pytest.raises(ArtifactError) as extra:
        await make_artifact(
            api, name="logs.tar", artifact_type="archive", android=android_metadata(),
            content_type="application/x-tar", write_bytes=False,
        )
    assert extra.value.field == "/android"


async def test_a_fingerprint_has_one_spelling(api) -> None:
    """A bare 64-hex fingerprint and the colon-separated form are one certificate."""
    bare = "ab" * 32
    artifact = await make_artifact(api, android=android_metadata(signing_fingerprint=bare))
    body = api.get(f"/api/v1/artifacts/{artifact.id}", headers=auth(ALICE_TOKEN)).json()
    assert body["android"]["signingFingerprint"] == FINGERPRINT

    with pytest.raises(ArtifactError):
        await make_artifact(
            api, name="bad.apk", android=android_metadata(signing_fingerprint="not-a-fingerprint"),
            write_bytes=False,
        )


async def test_a_name_that_could_forge_a_header_is_refused(api) -> None:
    """`name` is interpolated into `Content-Disposition`.

    A quote or a newline there is a header-injection primitive, so the
    allowlist is enforced at the write and the download can interpolate
    without escaping.
    """
    for hostile in ('evil".apk', "evil\r\nX-Injected: 1", "../escape.apk", ".hidden"):
        with pytest.raises(ArtifactError) as raised:
            await make_artifact(api, name=hostile, write_bytes=False)
        assert raised.value.field == "/name"


async def test_an_artifact_needs_a_real_checksum(api) -> None:
    async with api.factory() as session:
        with pytest.raises(ArtifactError) as raised:
            await store.create_artifact(
                session, project_id="p1", artifact_type="report", name="report.txt",
                size_bytes=1, sha256="not-a-digest", origin="ci", storage_path="p1/report.txt",
            )
    assert raised.value.field == "/sha256"


async def test_an_unknown_project_is_refused_at_the_write(api) -> None:
    with pytest.raises(ArtifactError) as raised:
        await make_artifact(api, project_id="p-nope", write_bytes=False)
    assert raised.value.field == "/projectId"
