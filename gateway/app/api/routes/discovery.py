"""Discovered resources: the panel's half of "the node proposes, the panel adopts".

WK-20260902-gh73-discovery-adoption, issue #73 Stage 3 (adoption half). The
report half (`docs/control-plane.md`, "Stage 3 -- o nó propõe, o painel
adota") shipped `discovered_resources` and the branch in `gateway/app/main.py`
that fills it, writing nothing else -- by construction, not convention. This
module is the other half: the only REST surface that may turn one of those
rows into a `ProjectModel`, a `WorkspaceBindingModel`, a `ScmAssociationModel`,
or a `ProjectAuthorizationModel`, and it does so through
`gateway/app/services/store.py:adopt_discovered_resource`/
`deny_discovered_resource` exclusively -- see those functions' own docstrings
for the full invariant.

## Why this is administrative, not project-scoped

A discovered candidate is not scoped to any project the caller already sees --
often there is no project yet, that is the whole point of the adoption
decision. `NODES_DISCOVERIES_READ`/`NODES_DISCOVERIES_DECIDE` therefore follow
`routes/nodes.py`'s precedent (`NODES_READ`): fleet-wide, administrative,
`codexbridge.admin`, never `visible_projects`-scoped.

## `resourcePath`/`rootPath` are the one exception on this contract

`docs/api/README.md` ("Fields that must never ship") forbids a server
filesystem path in any response, with one standing, pre-registered exception:
`docs/control-plane.md` names it explicitly ("resource_key é dado sensível...
quando a rota de adoção existir, cai na mesma regra de local_path") for
exactly this endpoint. `resourcePath` (the candidate's absolute path,
`migrations/0013_discovery_resource_key_hash.sql`) and `rootPath` (the
discovery root it came from) are returned here and ONLY here, guarded by the
same administrative scope as `NODES_READ`. The internal `resource_key` hash
itself is not part of this DTO at all -- it is a lookup key for
`record_discovery_report`, not information an operator decides anything from.

## Pagination

`GET .../discovered-resources` is cursor-paginated, unlike `GET /api/v1/nodes`
(unpaginated because the fleet is small and operator-curated). That reasoning
does not extend here: a single real operator root has reported 247 candidates
in one scan (`docs/control-plane.md`), so this follows `routes/projects.py`'s
cursor idiom instead.
"""

from __future__ import annotations

import json

from fastapi import APIRouter, Depends, Header, Query, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from gateway.app.api import idempotency, pagination, permissions, timestamps
from gateway.app.api.auth import require_action
from gateway.app.api.errors import CONFLICT, NOT_FOUND, PERMISSION_DENIED, VALIDATION_FAILED, ApiError
from gateway.app.core.users import AuthenticatedPrincipal
from gateway.app.db.session import get_session
from gateway.app.services import store
from gateway.app.services.discovery_types import DiscoveryAdoptionError
from shared.protocol import Capability, DiscoveredState


router = APIRouter(prefix="/api/v1")

DISCOVERED_RESOURCES_ENDPOINT = "/api/v1/discovered-resources"

_STATE_VALUES = {state.value for state in DiscoveredState}


def _iso(value) -> str | None:
    return timestamps.utc_z(value)


def _node_not_found() -> ApiError:
    return ApiError(status_code=404, code=NOT_FOUND, message="No such node.")


def _resource_not_found() -> ApiError:
    return ApiError(status_code=404, code=NOT_FOUND, message="No such discovered resource.")


def _invalid_state() -> ApiError:
    return ApiError(
        status_code=400,
        code=VALIDATION_FAILED,
        message=f"state must be one of {sorted(_STATE_VALUES)}.",
        details=[{"field": "?state", "code": "invalid_enum", "message": "Unknown discovery state."}],
    )


def _not_decidable(resource_id: str, state: str) -> ApiError:
    return ApiError(
        status_code=409,
        code=CONFLICT,
        message=f"Discovered resource {resource_id!r} is {state!r} and cannot be decided again.",
    )


def _adoption_error(exc: DiscoveryAdoptionError) -> ApiError:
    return ApiError(
        status_code=400,
        code=VALIDATION_FAILED,
        message=exc.message,
        details=[{"field": exc.field, "code": exc.code, "message": exc.message}],
    )


def _discovered_resource_dto(row) -> dict:
    evidence = json.loads(row.evidence_json or "{}")
    return {
        "id": row.id,
        "nodeId": row.node_id,
        "kind": row.kind,
        "state": row.state,
        "projectId": row.project_id,
        # Sensitive filesystem data -- see this module's own docstring for
        # why this endpoint, and only this endpoint, may return them.
        "resourcePath": row.resource_path,
        "rootPath": row.root_path,
        "suggestedProjectId": evidence.get("suggested_project_id"),
        "suggestedName": evidence.get("suggested_name"),
        "remoteUrl": evidence.get("remote_url"),
        "head": evidence.get("head"),
        "dirty": evidence.get("dirty"),
        "firstSeenAt": _iso(row.first_seen_at),
        "lastSeenAt": _iso(row.last_seen_at),
        "decidedBy": row.decided_by,
        "decidedAt": _iso(row.decided_at),
    }


class NewProjectSpec(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    project_id: str = Field(alias="projectId", min_length=1, max_length=128)
    name: str = Field(min_length=1, max_length=255)


class AdoptDiscoveredResourceRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    project_id: str | None = Field(default=None, alias="projectId", min_length=1, max_length=128)
    new_project: NewProjectSpec | None = Field(default=None, alias="newProject")
    grant_capabilities: list[Capability] = Field(default_factory=list, alias="grantCapabilities")


@router.get("/nodes/{node_id}/discovered-resources", tags=["discovery"])
async def list_discovered_resources(
    node_id: str,
    response: Response,
    state: str | None = Query(default=None),
    cursor: str | None = Query(default=None),
    limit: int | None = Query(default=None),
    principal: AuthenticatedPrincipal = Depends(require_action(permissions.NODES_DISCOVERIES_READ)),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """One node's discovered candidates, cursor-paginated, newest-id last.

    404 for an unknown node id, the same "do not confirm what the caller
    cannot see" posture `routes/nodes.py` already documents -- there is no
    project scope to hide it behind here either, the id simply is not
    present.
    """
    if await store.get_node(session, node_id) is None:
        raise _node_not_found()
    if state is not None and state not in _STATE_VALUES:
        raise _invalid_state()

    size = pagination.parse_limit(limit)
    scope = pagination.scope_digest(
        f"{DISCOVERED_RESOURCES_ENDPOINT}:{node_id}", {"state": state}
    )
    after_id = None
    if cursor:
        after_id = pagination.decode_cursor(scope, cursor, expect={"id": str})["id"]

    rows = await store.list_discovered_resources_page(
        session, node_id, state=state, after=after_id, limit=size
    )
    page, info = pagination.paginate(rows, limit=size, scope=scope, position_of=lambda row: {"id": row.id})
    return {"items": [_discovered_resource_dto(row) for row in page], "page": info}


@router.post("/discovered-resources/{resource_id}/adopt", tags=["discovery"])
async def adopt_discovered_resource(
    resource_id: str,
    payload: AdoptDiscoveredResourceRequest,
    response: Response,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    principal: AuthenticatedPrincipal = Depends(require_action(permissions.NODES_DISCOVERIES_DECIDE)),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Bind a discovered candidate to a project (existing or new).

    `project_id` XOR `new_project` -- exactly one, enforced again inside
    `store.adopt_discovered_resource` because the guard belongs on the
    operation, not the caller. When the candidate's `rootPath` matches a
    `DiscoveryRoot` with `auto_authorize` on this node's registration, or when
    `grantCapabilities` is given, the resulting `project_authorizations` row
    is granted here -- never by the node itself (see the module docstring).
    """
    # The same privilege ladder the dedicated authorize route applies
    # (`routes/authorizations.py`). Adoption writes `project_authorizations`
    # directly through `grantCapabilities`, so gating only that route would
    # leave a second door to `modify`/`deliver` standing open, reachable by
    # exactly the principal the ladder exists to stop: one whose token carries
    # `codexbridge.admin` for fleet visibility without the account being
    # trusted for a sensitive grant. Checked before the idempotency claim, so
    # a refused request never consumes a key.
    if not permissions.is_allowed(
        principal, permissions.NODES_DISCOVERIES_DECIDE, capabilities=payload.grant_capabilities
    ):
        raise ApiError(
            status_code=403,
            code=PERMISSION_DENIED,
            message=(
                "Granting 'modify' or 'deliver' requires can_approve_sensitive or "
                "admin. GET /api/v1/auth/me reports what this actor may do."
            ),
        )

    endpoint = f"{DISCOVERED_RESOURCES_ENDPOINT}/{{resourceId}}/adopt"
    fingerprint = idempotency.fingerprint(
        f"adopt:{resource_id}:{payload.project_id}:"
        f"{payload.new_project.project_id if payload.new_project else ''}:"
        f"{sorted(c.value for c in payload.grant_capabilities)}".encode()
    )
    claim = None
    if idempotency_key:
        outcome = await idempotency.reserve(
            session,
            key=idempotency_key,
            endpoint=endpoint,
            actor_id=principal.user_id,
            request_fingerprint=fingerprint,
        )
        if isinstance(outcome, idempotency.ReplayedResponse):
            response.status_code = outcome.status_code
            response.headers["Idempotent-Replay"] = "true"
            return outcome.body
        claim = outcome

    try:
        row = await store.adopt_discovered_resource(
            session,
            resource_id,
            project_id=payload.project_id,
            new_project_id=payload.new_project.project_id if payload.new_project else None,
            new_project_name=payload.new_project.name if payload.new_project else None,
            grant_capabilities=payload.grant_capabilities,
            actor_user_id=principal.user_id,
        )
    except DiscoveryAdoptionError as exc:
        if claim is not None:
            await idempotency.release(session, key=idempotency_key, endpoint=endpoint, actor_id=principal.user_id, claim=claim)
        raise _adoption_error(exc) from exc
    except ValueError as exc:
        if claim is not None:
            await idempotency.release(session, key=idempotency_key, endpoint=endpoint, actor_id=principal.user_id, claim=claim)
        if str(exc) == "discovered_resource_not_found":
            raise _resource_not_found() from exc
        if str(exc) == "discovered_resource_not_decidable":
            # The row exists; re-fetch only to report its current state.
            existing = await store.get_discovered_resource(session, resource_id)
            raise _not_decidable(resource_id, existing.state if existing else "unknown") from exc
        raise
    except Exception:
        if claim is not None:
            await idempotency.release(session, key=idempotency_key, endpoint=endpoint, actor_id=principal.user_id, claim=claim)
        raise

    body = _discovered_resource_dto(row)
    if claim is not None:
        await idempotency.complete(
            session,
            key=idempotency_key,
            endpoint=endpoint,
            actor_id=principal.user_id,
            status_code=200,
            body=body,
            claim=claim,
            request_fingerprint=fingerprint,
        )
    return body


@router.post("/discovered-resources/{resource_id}/deny", tags=["discovery"])
async def deny_discovered_resource(
    resource_id: str,
    response: Response,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    principal: AuthenticatedPrincipal = Depends(require_action(permissions.NODES_DISCOVERIES_DECIDE)),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Refuse a discovered candidate. "Ignore" is a UI filter over `DISCOVERED`/

    `STALE`, not a sixth state -- `shared.protocol.DiscoveredState` names
    exactly five, and this endpoint only ever writes `DENIED`.
    """
    endpoint = f"{DISCOVERED_RESOURCES_ENDPOINT}/{{resourceId}}/deny"
    fingerprint = idempotency.fingerprint(f"deny:{resource_id}".encode())
    claim = None
    if idempotency_key:
        outcome = await idempotency.reserve(
            session,
            key=idempotency_key,
            endpoint=endpoint,
            actor_id=principal.user_id,
            request_fingerprint=fingerprint,
        )
        if isinstance(outcome, idempotency.ReplayedResponse):
            response.status_code = outcome.status_code
            response.headers["Idempotent-Replay"] = "true"
            return outcome.body
        claim = outcome

    try:
        row = await store.deny_discovered_resource(session, resource_id, actor_user_id=principal.user_id)
    except ValueError as exc:
        if claim is not None:
            await idempotency.release(session, key=idempotency_key, endpoint=endpoint, actor_id=principal.user_id, claim=claim)
        if str(exc) == "discovered_resource_not_found":
            raise _resource_not_found() from exc
        if str(exc) == "discovered_resource_not_decidable":
            existing = await store.get_discovered_resource(session, resource_id)
            raise _not_decidable(resource_id, existing.state if existing else "unknown") from exc
        raise
    except Exception:
        if claim is not None:
            await idempotency.release(session, key=idempotency_key, endpoint=endpoint, actor_id=principal.user_id, claim=claim)
        raise

    body = _discovered_resource_dto(row)
    if claim is not None:
        await idempotency.complete(
            session,
            key=idempotency_key,
            endpoint=endpoint,
            actor_id=principal.user_id,
            status_code=200,
            body=body,
            claim=claim,
            request_fingerprint=fingerprint,
        )
    return body
