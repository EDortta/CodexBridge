"""The artifact catalogue, Android build metadata, and the download flow — issue #11.

An **artifact** is a retained file this gateway can hand to CodexBridgeMobile:
type, project, version, size, origin, checksum, creation time and retention
window. An **Android build** is not a second entity — it is an artifact of type
`apk` plus its APK metadata, keyed by the artifact's own id, so
`GET /api/v1/builds/android/{buildId}` takes an `ArtifactId` and a client never
has to hold two identifiers for one file.

## Nothing in this build produces an artifact

There is no ingestion path: no executor message, no upload endpoint, no build
hook writes a row. Every artifact this router can serve was created by a direct
call to `store.create_artifact`, which today means a test fixture or an operator
script. That is said out loud for the same reason `routes/projects.py` says its
counts read one entity rather than three: a mobile client reading these
endpoints will get an empty list on this deployment, and an empty list is worth
knowing the reason for. Ingestion is a future issue; the catalogue, the
authorization and the download lifecycle are this one's.

## The download flow, and why the bytes are not behind the session token

`POST /api/v1/artifacts/{artifactId}/download-token` mints a short-lived bearer
credential for exactly one artifact.
`GET /api/v1/artifacts/{artifactId}/download` accepts **that** credential and
nothing else — it never looks at a session token and never consults
`permissions.CATALOGUE`.

The split exists because the phone does not do the transfer. Android hands a
multi-megabyte download to the system downloader, which is a separate process
with no access to the app's session; giving it the session bearer token would
put the credential that can approve a sensitive task into a component whose only
job is fetching a file.

**The credential travels in `Authorization: Bearer`, not in the URL.** The
design note for this issue floated `?token=…`; this codebase has already been
burned by exactly that (issue #15: an executor's machine token reached the
gateway log through a query string) and `security-standards.md` §2 forbids it
outright — a query string reaches access logs, proxies, browser history and
`Referer`. Every HTTP downloader worth using, `DownloadManager` included, can
set a request header. So the response of the mint endpoint carries a *path*
with no credential in it, and the token separately.

Five things narrow the credential. Each one names the test that pins it, because
"each one is tested" was written here once while one of them was not
(`council.md` §2, the claim auditor) — a list of properties is not evidence that
they hold. Four live in `tests/integration/test_artifacts.py` and the fifth is
named with its file:

- bound to the artifact — presenting it on another one is refused
  (`test_a_token_minted_for_one_artifact_is_refused_on_another`);
- bound to the minting account, **re-read at download time**, so an account the
  operator disables (`test_a_token_whose_account_was_disabled_stops_working`) or
  narrows (`test_a_token_stops_at_the_projects_the_account_still_has`) after
  minting cannot still pull the bytes. Same rule refresh rotation already
  applies to a grant;
- it expires in minutes (`settings.artifact_download_token_ttl_seconds`,
  `test_an_expired_token_is_refused_with_the_typed_error`);
- it dies with the sign-in that minted it. `POST /api/v1/auth/revoke` deletes
  the download tokens of **that grant**, because a sign-out that leaves an APK
  streaming is the failure that endpoint exists to prevent
  (`test_auth.py::test_signing_out_kills_a_download_token_minted_before_it` —
  the only one of the five that lives in `test_auth.py`, because what it tests
  is what sign-out does). Scoped to the grant and not to the actor: a second
  council round found the by-actor version letting an unauthenticated replay of
  a dead refresh token kill a live grant's downloads;
- it is stored hashed, so the database never holds anything downloadable
  (`test_the_download_token_is_never_stored_in_the_clear`).

It is deliberately **not** single-use. Issue #11 asks for range and resumable
downloads in the same breath as short-lived authorization, and a token consumed
by the first request makes a resumed transfer impossible — the downloader would
have to re-authenticate mid-stream, which is the thing this endpoint exists to
avoid. The lifetime is the control.

## Retention is load-bearing, not a decorative timestamp

Past `retainedUntil` the catalogue still lists the artifact — a client showing a
stale entry deserves an explanation rather than a mystery 404 — but minting a
token and serving the bytes both answer `409 conflict`. A retention field that
only ever described something would be the always-null field
`docs/api/README.md` refuses to publish.

## No response ever carries `storage_path`

`ArtifactModel.storage_path` is this table's `ProjectModel.path`: an internal
filesystem path, excluded from every DTO below by construction rather than by a
filter applied late. `gateway/app/services/artifact_storage.py` is the only code
that resolves it, and it refuses anything that leaves the artifacts root.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Query, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.responses import StreamingResponse

from gateway.app.api import pagination, permissions, timestamps
from gateway.app.api.auth import bearer_token, require_action, unauthenticated, visible_projects
from gateway.app.api.errors import CONFLICT, NOT_FOUND, VALIDATION_FAILED, ApiError
from gateway.app.api.request_context import current_request_id
from gateway.app.core.config import settings
from gateway.app.core.oauth import expires_in, generate_artifact_download_token
from gateway.app.core.users import AuthenticatedPrincipal, lookup_user
from gateway.app.db.session import get_session
from gateway.app.services import artifact_storage, store
from gateway.app.services.artifact_storage import ArtifactContentMissing, UnsatisfiableRange
from gateway.app.services.artifact_types import ArtifactError


logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1")

ARTIFACTS_ENDPOINT = "/api/v1/artifacts"
ANDROID_BUILDS_ENDPOINT = "/api/v1/builds/android"

# One message for every way a download can be refused authorization — absent
# token, unknown, expired, minted for another artifact, belonging to an account
# the operator has since disabled or narrowed, or revoked by a sign-out (whose
# row is deleted, so it arrives here as "unknown"). See
# `_artifact_for_download_token` and `gateway/app/api/auth.py:unauthenticated`.
_DOWNLOAD_TOKEN_REJECTED = (
    "This download requires a current download token for this artifact, "
    "presented as `Authorization: Bearer`."
)


def _iso(value: datetime | None) -> str | None:
    return timestamps.utc_z(value)


def _not_found() -> ApiError:
    """The one refusal for an artifact that is absent or invisible.

    Both answer the same `404` with the same message: telling a caller that an
    id exists but belongs to a project they cannot see is precisely the oracle
    `gateway/app/api/auth.py` refuses to build, and every other resource in this
    contract answers the same way.
    """
    return ApiError(status_code=404, code=NOT_FOUND, message="No such artifact.")


def _past_retention() -> ApiError:
    return ApiError(
        status_code=409,
        code=CONFLICT,
        message="This artifact is past its retention window and is no longer downloadable.",
    )


def _content_missing(artifact_id: str, reason: str) -> ApiError:
    """The row is there and the bytes are not.

    Reported without naming anything about the filesystem: the client learns the
    content is unavailable, and the operator learns which artifact from the
    `requestId`. Reachable only by a caller already authorized to see this
    artifact, so it discloses nothing a probe could use.

    **The log line is what makes the second half of that true.** An earlier cut
    of this function said the operator "learns which artifact from the
    `requestId` in the log" while nothing wrote a log line at all: `ApiError` is
    rendered by `errors.install_error_handlers`, which logs nothing, and this
    gateway has no access-log middleware — so the `requestId` on the client's
    screenshot mapped to nothing. A council round reproduced the silence. The
    log line below is the artifact that claim needed, and it carries the same
    `correlation_id` the response's `requestId` carries.

    `reason` separates the two ways to get here — no file, or a stored path
    that stopped resolving inside the root — because they need different
    operator responses and the client is deliberately told neither.
    """
    logger.warning(
        "artifact_content_unavailable",
        extra={
            "correlation_id": current_request_id(),
            "task_id": None,
            "executor_id": None,
            "artifact_id": artifact_id,
            "reason": reason,
        },
    )
    return ApiError(
        status_code=404,
        code=NOT_FOUND,
        message="The stored content for this artifact is not available.",
    )


def _android_dto(build) -> dict:
    return {
        "packageName": build.package_name,
        "versionName": build.version_name,
        "versionCode": build.version_code,
        "environment": build.environment,
        "minSdkVersion": build.min_sdk_version,
        "changelog": build.changelog,
        "signingFingerprint": build.signing_fingerprint,
    }


def _artifact_dto(artifact, build=None, *, now: datetime | None = None) -> dict:
    """Mobile representation of an artifact.

    `storage_path` is absent by construction — see the module docstring. `sha256`
    and, for an APK, `android.signingFingerprint` are present on **every** read,
    not only on the download response: issue #11's acceptance criterion is that
    checksums and signing metadata are available *before* download or install,
    which means the list has to carry them too.
    """
    body = {
        "id": artifact.id,
        "projectId": artifact.project_id,
        "type": artifact.type,
        "name": artifact.name,
        "version": artifact.version,
        "sizeBytes": artifact.size_bytes,
        "sha256": artifact.sha256,
        "origin": artifact.origin,
        "contentType": artifact.content_type,
        "createdAt": _iso(artifact.created_at),
        "retainedUntil": _iso(artifact.retained_until),
        # Derived, not stored: a client comparing `retainedUntil` against its own
        # clock would disagree with the server that actually refuses the
        # download. One of the two has to be authoritative, and it is this one.
        "retained": store.artifact_is_retained(artifact, now),
    }
    if build is not None:
        body["android"] = _android_dto(build)
    return body


def _scoped_projects(principal: AuthenticatedPrincipal, requested: list[str] | None) -> list[str] | None:
    """The caller's visible projects, narrowed by `?project=` but never widened.

    Same helper shape as `routes/decisions.py:list_decisions`: an admin's `None`
    stays unrestricted-minus-the-request, and a restricted caller cannot use the
    query string to reach past their own `allowed_projects`.
    """
    projects = visible_projects(principal)
    if requested:
        projects = [p for p in requested if projects is None or p in projects]
    return projects


@router.get("/artifacts", tags=["artifacts"])
async def list_artifacts(
    project: list[str] | None = Query(default=None),
    type: list[str] | None = Query(default=None),
    origin: list[str] | None = Query(default=None),
    cursor: str | None = Query(default=None),
    limit: int | None = Query(default=None),
    principal: AuthenticatedPrincipal = Depends(require_action(permissions.ARTIFACTS_READ)),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Artifacts the caller may see, newest first."""
    projects = _scoped_projects(principal, project)
    size = pagination.parse_limit(limit)

    scope = pagination.scope_digest(
        ARTIFACTS_ENDPOINT,
        {
            "type": sorted(type) if type else None,
            "origin": sorted(origin) if origin else None,
            "actor": principal.user_id,
            "projects": sorted(projects) if projects is not None else "*",
        },
    )
    after = None
    if cursor:
        position = pagination.decode_cursor(scope, cursor, expect={"createdAt": str, "id": str})
        after = (position["createdAt"], position["id"])

    rows = await store.list_artifacts_page(
        session, project_ids=projects, types=type, origins=origin, after=after, limit=size
    )
    page, info = pagination.paginate(
        rows,
        limit=size,
        scope=scope,
        position_of=lambda artifact: {
            "createdAt": pagination.cursor_time(artifact.created_at),
            "id": artifact.id,
        },
    )
    builds = await store.android_builds_for(session, [artifact.id for artifact in page])
    now = datetime.now(timezone.utc)
    return {
        "items": [_artifact_dto(artifact, builds.get(artifact.id), now=now) for artifact in page],
        "page": info,
    }


@router.get("/artifacts/{artifact_id}", tags=["artifacts"])
async def get_artifact(
    artifact_id: str,
    principal: AuthenticatedPrincipal = Depends(require_action(permissions.ARTIFACTS_READ)),
    session: AsyncSession = Depends(get_session),
) -> dict:
    artifact = await store.get_artifact_for_projects(session, artifact_id, visible_projects(principal))
    if artifact is None:
        raise _not_found()
    build = await store.get_android_build(session, artifact.id)
    return _artifact_dto(artifact, build)


@router.post("/artifacts/{artifact_id}/download-token", tags=["artifacts"], status_code=201)
async def mint_download_token(
    artifact_id: str,
    request: Request,
    response: Response,
    principal: AuthenticatedPrincipal = Depends(require_action(permissions.ARTIFACTS_DOWNLOAD)),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Mint a short-lived bearer credential for this artifact's bytes.

    Carries no `Idempotency-Key`, unlike the other writes in this contract. The
    reserve-then-complete flow exists so a lost network cannot produce a second
    *durable* side effect — a second issue, a second message, a double approval.
    A repeated mint produces a second credential that expires in minutes and
    that nothing reconciles against; replaying the first would hand back a token
    with less life left than the caller expects, which is worse than minting
    another. The response is `Cache-Control: no-store` because it carries one.
    """
    artifact = await store.get_artifact_for_projects(session, artifact_id, visible_projects(principal))
    if artifact is None:
        raise _not_found()
    if not store.artifact_is_retained(artifact):
        raise _past_retention()

    token = generate_artifact_download_token()
    ttl = settings.effective_artifact_download_token_ttl_seconds()
    grant = await store.create_artifact_download_token(
        session,
        artifact_id=artifact.id,
        user_id=principal.user_id,
        token=token,
        expires_at=expires_in(ttl),
        # Which sign-in is minting this, so `POST /api/v1/auth/revoke` can
        # delete exactly this grant's download credentials. Re-read from the
        # presented access token rather than carried on `AuthenticatedPrincipal`:
        # widening that model would put a field on every route in the gateway to
        # serve one, and this is a primary-key lookup on a rare endpoint. Null
        # for the grantless browser-OAuth session, which is a value.
        grant_id=await _minting_grant_id(request, session),
    )
    response.headers["Cache-Control"] = "no-store"
    return {
        "artifactId": artifact.id,
        "token": token,
        "tokenType": "Bearer",
        "expiresAt": _iso(grant.expires_at),
        # A path, not a URL: it names no host (an absolute URL would be one more
        # place a deployment's own address is published) and carries no
        # credential (`security-standards.md` §2). The token goes in the
        # `Authorization` header of the request to this path.
        "downloadPath": f"/api/v1/artifacts/{artifact.id}/download",
        "sizeBytes": artifact.size_bytes,
        "sha256": artifact.sha256,
        "contentType": artifact.content_type,
    }


async def _minting_grant_id(request: Request, session: AsyncSession) -> str | None:
    """The grant behind the access token authorizing this mint, or None.

    `require_action` has already accepted the credential by the time this runs,
    so a miss here means a grantless token (the browser OAuth flow issues
    those), not an unauthenticated caller.
    """
    token = bearer_token(request)
    if token is None:
        return None
    item = await store.get_oauth_access_token(session, token)
    return item.grant_id if item is not None else None


async def _artifact_for_download_token(request: Request, artifact_id: str, session: AsyncSession):
    """Resolve the presented download token to the artifact it authorizes.

    Every refusal here is the same `401` with the same message, for the reason
    `gateway/app/api/auth.py:unauthenticated` gives: absent, unknown, expired,
    minted for a different artifact, belonging to an account the operator has
    since disabled or narrowed, or killed by a sign-out — distinguishing them
    tells a holder of a token they were never given whether it was ever real,
    and which artifact it was for. A revoked token's row is *deleted*, so it
    reaches this function as "unknown" and needs no branch of its own.

    The account is re-read from the registry on every download rather than
    trusted from minting time. A five-minute window is small, and it is not
    zero: an operator who disables an account expects the bytes to stop.
    """
    token = bearer_token(request)
    if token is None:
        raise unauthenticated(_DOWNLOAD_TOKEN_REJECTED)

    grant = await store.get_artifact_download_token(session, token)
    if grant is None or grant.artifact_id != artifact_id:
        raise unauthenticated(_DOWNLOAD_TOKEN_REJECTED)

    user = lookup_user(settings.user_registry_file, grant.user_id)
    if user is None or not user.enabled:
        raise unauthenticated(_DOWNLOAD_TOKEN_REJECTED)

    principal = AuthenticatedPrincipal(
        user_id=user.user_id,
        email=user.email,
        roles=user.roles,
        allowed_projects=user.allowed_projects,
        # Deliberately empty: this principal exists to answer "which projects",
        # never "which actions". A download token grants one artifact's bytes
        # and must not be usable to satisfy any `require_action` check.
        scopes=[],
        can_approve_sensitive=False,
        auth_scheme="artifact_download_token",
    )
    artifact = await store.get_artifact_for_projects(session, artifact_id, visible_projects(principal))
    if artifact is None:
        raise unauthenticated(_DOWNLOAD_TOKEN_REJECTED)
    return artifact


@router.get("/artifacts/{artifact_id}/download", tags=["artifacts"])
async def download_artifact(
    artifact_id: str,
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> Response:
    """Stream an artifact's bytes to the holder of a live download token.

    Supports a single `Range`: `206` with `Content-Range` when it is
    satisfiable, `416` with `Content-Range: bytes */size` when it is not, and a
    plain `200` when the header is absent, malformed or asks for something this
    endpoint does not serve — all three are what RFC 9110 §14 permits, and the
    reasoning for each is in
    `gateway/app/services/artifact_storage.py:parse_range_header`.

    Not guarded by `require_action`: it authenticates the download token and
    nothing else. See the module docstring for why the session bearer is not
    what fetches the bytes.
    """
    artifact = await _artifact_for_download_token(request, artifact_id, session)
    if not store.artifact_is_retained(artifact):
        raise _past_retention()

    try:
        path = artifact_storage.resolve_artifact_file(artifact.storage_path)
    except ArtifactContentMissing:
        raise _content_missing(artifact.id, "no_regular_file") from None
    except ArtifactError:
        # A stored path that no longer resolves inside the artifacts root — a
        # symlink, or a root that moved. Reported as missing content rather than
        # as a path problem: the caller has no business learning that a path
        # exists at all, and the operator has the `requestId` — which now
        # actually resolves to a log line, see `_content_missing`.
        raise _content_missing(artifact.id, "escapes_root") from None

    size = path.stat().st_size
    try:
        byte_range = artifact_storage.parse_range_header(request.headers.get("Range"), size)
    except UnsatisfiableRange:
        raise ApiError(
            status_code=416,
            code=VALIDATION_FAILED,
            message="The requested range cannot be satisfied.",
            details=[{"field": "Range", "code": "unsatisfiable", "message": f"This artifact is {size} bytes."}],
            headers={"Content-Range": f"bytes */{size}", "Accept-Ranges": "bytes"},
        ) from None

    headers = {
        "Accept-Ranges": "bytes",
        # `name` is constrained to [A-Za-z0-9._-] at creation
        # (`artifact_types.NAME_RE`), which is what makes interpolating it into
        # a header safe: no quote, no newline, no separator can reach here.
        "Content-Disposition": f'attachment; filename="{artifact.name}"',
        "X-Artifact-Sha256": artifact.sha256,
        # Authorized content behind a short-lived credential: it must not sit in
        # a shared cache once the credential is gone.
        "Cache-Control": "private, no-store",
    }
    if byte_range is None:
        headers["Content-Length"] = str(size)
        status_code = 200
    else:
        headers["Content-Length"] = str(byte_range.length)
        headers["Content-Range"] = f"bytes {byte_range.start}-{byte_range.end}/{size}"
        status_code = 206

    return StreamingResponse(
        artifact_storage.read_chunks(path, byte_range),
        status_code=status_code,
        media_type=artifact.content_type,
        headers=headers,
    )


@router.get("/builds/android", tags=["artifacts"])
async def list_android_builds(
    project: list[str] | None = Query(default=None),
    environment: list[str] | None = Query(default=None),
    package_name: str | None = Query(default=None, alias="packageName", max_length=255),
    cursor: str | None = Query(default=None),
    limit: int | None = Query(default=None),
    principal: AuthenticatedPrincipal = Depends(require_action(permissions.ARTIFACTS_READ)),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """APK artifacts with their build metadata, newest first.

    The same rows `GET /api/v1/artifacts?type=apk` returns, with `android`
    guaranteed present and with the two filters that only exist on the metadata
    (`environment`, `packageName`). Guarded by `artifacts.read`, because an
    Android build is an artifact and a second permission for the same rows would
    be two answers to one question.
    """
    projects = _scoped_projects(principal, project)
    size = pagination.parse_limit(limit)

    scope = pagination.scope_digest(
        ANDROID_BUILDS_ENDPOINT,
        {
            "environment": sorted(environment) if environment else None,
            "packageName": package_name,
            "actor": principal.user_id,
            "projects": sorted(projects) if projects is not None else "*",
        },
    )
    after = None
    if cursor:
        position = pagination.decode_cursor(scope, cursor, expect={"createdAt": str, "id": str})
        after = (position["createdAt"], position["id"])

    rows = await store.list_android_builds_page(
        session,
        project_ids=projects,
        environments=environment,
        package_name=package_name,
        after=after,
        limit=size,
    )
    page, info = pagination.paginate(
        rows,
        limit=size,
        scope=scope,
        position_of=lambda row: {
            "createdAt": pagination.cursor_time(row[0].created_at),
            "id": row[0].id,
        },
    )
    now = datetime.now(timezone.utc)
    return {"items": [_artifact_dto(artifact, build, now=now) for artifact, build in page], "page": info}


@router.get("/builds/android/{build_id}", tags=["artifacts"])
async def get_android_build(
    build_id: str,
    principal: AuthenticatedPrincipal = Depends(require_action(permissions.ARTIFACTS_READ)),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """One Android build, addressed by the id of the artifact it is.

    An artifact that exists but has no APK metadata answers the same `404` as
    one that does not exist: from this endpoint's vocabulary there is no such
    build, and saying "that id is an artifact, just not a build" would describe
    a row the caller asked about under the wrong name.
    """
    artifact = await store.get_artifact_for_projects(session, build_id, visible_projects(principal))
    if artifact is None:
        raise _not_found()
    build = await store.get_android_build(session, artifact.id)
    if build is None:
        raise _not_found()
    return _artifact_dto(artifact, build)
