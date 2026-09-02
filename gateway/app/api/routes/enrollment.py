"""Node enrollment — issue #76's minimal cut.

Before this module, admitting a new CodexBridge installation meant hand-
editing `registry.json`, inventing a machine token in clear text, and
restarting the gateway for it to take effect; `/agent/ws` closed `4404` for
any executor id not already in that file. "Revoking" access meant deleting
the line and restarting — and a socket that was already open when the
operator did that kept working regardless, because nothing ever told it to
stop. This module is the three routes that make each of those a real,
gated, API-driven decision instead of a file edit plus a restart:

- `POST /nodes/invite` mints a bearer credential an operator hands to
  whoever is standing up the new machine.
- `POST /nodes/enroll` redeems it — no principal, because the node presenting
  it has no credential of its own yet; the invite itself is the gate.
- `POST /nodes/{id}/revoke` ends a node's credential and closes its live
  socket in the same request, so revoking is not a promise kept only at the
  node's next reconnect attempt.

## Decisions this module does not relitigate

1. The invite is a **bearer** token with a 15-minute TTL. It is not bound to
   a claimed hostname or machine identity — `migrations/0009_control_plane.sql`
   already refused to trust a hostname for node identity, because it is
   mutable and spoofable. The TTL is the actual boundary.
2. `POST /nodes/enroll` reconnecting after an offline period behaves exactly
   as it does today — reconnect with backoff, unchanged. This module does
   not touch that path.
3. The invite's raw value appears exactly once: in `POST /nodes/invite`'s
   response body. Never in `audit_events` (`store.create_node_invite` records
   only `created_by` and `display_name_hint`), never in a log line.
4. Revoking never touches a node's local checkouts. It ends the credential
   and closes the socket; the files on that machine are the operator's
   business, not this API's.

## Out of scope for this cut (issue #76's larger arc)

Token rotation, the full `invited`/`suspended` state machine, and binding an
invite to a claimed machine identity are explicitly not here. See
`migrations/0010_node_enrollment.sql` for what `admission_state` values this
cut actually writes.
"""

from __future__ import annotations

import secrets
from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from gateway.app.api import permissions, timestamps
from gateway.app.api.auth import require_action
from gateway.app.api.errors import NOT_FOUND, VALIDATION_FAILED, ApiError
from gateway.app.core.users import AuthenticatedPrincipal
from gateway.app.db.session import get_session
from gateway.app.services import store


router = APIRouter(prefix="/api/v1")

# Decision #1 above. Fixed rather than an operator-tunable setting: the issue
# settled on 15 minutes specifically, and nothing in this cut's scope calls
# for a second knob to get that decision wrong with.
INVITE_TOKEN_TTL_SECONDS = 15 * 60


def _iso(value: datetime | None) -> str | None:
    return timestamps.utc_z(value)


def _invite_expired_or_used() -> ApiError:
    """One shape for every reason an invite may not be redeemed.

    Unknown, already-consumed and expired all answer identically — the same
    "real-but-dead is indistinguishable from never-real" rule
    `gateway/app/api/auth.py:unauthenticated` applies to bearer tokens.
    Telling them apart would tell an unauthenticated, probing caller whether
    a guessed invite token was ever issued.
    """
    return ApiError(
        status_code=400,
        code=VALIDATION_FAILED,
        message="This invite token is invalid, expired, or already used.",
        details=[{"field": "/inviteToken", "code": "invalid", "message": "Invite may not be redeemed."}],
    )


def _not_found() -> ApiError:
    return ApiError(status_code=404, code=NOT_FOUND, message="No such node.")


class NodeInviteRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    display_name_hint: str | None = Field(default=None, max_length=255, alias="displayNameHint")


class NodeEnrollRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    invite_token: str = Field(min_length=1, max_length=4096, alias="inviteToken")
    display_name: str = Field(min_length=1, max_length=255, alias="displayName")


@router.post("/nodes/invite", tags=["nodes"], status_code=201)
async def invite_node(
    body: NodeInviteRequest,
    principal: AuthenticatedPrincipal = Depends(require_action(permissions.NODES_INVITE)),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Issue a one-time enrollment invite. The raw token is returned here and
    nowhere else — see the module docstring, decision #3."""
    token = secrets.token_urlsafe(32)
    invite = await store.create_node_invite(
        session,
        token=token,
        created_by=principal.user_id,
        display_name_hint=body.display_name_hint,
        ttl_seconds=INVITE_TOKEN_TTL_SECONDS,
    )
    return {
        "id": invite.id,
        "inviteToken": token,
        "expiresAt": _iso(invite.expires_at),
    }


@router.post("/nodes/enroll", tags=["nodes"], status_code=201)
async def enroll_node(
    body: NodeEnrollRequest,
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Redeem an invite and create the Executor+Node it authorizes.

    No `require_action` dependency: the node presenting `inviteToken` has no
    bearer credential of its own to authenticate with yet — that is exactly
    what this call mints. The invite itself is the gate (decision #2 of the
    module docstring). Rate-limited the same way `POST /oauth/authorize`'s
    submit route is: this is the only other endpoint in this codebase that
    mints a credential for an unauthenticated caller, and it follows that
    precedent rather than inventing a second one — see the shared
    `RateLimitDependency` applied where this router is included
    (`gateway/app/main.py`).
    """
    machine_token = secrets.token_urlsafe(48)
    result = await store.enroll_node(
        session,
        invite_token=body.invite_token,
        display_name=body.display_name,
        machine_token=machine_token,
    )
    if result is None:
        raise _invite_expired_or_used()
    node, executor = result
    return {
        "nodeId": node.id,
        "displayName": node.display_name,
        "machineToken": machine_token,
    }


@router.post("/nodes/{node_id}/revoke", tags=["nodes"])
async def revoke_node(
    node_id: str,
    principal: AuthenticatedPrincipal = Depends(require_action(permissions.NODES_REVOKE)),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """End `node_id`'s credential and close its live socket in this request.

    The two are not independent: `store.revoke_node` only stops the *next*
    handshake from succeeding, and `AgentHub.force_close` only closes what
    happens to be open right now. Calling just one of them is what issue #76
    calls "revoking is theatre" — a socket open at the moment of revocation
    would otherwise keep working until it disconnected on its own.
    """
    node = await store.revoke_node(session, node_id)
    if node is None:
        raise _not_found()
    from gateway.app.main import hub  # imported late: main includes this router

    closed = await hub.force_close(node_id)
    return {
        "id": node.id,
        "admissionState": node.admission_state,
        "enabled": node.enabled,
        "connectionClosed": closed,
    }
