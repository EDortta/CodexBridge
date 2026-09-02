"""The one place that answers "is this project bound to a forge repository?"

WK-20260902-forge-binding, issue #79/#80 (PR B4). `scm_associations`
(`migrations/0009_control_plane.sql`, `gateway/app/models/entities.py::
ScmAssociationModel`) existed since issue #73's Stage 1 but had no reader and
no writer until this PR -- `docs/control-plane.md`: "vazia e sem código até
hoje". `project_forge_binding` below is that reader, and it is deliberately
the ONLY place in this codebase that turns a row (or its absence) into a
routing decision, so every caller that needs to know "forge or local
tables?" -- the MCP tools in `gateway/app/mcp/server.py`, `AgentHub.
dispatch_next`'s `gh:N` support, `gateway/app/api/routes/decisions.py`'s
forge-operation approval path -- asks this function instead of re-deriving
the answer from the table itself. A second hand-rolled query somewhere else
in this codebase, however small, is exactly the kind of drift that made a
project's own `path` need `workspace_bindings` as a single source of truth
(`docs/control-plane.md`); this module plays the same role for "is this
project's forge write surface open".

What this module does NOT do: confirm the binding against reality. That is
`agent.codex_bridge_agent.forge.github._confirm_repo_identity_live`, on the
EXECUTOR, run fresh before every single forge operation, never cached. The
split is deliberate and mirrors `docs/architecture.md`'s existing "gateway
never learns a project's real path" posture extended one step further: the
gateway records what an operator DECLARED through `bind_project_forge`
(`gateway/app/mcp/server.py`); only the executor, sitting in the actual
working tree, can know what the remote REALLY is right now. A gateway that
trusted its own declared row as proof of the live remote would grant a forge
write against a folder that has since lost, gained, or repointed its
remote -- exactly the gap `_confirm_repo_identity_live`'s own docstring
names.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from gateway.app.models.entities import ScmAssociationModel


# The only provider this codebase's forge module (`agent.codex_bridge_agent.
# forge.github`) speaks. Not a placeholder for a future multi-provider
# lookup -- `project_forge_binding` filters on it explicitly so a row some
# future provider module writes under a different `provider` value is never
# silently treated as a GitHub binding.
GITHUB_PROVIDER = "github"

# `ScmAssociationModel.confidence`'s two real values (`observed` stays
# reserved for a future automatic-discovery writer this PR does not add --
# see that model's own docstring). Named here, once, so `store.py`'s
# registration function and this module's own tests import the same two
# strings rather than each spelling them out.
CONFIDENCE_DECLARED = "declared"
CONFIDENCE_CONFIRMED = "confirmed"


@dataclass(frozen=True)
class ForgeBinding:
    """What `project_forge_binding` found: a project IS bound, here's to what.

    `association_id` is carried through so a caller that needs to update the
    same row later (an operator confirming what was declared) does not have
    to re-query for it.
    """

    association_id: str
    project_id: str
    provider: str
    repo_identity: str
    confidence: str


async def project_forge_binding(session: AsyncSession, project_id: str) -> ForgeBinding | None:
    """The project's current forge binding, or `None` -- "not bound" included.

    `None` is not an error and not a degraded case: it is the majority
    answer for every project in this codebase today (the table starts
    empty), and every caller of this function treats it as "route to the
    local tables instead", never as a reason to refuse outright. A project
    can have at most one row per `(project_id, provider)`
    (`scm_associations_project_provider_idx`,
    `migrations/0013_forge_binding.sql`) -- `store.upsert_scm_association`
    is the only writer, and it updates that one row in place rather than
    inserting a second one, so there is no "which row wins" ambiguity to
    resolve here.

    `repo_identity` can, in principle, be `None` on a row `store.
    upsert_scm_association` has not filled in yet (the column is nullable on
    `ScmAssociationModel`, inherited from #73's original schema, which also
    had to represent "the remote is known, the exact owner/repo is not").
    That row is not a usable forge binding -- there is no `repo_identity` a
    caller could hand to `ForgeOperationRequest` -- so it is treated the same
    as no row at all, `None`, rather than surfacing a `ForgeBinding` whose
    `repo_identity` is `None` and pushing that check onto every caller.
    """
    result = await session.execute(
        select(ScmAssociationModel).where(
            ScmAssociationModel.project_id == project_id,
            ScmAssociationModel.provider == GITHUB_PROVIDER,
        )
    )
    row = result.scalar_one_or_none()
    if row is None or not row.repo_identity:
        return None
    return ForgeBinding(
        association_id=row.id,
        project_id=row.project_id,
        provider=row.provider,
        repo_identity=row.repo_identity,
        confidence=row.confidence,
    )
