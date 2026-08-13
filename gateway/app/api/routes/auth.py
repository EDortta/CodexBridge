"""Sign-in, renewal, revocation, and what the actor may actually do.

Issue #4. Four endpoints under `/api/v1/auth`, and they are the credential
lifecycle CodexBridgeMobile needs:

    POST /auth/sign-in   username + password  -> access token + refresh token
    POST /auth/refresh   refresh token        -> a new pair, the old one dead
    POST /auth/revoke    either credential    -> both dead now, not at expiry
    GET  /auth/me        access token         -> actor, scopes, permissions

`gateway/app/api/auth.py` is the other half and does not overlap: this module
*issues* credentials, that one *consumes* them.

## Sign-in, not device authorization

The issue asks for "sign-in **or** device authorization". Device authorization
(RFC 8628) exists for clients that cannot show a keyboard — a TV, a CLI on a
headless box. CodexBridgeMobile is a phone app with a text field, and the
gateway already holds the operator's password hash in `users.json` and already
verifies it for the browser OAuth flow. Adding a device-code table, a polling
endpoint and a verification page to serve a client that can simply ask for the
password would be a second authentication surface to keep correct forever.
`GET /api/version` reports `deviceAuthorization: false`, so the client can see
the difference rather than guess it.

## Why not reuse the OAuth authorization-code flow

It exists, and it is the right flow for ChatGPT: a **third-party** client that
must never see the operator's password. A first-party app of the operator's own
is the case that flow's redirect dance is protecting against nothing in — and it
issues no refresh token at all, which is the renewal this issue is about.

## What every failure here answers

`401 unauthenticated`, with the same message whether the credential was absent,
unknown, wrong, expired, revoked, or belongs to an account that has since been
disabled. Anything finer is a probing oracle: a distinct "expired" tells a
holder of a stolen token that it was once real, and a distinct "no such user"
turns the sign-in form into a user directory. `403` is reserved for an actor who
*is* authenticated and is not permitted, which is what `require_action` raises —
and, since the disabled-account case became a `401`, that is now the only thing
on `/api/v1` that raises one.

## What a token minted here may carry

The account's scopes intersected with `CODEX_BRIDGE_OAUTH_DEFAULT_SCOPES`, never
the account's scopes alone. The browser flow already caps grants that way
(`gateway/app/main.py`), and both flows write to the same `oauth_access_tokens`
table that `POST /mcp` authenticates against: a sign-in token that skipped the
cap would be a live MCP credential carrying scopes the deployment's own
allowlist exists to withhold. One token table, one ceiling.
"""

from __future__ import annotations

import json
from datetime import datetime

from fastapi import APIRouter, Body, Depends, Request, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from gateway.app.api import permissions, timestamps
from gateway.app.api.auth import bearer_token, current_principal, unauthenticated
from gateway.app.core.config import settings
from gateway.app.core.oauth import (
    expires_in,
    generate_access_token,
    generate_grant_id,
    generate_refresh_token,
)
from gateway.app.core.users import (
    AuthenticatedPrincipal,
    authenticate_async,
    lookup_user,
)
from gateway.app.db.session import get_session
from gateway.app.services import store


router = APIRouter(prefix="/api/v1")

# The client identifier recorded on a grant issued here. Fixed rather than taken
# from the request: this is the first-party mobile client, and accepting a
# client id from an unauthenticated body would let a caller label their grant as
# ChatGPT's in the audit trail.
MOBILE_CLIENT_ID = "codexbridge-mobile"

# One message for every way authentication can fail. See the module docstring.
_SIGN_IN_FAILED = "Sign-in failed."
_CREDENTIAL_REJECTED = "The credential is not valid."


class SignInRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    username: str = Field(min_length=1, max_length=255)
    # Bounded because verifying costs a deliberate ~600k PBKDF2 iterations and
    # the body is unauthenticated. The bound is on the field, not on the hash
    # cost: PBKDF2 does not care how long the input is, but the JSON parser and
    # the request log do.
    password: str = Field(min_length=1, max_length=1024)


class RefreshRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    refresh_token: str = Field(alias="refreshToken", min_length=1, max_length=1024)


class RevokeRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    refresh_token: str | None = Field(default=None, alias="refreshToken", max_length=1024)


def _tokens_body(
    *,
    access_token: str,
    refresh_token: str,
    access_expires_at: datetime,
    refresh_expires_at: datetime,
    scopes: list[str],
) -> dict:
    """The one shape sign-in and refresh both return.

    `expiresIn` is present alongside `accessTokenExpiresAt` on purpose: the
    contract tells clients not to do elapsed-time arithmetic against the device
    clock, and a seconds-from-now value is the only form that survives a device
    whose clock is wrong.
    """
    return {
        "tokenType": "Bearer",
        "accessToken": access_token,
        "accessTokenExpiresAt": timestamps.utc_z(access_expires_at),
        "expiresIn": settings.oauth_access_token_ttl_seconds,
        "refreshToken": refresh_token,
        "refreshTokenExpiresAt": timestamps.utc_z(refresh_expires_at),
        "scopes": scopes,
    }


def _no_store(response: Response) -> None:
    """Token responses must not be cached anywhere. RFC 6749 §5.1."""
    response.headers["Cache-Control"] = "no-store"
    response.headers["Pragma"] = "no-cache"


@router.post("/auth/sign-in", tags=["auth"])
async def sign_in(
    body: SignInRequest,
    response: Response,
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Exchange a username and password for an access/refresh pair."""
    # One call, not lookup-then-verify: the constant-cost derivation and the
    # refusal of the published example credential are guards that belong inside
    # the operation, not at whichever caller remembered them.
    #
    # `_async` because the derivation is a few hundred milliseconds of CPU with
    # no `await` in it. Called directly from this handler it holds the event
    # loop, and the limiter's 120/minute/bucket would then buy an unauthenticated
    # caller ~36 s of stalled gateway per minute per address.
    outcome = await authenticate_async(settings.user_registry_file, body.username, body.password)

    if not outcome.ok or outcome.user is None:
        # Recorded against the resolved user when there is one. The string the
        # caller typed is never stored: it is unvalidated input, and an operator
        # who mistypes their password into the username field would otherwise
        # have it committed to the audit trail.
        await store.record_auth_event(
            session,
            user_id=outcome.user.user_id if outcome.user else "unknown",
            event_type="auth.sign_in_failed",
            payload={"reason": outcome.reason, "client_id": MOBILE_CLIENT_ID},
        )
        raise unauthenticated(_SIGN_IN_FAILED)

    user = outcome.user
    # Intersected with the server allowlist, exactly as the browser flow does.
    # See the module docstring: both issuers write to one token table, so a
    # second issuer with a second ceiling is no ceiling.
    scopes = sorted(set(user.scopes) & settings.oauth_scopes())
    grant_id = generate_grant_id()
    access_token = generate_access_token()
    refresh_token = generate_refresh_token()
    access_expires_at = expires_in(settings.oauth_access_token_ttl_seconds)
    refresh_expires_at = expires_in(settings.oauth_refresh_token_ttl_seconds)

    await store.issue_auth_grant(
        session,
        grant_id=grant_id,
        access_token=access_token,
        refresh_token=refresh_token,
        client_id=MOBILE_CLIENT_ID,
        user_id=user.user_id,
        scopes=scopes,
        access_expires_at=access_expires_at,
        refresh_expires_at=refresh_expires_at,
        event_type="auth.signed_in",
    )

    _no_store(response)
    return _tokens_body(
        access_token=access_token,
        refresh_token=refresh_token,
        access_expires_at=access_expires_at,
        refresh_expires_at=refresh_expires_at,
        scopes=scopes,
    )


@router.post("/auth/refresh", tags=["auth"])
async def refresh(
    body: RefreshRequest,
    response: Response,
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Rotate a refresh token into a new pair.

    Three properties, each of which has a failure mode behind it:

    - **the presented token is consumed**, so a captured copy is worth one use
      to whoever gets there first and a lost race is detectable;
    - **a consumed token presented again revokes the whole grant.** Replay and
      theft look identical from here, and the safe reading of the ambiguity is
      theft — the operator signs in again, which is cheap, instead of sharing a
      session with whoever holds the copy, which is not;
    - **the registry is re-read.** Scopes are intersected with what the user has
      *now*, and a disabled or deleted account ends the grant. A 30-day refresh
      token that kept minting yesterday's permissions would make disabling an
      account take a month.
    """
    status, item = await store.inspect_refresh_token(session, body.refresh_token)

    if status == store.REFRESH_REUSED and item is not None:
        await store.revoke_auth_grant(
            session,
            grant_id=item.grant_id,
            user_id=item.user_id,
            reason="refresh_token_reuse",
        )
        raise unauthenticated(_CREDENTIAL_REJECTED)

    if status != store.REFRESH_VALID or item is None:
        raise unauthenticated(_CREDENTIAL_REJECTED)

    user = lookup_user(settings.user_registry_file, item.user_id)
    if user is None or not user.enabled:
        await store.revoke_auth_grant(
            session,
            grant_id=item.grant_id,
            user_id=item.user_id,
            reason="account_unavailable",
        )
        raise unauthenticated(_CREDENTIAL_REJECTED)

    granted = set(json.loads(item.scopes_json or "[]"))
    # Intersection, never union: a rotation may narrow what the grant carries
    # and must never widen it, however the registry or the allowlist changed.
    # The server allowlist is one of the three terms so that narrowing
    # `CODEX_BRIDGE_OAUTH_DEFAULT_SCOPES` takes effect on the next rotation
    # rather than at the end of a 30-day grant.
    scopes = sorted(granted & set(user.scopes) & settings.oauth_scopes())

    access_token = generate_access_token()
    refresh_token = generate_refresh_token()
    access_expires_at = expires_in(settings.oauth_access_token_ttl_seconds)
    # Carried forward, not extended: the grant has an absolute lifetime, so a
    # stolen refresh token cannot be rotated into a session that never ends.
    refresh_expires_at = item.expires_at

    rotated = await store.issue_auth_grant(
        session,
        grant_id=item.grant_id,
        access_token=access_token,
        refresh_token=refresh_token,
        client_id=item.client_id,
        user_id=user.user_id,
        scopes=scopes,
        access_expires_at=access_expires_at,
        refresh_expires_at=refresh_expires_at,
        event_type="auth.token_refreshed",
        rotated_from_hash=item.token_hash,
    )
    if not rotated:
        # Another request consumed the same refresh token between the check
        # above and the write. Exactly one of the two may hold the result, and
        # this one lost — answered like any other rejected credential.
        raise unauthenticated(_CREDENTIAL_REJECTED)

    _no_store(response)
    return _tokens_body(
        access_token=access_token,
        refresh_token=refresh_token,
        access_expires_at=access_expires_at,
        refresh_expires_at=refresh_expires_at,
        scopes=scopes,
    )


@router.post("/auth/revoke", tags=["auth"])
async def revoke(
    request: Request,
    response: Response,
    body: RevokeRequest | None = Body(default=None),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Sign out: end the grant now rather than at expiry.

    Either credential authorizes its own revocation — the access token in the
    header, or the refresh token in the body. Both are accepted because the
    common reason to sign out on a phone is that the access token has already
    expired, and requiring a live one would mean the only way to end a session
    is to wait for it.

    Revoking a grant revokes **both** its tokens, not just the one presented. A
    sign-out that leaves the other half usable for the rest of its TTL is the
    failure this endpoint exists to prevent.

    Idempotent, and deliberately incurious: an unknown, expired or
    already-revoked credential is answered `200` like any other, per RFC 7009.
    The response says the credential cannot be used, which is true in every one
    of those cases, and says nothing about which one it was.

    **Idempotent includes the second call.** A client holding only an access
    token signs out, the connection drops, the client retries: the token is
    revoked by then, so a store lookup that comes back empty must still be a
    `200`. Answering `401` there turned a completed sign-out into an
    authentication failure for every client with the usual global 401
    interceptor — the one shape this endpoint's own contract says cannot happen.
    Presenting *nothing* is still a `401`, because that is an error about the
    request rather than about a credential.
    """
    presented_refresh = body.refresh_token if body else None
    token = bearer_token(request)

    revoked = {"access_tokens": 0, "refresh_tokens": 0}
    handled = False

    if presented_refresh:
        # `_status` is deliberately not consulted. A refresh token this store
        # has already classified as consumed, revoked or expired still ends the
        # grant it belongs to, and that is a decision rather than an oversight:
        #
        # - it is the fail-closed direction (`design-standards.md` §6). The
        #   alternative — refusing to act on a spent token — makes a client's
        #   sign-out report success while the session stays alive, which is the
        #   confidentiality failure this endpoint exists to prevent;
        # - the reachable abuse is bounded. A token addresses only the grant it
        #   was issued under; rotation carries that `grant_id` forward, but a
        #   *new* sign-in mints a new one, so a recovered token is worth one
        #   forced re-authentication of one grant and nothing else. No data is
        #   read, and the operator's recovery is to sign in again;
        # - `/refresh` already reads a replayed token as theft and revokes for
        #   it. Reading the same token as harmless here would make the two
        #   endpoints disagree about the same credential.
        #
        # Residual risk, accepted: an attacker holding any refresh token ever
        # issued under a live grant can force one re-authentication, without
        # authenticating. Recorded in `docs/security.md`.
        _status, item = await store.inspect_refresh_token(session, presented_refresh)
        if item is not None:
            revoked = await store.revoke_auth_grant(
                session,
                grant_id=item.grant_id,
                user_id=item.user_id,
                reason="signed_out",
            )
        # An unknown refresh token is still a handled request: answering 401
        # would tell the caller their token was never real, and would make a
        # client's sign-out fail on the one input it cannot correct.
        handled = True

    if token:
        item = await store.get_oauth_access_token(session, token)
        if item is not None:
            if item.grant_id:
                counts = await store.revoke_auth_grant(
                    session,
                    grant_id=item.grant_id,
                    user_id=item.user_id,
                    reason="signed_out",
                )
            else:
                # Issued by the browser OAuth flow: no refresh chain exists, so
                # revocation stops at this token.
                counts = await store.revoke_access_token(
                    session,
                    token=token,
                    user_id=item.user_id,
                    reason="signed_out",
                )
            revoked = {key: revoked[key] + counts[key] for key in revoked}
        # Handled whether or not the store still recognises it — see the
        # docstring. A token the store refuses is a token that cannot be used,
        # which is exactly what this response reports.
        handled = True

    if not handled:
        # Nothing usable was presented: no body, and no access token this store
        # recognises. There is nothing to revoke and nothing to report, so this
        # is an error about the request rather than about a credential.
        #
        # A client whose access token has already expired signs out with the
        # refresh token, which is the half that keeps the grant alive.
        raise unauthenticated("Present an access token or a refresh token to revoke.")

    _no_store(response)
    return {
        "revoked": True,
        "revokedAt": timestamps.now_z(),
        "accessTokensRevoked": revoked["access_tokens"],
        "refreshTokensRevoked": revoked["refresh_tokens"],
    }


@router.get("/auth/me", tags=["auth"])
async def current_actor(
    response: Response,
    principal: AuthenticatedPrincipal = Depends(current_principal),
) -> dict:
    """Who is calling, and what this build will let them do.

    The `permissions` array is the point of the endpoint: it lets the client
    decide whether to *offer* a control instead of offering it and translating
    the `403`. It is produced from `permissions.CATALOGUE`, which is the same
    table `require_action` enforces, so the list cannot promise something the
    endpoints refuse.

    `projects.all` is a flag rather than an empty-list convention. Internally
    "no restriction" and "no projects" are `None` and `[]`, one character apart,
    and collapsing them grants everything — that ambiguity is not worth
    exporting to a client.
    """
    response.headers["Cache-Control"] = "no-store"
    return {
        "actor": {
            "kind": "user",
            "id": principal.user_id,
            "email": principal.email,
        },
        "roles": list(principal.roles),
        "scopes": sorted(set(principal.scopes)),
        "projects": {
            "all": principal.is_admin(),
            "ids": [] if principal.is_admin() else list(principal.allowed_projects),
        },
        "permissions": permissions.report_for(principal),
        "authScheme": principal.auth_scheme,
        "generatedAt": timestamps.now_z(),
    }
