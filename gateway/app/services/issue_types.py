"""Closed vocabularies for epics and issues, and the error they fail with.

Kept out of `shared/protocol.py` on purpose: that module is the executor
protocol, shared with the agent process over the reverse WebSocket. Epics and
issues are a gateway-only concept with no executor involvement, so giving them
their own module keeps a protocol change and a planning-model change from ever
being the same diff.
"""

from __future__ import annotations


EPIC_STATUSES = frozenset({"open", "in_progress", "done", "cancelled"})
ISSUE_STATUSES = frozenset({"open", "in_progress", "blocked", "in_review", "done", "cancelled"})
ISSUE_PRIORITIES = frozenset({"low", "medium", "high", "urgent"})

DEFAULT_EPIC_STATUS = "open"
DEFAULT_ISSUE_STATUS = "open"
DEFAULT_ISSUE_PRIORITY = "medium"


class IssuePlanningError(ValueError):
    """A create/update input that fails validation inside the store itself.

    Raised by `gateway.app.services.store`, not by the route layer: the guard
    belongs inside the operation, or a future second caller (the MCP transport,
    a future GitHub sync job) gets to skip it by construction rather than by
    accident (`design-standards.md` §3). `field` and `code` let the HTTP layer
    build one `ErrorDetail` without re-deriving what went wrong from a string.
    """

    def __init__(self, field: str, code: str, message: str) -> None:
        super().__init__(message)
        self.field = field
        self.code = code
        self.message = message
