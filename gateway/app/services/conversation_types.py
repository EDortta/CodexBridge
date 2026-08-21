"""Closed vocabulary for conversation context references, and their error.

Kept out of `shared/protocol.py` on purpose, same reasoning as
`gateway/app/services/issue_types.py`: this is a gateway-only planning
concept with no executor involvement, so it does not share a module with the
executor protocol.

## Why `artifact` is not a context type

Issue #10's objective names conversations "linked to projects, decisions,
missions, issues, sessions and artifacts". Five of those six already have a
backing model this build can validate a reference against: `project` is
`ProjectModel`; `session`, `decision` and `mission` are the same `TaskModel`
under three vocabularies (`docs/api/README.md`'s "Decisions"/"Missions"
sections); `issue` is `IssueModel` (issue #8). `artifact` has no backing model
— issue #11 has not shipped `ArtifactModel` — so a context reference of that
type could not be checked for existence or for project visibility, which is
exactly the acceptance criterion this issue's context references exist to
satisfy ("Unauthorized entity references are rejected without disclosing
hidden resources"). Rather than accept an unverifiable reference, `artifact`
is omitted from `CONTEXT_TYPES` until issue #11 gives it something to check
against, the same discipline issue #8 applied to "missions, conversations and
decisions" as issue links and issue #7 applied to `dependencies`/
`relatedEntities`: no backing entity, no field.

This does not remove artifacts from the feature. "Attachment references
through artifact/file identifiers" (issue #10's own Scope wording) is a
*message* concept, not a conversation *context* concept — `ConversationMessageModel.attachments_json`
carries opaque artifact/file ids on each message, unvalidated for the same
reason, and is unaffected by this restriction.
"""

from __future__ import annotations


CONTEXT_TYPES = frozenset({"project", "session", "decision", "mission", "issue"})

# Generous but bounded: a conversation about "this session and its parent
# project" is two references; there is no use case in this codebase for
# dozens, and an unbounded list is an unbounded query fan-out in
# `store.resolve_conversation_context`.
MAX_CONTEXT_REFERENCES = 16

MAX_MESSAGE_BODY_LENGTH = 50000
MAX_ATTACHMENTS_PER_MESSAGE = 20
MAX_ATTACHMENT_ID_LENGTH = 255


class ConversationPlanningError(ValueError):
    """A create input that fails validation inside the store itself.

    Same shape and same reasoning as `issue_types.IssuePlanningError`: the
    guard belongs inside the operation, not the route, so a future second
    caller does not get to skip it by construction.
    """

    def __init__(self, field: str, code: str, message: str) -> None:
        super().__init__(message)
        self.field = field
        self.code = code
        self.message = message
