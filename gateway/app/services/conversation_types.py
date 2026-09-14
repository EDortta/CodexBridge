"""Closed vocabulary for conversation context references, and their error.

Kept out of `shared/protocol.py` on purpose, same reasoning as
`gateway/app/services/issue_types.py`: this is a gateway-only planning
concept with no executor involvement, so it does not share a module with the
executor protocol.

## Why `artifact` is not a context type

Issue #10's objective names conversations "linked to projects, decisions,
missions, issues, sessions and artifacts". These now validate against their
own backing models where they have one: `project` is `ProjectModel`;
`session`/`decision` are `TaskModel`; `mission` is `MissionModel`; `issue` is
`IssueModel`. `artifact` is omitted until the conversation surface wires an
artifact visibility check, the same discipline issue #8 applied to "missions, conversations and
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
