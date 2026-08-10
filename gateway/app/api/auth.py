"""Authentication for the contract surface.

Reuses the OAuth 2.1 access tokens the gateway already issues and the user
registry it already reads, because both exist and work. Issue #4 — device
authorization, refresh, revocation, an endpoint reporting effective permissions —
is a **separate** piece of work and is not implemented here. What this module
provides is the minimum that lets `/api/v1` endpoints exist at all: a request
either carries a valid token belonging to an enabled user, or it does not reach
a handler.

Building `/api/v1/sessions` without this was never an option. A session record
carries the instruction the operator wrote, the project it ran against and its
logs; unauthenticated, the endpoint publishes all of it.

Two rules that shape every read below:

- **Project scope is enforced on the query, not on the response.** Filtering
  after loading is how a `count` or a `page.hasMore` ends up describing rows the
  caller may not see.
- **Invisible is indistinguishable from absent.** A session in a project the
  caller cannot see returns `not_found`, never `permission_denied`: the latter
  confirms the identifier exists, which is what probing is for.
"""

from __future__ import annotations

import json

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from gateway.app.api.errors import PERMISSION_DENIED, UNAUTHENTICATED, ApiError
from gateway.app.core.config import settings
from gateway.app.core.users import AuthenticatedPrincipal, lookup_user
from gateway.app.db.session import get_session
from gateway.app.services import store


READ_SCOPE = "codexbridge.read"
CANCEL_SCOPE = "codexbridge.task.cancel"


def _unauthenticated(message: str) -> ApiError:
    return ApiError(
        status_code=401,
        code=UNAUTHENTICATED,
        message=message,
        headers={"WWW-Authenticate": 'Bearer realm="codex-bridge"'},
    )


async def current_principal(
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> AuthenticatedPrincipal:
    """Resolve the bearer token to a principal, or refuse the request.

    The token is looked up in the same table the MCP transport uses, so a token
    revoked there is revoked here — one credential store, not two.
    """
    authorization = request.headers.get("Authorization")
    if not authorization or not authorization.startswith("Bearer "):
        raise _unauthenticated("This endpoint requires a bearer token.")

    token = authorization.removeprefix("Bearer ").strip()
    item = await store.get_oauth_access_token(session, token)
    if item is None:
        # Covers unknown and expired alike: `store.get_oauth_access_token`
        # filters on expiry, and telling the two apart tells a probing caller
        # whether a token was ever real.
        raise _unauthenticated("The bearer token is not valid.")

    user = lookup_user(settings.user_registry_file, item.user_id) or lookup_user(
        settings.user_registry_file, item.user_email
    )
    if user is None or not user.enabled:
        raise ApiError(
            status_code=403,
            code=PERMISSION_DENIED,
            message="The account for this token is unknown or disabled.",
        )

    principal = AuthenticatedPrincipal(
        user_id=user.user_id,
        email=user.email,
        roles=user.roles,
        allowed_projects=user.allowed_projects,
        scopes=json.loads(item.scopes_json or "[]"),
        can_approve_sensitive=user.can_approve_sensitive,
        auth_scheme="oauth",
    )
    # Recorded for handlers and for anything that runs *after* authentication.
    #
    # NOT for the rate limiter, despite `client_key` preferring an actor bucket:
    # the limiter is a router-level dependency and is solved before this
    # route-level one, so it never sees a principal on these routes and buckets
    # by address. Saying otherwise here was a claim an audit falsified. Making
    # it true means moving the limiter behind authentication, which changes what
    # unauthenticated floods cost — a decision, not a tidy-up.
    request.state.principal = principal
    return principal


def require_scope(scope: str):
    """Dependency factory refusing a principal that lacks `scope`."""

    async def _dependency(
        principal: AuthenticatedPrincipal = Depends(current_principal),
    ) -> AuthenticatedPrincipal:
        if not principal.has_scope(scope):
            raise ApiError(
                status_code=403,
                code=PERMISSION_DENIED,
                message=f"This action requires the {scope} scope.",
            )
        return principal

    return _dependency


def visible_projects(principal: AuthenticatedPrincipal) -> list[str] | None:
    """Project ids the principal may see, or None meaning "no restriction".

    None is returned only for an admin. Returning an empty list for a user with
    no projects is deliberate and different: it must filter everything out
    rather than being mistaken for "unrestricted".
    """
    if principal.is_admin():
        return None
    return list(principal.allowed_projects)
