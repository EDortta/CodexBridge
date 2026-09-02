"""Authentication and authorization for the contract surface.

This module answers two questions for every `/api/v1` request: *who is calling*
(`current_principal`) and *may they do this* (`require_action`). The credentials
themselves are minted by `gateway/app/api/routes/auth.py` — sign-in, refresh,
revocation — and stored in the same table the MCP transport reads, so a token
revoked for one is revoked for both.

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

from gateway.app.api import permissions
from gateway.app.api.errors import PERMISSION_DENIED, UNAUTHENTICATED, ApiError
from gateway.app.api.permissions import Action
from gateway.app.core.config import settings
from gateway.app.core.users import AuthenticatedPrincipal, lookup_user
from gateway.app.db.session import get_session
from gateway.app.services import store


# The one message every rejected credential on this surface gets. A constant
# rather than a convention: the previous cut passed a different string for an
# absent header than for an invalid token, under a docstring promising they were
# the same, and nothing failed. The property that matters — real-but-dead is
# indistinguishable from never-real — held; the claim did not, and a reader
# checking the claim would have stopped at the docstring.
TOKEN_REJECTED = "This endpoint requires a valid bearer token."


def unauthenticated(message: str = TOKEN_REJECTED) -> ApiError:
    """The one shape of a 401 on this surface.

    Every `unauthenticated` response carries `WWW-Authenticate`, and every one
    of them says the same thing whatever went wrong — absent, unknown, expired,
    revoked, or belonging to an account that no longer exists. Distinguishing
    them tells a caller holding a token they were never given whether it was
    ever real.
    """
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
    token = bearer_token(request)
    if token is None:
        raise unauthenticated()

    item = await store.get_oauth_access_token(session, token)
    if item is None:
        # Covers unknown, expired and revoked alike: the store refuses all
        # three, and telling them apart tells a probing caller whether a token
        # was ever real.
        raise unauthenticated()

    user = lookup_user(settings.user_registry_file, item.user_id)
    if user is None or not user.enabled:
        # 401, not 403. The operator disabled the account or removed it, so the
        # credential is dead and the only recovery is to present another one —
        # which is what 401 means and what the client's 401 branch does. A 403
        # here told the client "you are authenticated and not permitted", so it
        # showed a permissions error and kept the dead session; and it made
        # `/api/v1/auth/me` — the one endpoint whose purpose is reporting
        # authorization — answer a status its contract does not declare.
        #
        # It also makes the rule the rest of this surface is documented by
        # actually true: on `/api/v1`, `403` comes from `require_action` and
        # from nowhere else.
        raise unauthenticated()

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


def bearer_token(request: Request) -> str | None:
    """The presented bearer token, or None when the header is absent or not one.

    One reader, because `/api/v1/auth/revoke` needs the token itself rather than
    the principal derived from it, and two parsers of the same header is how one
    of them ends up accepting a form the other does not.
    """
    authorization = request.headers.get("Authorization")
    if not authorization or not authorization.startswith("Bearer "):
        return None
    token = authorization.removeprefix("Bearer ").strip()
    return token or None


def require_action(action: Action):
    """Dependency factory refusing a principal that may not perform `action`.

    Endpoints are guarded by an **action** from `permissions.CATALOGUE`, not by
    a bare scope string. That is what keeps `GET /api/v1/auth/me` honest: the
    report the client uses to decide whether to show a control is produced from
    the same table this guard enforces, so a control the client offers and a
    `403` from the endpoint cannot disagree.
    """

    async def _dependency(
        principal: AuthenticatedPrincipal = Depends(current_principal),
    ) -> AuthenticatedPrincipal:
        if not permissions.is_allowed(principal, action):
            raise ApiError(
                status_code=403,
                code=PERMISSION_DENIED,
                message=(
                    f"This action requires the {action.name!r} permission "
                    f"(scope {action.scope}). GET /api/v1/auth/me reports what "
                    "this actor may do."
                ),
            )
        return principal

    # The action this closure enforces, readable from the outside. A route
    # inventory cannot otherwise tell an *authorization* guard from bare
    # authentication: `_dependency` reaches `current_principal`, so a recursion
    # looking for the latter reports "guarded" for a route that checks no
    # action at all. A council round built exactly that route and walked it
    # past the gate in `tests/integration/test_probes.py`, which now reads this
    # attribute instead of guessing from a callable's name.
    _dependency.guarded_action = action  # type: ignore[attr-defined]
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
