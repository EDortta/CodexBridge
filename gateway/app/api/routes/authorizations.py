"""The explicit operator grant: `POST .../authorize` and `.../revoke`.

Issue #73 Stage 4 (WK-20260902-gh73-authorization-plane). Stage 3
(`routes/discovery.py`) shipped the first real writes to
`project_authorizations` -- adoption's own `autoAuthorize`/`grantCapabilities`
paths. This module is the OTHER way that table gets written: a human,
independent of any discovery flow, directly stating what capabilities one
Bridge Node has on one project. Separated from `routes/discovery.py` rather
than folded into it because the two are different operator actions with
different preconditions -- adoption requires a `discovered_resources` row to
act on; this requires only a node and a project that already exist.

## Enforcement lives elsewhere, on purpose

This module only WRITES the authorization. It never reads it back to decide
whether a task may run -- that is `gateway/app/services/store.py:
effective_task_modes`, called from `create_task` at the one spot that has
always decided this, and (independently) the executor's own
`agent/codex_bridge_agent/service.py:_handle_dispatch`. A grant recorded here
takes effect the next time either of those reads `project_authorizations`;
this module has no cache and no side channel to either of them.

## The privilege ladder

`NODES_AUTHORIZATIONS_MANAGE` (`permissions.py`) is the base administrative
gate, same `codexbridge.admin` posture as `NODES_READ`/
`NODES_DISCOVERIES_DECIDE`. Granting `modify` or `deliver` crosses a second
gate -- `can_approve_sensitive` or `is_admin()`, the same shape
`DECISIONS_DECIDE` already has -- but that second gate depends on WHICH
capabilities the request names, a fact `require_action`'s dependency cannot
see before the body is parsed. So `authorize_node_project` below calls
`permissions.is_allowed` a SECOND time, after parsing the body, passing
`capabilities=payload.capabilities` -- the rule itself still lives entirely
inside `is_allowed`, never as a second `if` built here. See that function's
own docstring.
"""

from __future__ import annotations

import json

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from gateway.app.api import permissions, timestamps
from gateway.app.api.auth import require_action
from gateway.app.api.errors import NOT_FOUND, PERMISSION_DENIED, ApiError
from gateway.app.core.users import AuthenticatedPrincipal
from gateway.app.db.session import get_session
from gateway.app.models.entities import ProjectModel
from gateway.app.services import store
from shared.protocol import Capability


router = APIRouter(prefix="/api/v1")


def _node_not_found(node_id: str) -> ApiError:
    return ApiError(status_code=404, code=NOT_FOUND, message=f"No such node: {node_id!r}.")


def _project_not_found(project_id: str) -> ApiError:
    return ApiError(status_code=404, code=NOT_FOUND, message=f"No such project: {project_id!r}.")


def _no_active_authorization(node_id: str, project_id: str) -> ApiError:
    return ApiError(
        status_code=404,
        code=NOT_FOUND,
        message=f"No active authorization for node {node_id!r} and project {project_id!r}.",
    )


def _sensitive_capability_denied() -> ApiError:
    return ApiError(
        status_code=403,
        code=PERMISSION_DENIED,
        message=(
            "Granting 'modify' or 'deliver' requires can_approve_sensitive or "
            "admin. GET /api/v1/auth/me reports what this actor may do."
        ),
    )


class AuthorizeNodeProjectRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    capabilities: list[Capability] = Field(default_factory=list)


def _authorization_dto(row) -> dict:
    return {
        "nodeId": row.node_id,
        "projectId": row.project_id,
        "capabilities": json.loads(row.capabilities_json or "[]"),
        "grantedBy": row.granted_by,
        "grantedAt": timestamps.utc_z(row.granted_at),
        "revokedAt": timestamps.utc_z(row.revoked_at),
    }


async def _require_node_and_project(session: AsyncSession, node_id: str, project_id: str) -> None:
    """404 before anything is written -- same "do not confirm what the caller

    cannot see" posture `routes/nodes.py`/`routes/discovery.py` already
    document. Checked here, once, rather than inside `store.grant_project_
    authorization`/`revoke_project_authorization`, which trust their callers
    the same way `adopt_discovered_resource`'s helpers trust theirs.
    """
    if await store.get_node(session, node_id) is None:
        raise _node_not_found(node_id)
    if await session.get(ProjectModel, project_id) is None:
        raise _project_not_found(project_id)


@router.post("/nodes/{node_id}/projects/{project_id}/authorize", tags=["authorizations"])
async def authorize_node_project(
    node_id: str,
    project_id: str,
    payload: AuthorizeNodeProjectRequest,
    principal: AuthenticatedPrincipal = Depends(require_action(permissions.NODES_AUTHORIZATIONS_MANAGE)),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Grant `payload.capabilities` to `node_id` on `project_id`.

    Overwrites the pair's standing authorization rather than merging with
    whatever it held before -- an operator calling this is stating the
    authorization they want NOW (`store.grant_project_authorization`'s own
    docstring). A previously revoked row is reactivated in place, never
    duplicated: `project_authorizations_node_project_idx` allows only one
    non-revoked row per pair.

    Requesting `modify` or `deliver` crosses the second gate this module's
    own docstring describes -- `403 permission_denied` for a principal
    without `can_approve_sensitive`/admin, even though the base
    `nodes.authorizations.manage` scope already let the request past
    `require_action` above.
    """
    await _require_node_and_project(session, node_id, project_id)
    if not permissions.is_allowed(
        principal, permissions.NODES_AUTHORIZATIONS_MANAGE, capabilities=payload.capabilities
    ):
        raise _sensitive_capability_denied()

    row = await store.grant_project_authorization(
        session,
        node_id=node_id,
        project_id=project_id,
        capabilities=payload.capabilities,
        granted_by=f"operator:{principal.user_id}",
    )
    return _authorization_dto(row)


@router.post("/nodes/{node_id}/projects/{project_id}/revoke", tags=["authorizations"])
async def revoke_node_project(
    node_id: str,
    project_id: str,
    principal: AuthenticatedPrincipal = Depends(require_action(permissions.NODES_AUTHORIZATIONS_MANAGE)),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Revoke the active authorization for `node_id` on `project_id`.

    No second gate here -- taking capability AWAY is never the escalation
    `is_allowed`'s extra condition guards against, only granting `modify`/
    `deliver` is. `404` when there is no active row to revoke, the same
    "nothing to confirm" posture the rest of this contract already applies to
    an absent id.
    """
    await _require_node_and_project(session, node_id, project_id)
    row = await store.revoke_project_authorization(
        session, node_id=node_id, project_id=project_id, revoked_by=f"operator:{principal.user_id}"
    )
    if row is None:
        raise _no_active_authorization(node_id, project_id)
    return _authorization_dto(row)
