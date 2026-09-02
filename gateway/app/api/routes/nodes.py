"""Bridge Nodes — the fleet visibility surface of issue #73, Stage 2.

A **node** is a `NodeModel` row: a registered CodexBridge installation, distinct
from the `ExecutorModel` connection that carries work to it (see `NodeModel`'s
own docstring in `gateway/app/models/entities.py`). This module reports what a
node last announced about itself plus the liveness of its bound executor —
never the filesystem paths or hostnames `docs/api/README.md` ("Fields that must
never ship") excludes from every response. `discovery_root_count` exists
precisely so this surface can answer "does this node discover anything at all"
without a single path ever crossing the wire.

## Health is derived, not stored

Same posture as `routes/projects.py`: `NodeModel` carries no health column.
`health` is computed at read time by `shared.protocol.node_health`, fed by
`store.executor_is_live` (liveness) and `executor.last_seen_at is not None`
("ever seen"). See that function's docstring for why the ordering of its checks
matters.

## An announcement is an observation, not a grant

`capabilities`/`engines`/`maxConcurrentTasks`/`discoveryRootCount` all come
from the node's own last HELLO (`store.record_node_announcement`) and say only
what the node *reports itself capable of* — never what it is authorized to do
to any given project. That authorization lives in `project_authorizations`,
which this surface does not read or expose (issue #73: "a node cannot grant
itself project authorization merely by reporting a discovery").

## Authorization

Fleet-wide, not per-project — a node is not owned by one project the way a
session or a mission is — so both routes are guarded by the one administrative
`permissions.NODES_READ` action rather than the `visible_projects` scoping
`routes/projects.py` applies. An unknown node id is `404 not_found`, the same
"do not confirm what the caller cannot see" rule every other resource on this
surface follows, even though here there is no project scope that could hide it
— the id is simply not present.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from gateway.app.api import permissions, timestamps
from gateway.app.api.auth import require_action
from gateway.app.api.errors import NOT_FOUND, ApiError
from gateway.app.core.users import AuthenticatedPrincipal
from gateway.app.db.session import get_session
from gateway.app.models.entities import ExecutorModel, NodeModel
from gateway.app.services import store
from shared.protocol import node_health


router = APIRouter(prefix="/api/v1")

# Inventory freshness needs a longer window than connection liveness.
# `settings.reconnect_grace_seconds` (120s) is sized to the agent's 15s
# heartbeat interval and would mark a node's inventory stale between two
# ordinary heartbeats — a `NodeAnnouncement` is sent once per connection (on
# HELLO), not on every heartbeat the way `last_seen_at` is refreshed. Issue
# #73/#42 ask only that stale inventory be "visibly marked", not for a
# specific window, so this is a deliberately generous, module-level constant
# rather than a new setting (the task explicitly rules that out — the operator
# has no reason to tune this independently of the reconnect grace yet).
INVENTORY_STALE_AFTER_SECONDS = 24 * 60 * 60


def _not_found() -> ApiError:
    return ApiError(status_code=404, code=NOT_FOUND, message="No such node.")


def _iso(value: datetime | None) -> str | None:
    return timestamps.utc_z(value)


def _is_stale(observed_at: datetime | None, *, now: datetime) -> bool:
    if observed_at is None:
        return True
    if observed_at.tzinfo is None:
        observed_at = observed_at.replace(tzinfo=timezone.utc)
    return (now - observed_at).total_seconds() > INVENTORY_STALE_AFTER_SECONDS


def _node_dto(node: NodeModel, executor: ExecutorModel | None) -> dict:
    """The fleet DTO for one node. Never a filesystem path — see module docstring."""
    live = executor is not None and store.executor_is_live(executor)
    ever_seen = executor is not None and executor.last_seen_at is not None
    health = node_health(live=live, enabled=node.enabled, ever_seen=ever_seen, health_reason=node.health_reason)
    inventory = json.loads(node.capabilities_json or "{}")
    now = datetime.now(timezone.utc)
    return {
        "id": node.id,
        "displayName": node.display_name,
        "enabled": node.enabled,
        "health": health.value,
        "healthReason": node.health_reason,
        "lastSeenAt": _iso(executor.last_seen_at) if executor is not None else None,
        "agentVersion": node.agent_version,
        "os": node.os,
        "arch": node.arch,
        "capabilities": inventory.get("capabilities", []),
        "engines": inventory.get("engines", []),
        "maxConcurrentTasks": inventory.get("max_concurrent_tasks"),
        "discoveryRootCount": inventory.get("discovery_root_count"),
        "capabilitiesObservedAt": _iso(node.capabilities_observed_at),
        "inventoryObservedAt": _iso(node.inventory_observed_at),
        "inventoryStale": _is_stale(node.capabilities_observed_at, now=now),
    }


@router.get("/nodes", tags=["nodes"])
async def list_nodes_endpoint(
    principal: AuthenticatedPrincipal = Depends(require_action(permissions.NODES_READ)),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Every Bridge Node in the fleet, ordered by id.

    Not paginated: the fleet, like the executor registry it is seeded from, is
    operator-curated and expected to hold a handful of machines, the same
    reasoning `store.executors_by_project` documents for reading the whole
    registry in one pass.
    """
    rows = await store.list_nodes(session)
    return {"items": [_node_dto(node, executor) for node, executor in rows]}


@router.get("/nodes/{node_id}", tags=["nodes"])
async def get_node_detail(
    node_id: str,
    principal: AuthenticatedPrincipal = Depends(require_action(permissions.NODES_READ)),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """One node's fleet status."""
    row = await store.get_node(session, node_id)
    if row is None:
        raise _not_found()
    node, executor = row
    return _node_dto(node, executor)
