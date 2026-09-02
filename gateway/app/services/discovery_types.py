"""Closed vocabulary for adopting a `discovered_resources` row, and its error.

WK-20260902-gh73-discovery-adoption, issue #73 Stage 3 (adoption half). Kept
out of `shared/protocol.py` on purpose, same reasoning `issue_types.py` and
`conversation_types.py` already give: this is a gateway-only, operator-facing
concept -- the node never sees an adoption decision, only its eventual effect
(a `project_authorizations` row it did not write) -- so it does not share a
module with the executor wire protocol.
"""

from __future__ import annotations

from shared.protocol import DiscoveredState


# The only states `adopt_discovered_resource`/`deny_discovered_resource` may
# act on. `ADOPTED`/`AUTHORIZED`/`DENIED` are all standing operator decisions;
# re-deciding one is a conflict, not a silent overwrite -- the same posture
# `routes/decisions.py:DECIDABLE` already takes toward a resolved decision.
# `STALE` is included deliberately: a candidate the node stopped reporting is
# still something an operator may choose to adopt or deny from history, and
# `docs/control-plane.md` already treats a `STALE` row's earlier decision (if
# any) as worth preserving -- an *undecided* `STALE` row deserves the same
# adoption path a `DISCOVERED` one gets, not a dead end.
DECIDABLE_DISCOVERY_STATES = frozenset({DiscoveredState.DISCOVERED.value, DiscoveredState.STALE.value})


class DiscoveryAdoptionError(ValueError):
    """An adopt/deny input that fails validation inside the store itself.

    Same shape as `issue_types.IssuePlanningError` and
    `conversation_types.ConversationPlanningError`: the guard belongs inside
    the operation, not the route, so a future second caller (there is none
    today, but `link_issue_to_epic`'s own history is the reason this is
    written now rather than assumed) does not get to skip it by construction.
    """

    def __init__(self, field: str, code: str, message: str) -> None:
        super().__init__(message)
        self.field = field
        self.code = code
        self.message = message
