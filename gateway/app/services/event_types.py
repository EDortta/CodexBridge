"""Which audit rows become mobile events, and what those events may say — issue #13.

`audit_events` is this gateway's durable event log: every domain mutation already
calls `gateway/app/services/audit.py:record_event`, so issue #13 needs no second
write path, no message bus and no new table. What it needs is a **translation**,
and translation is this module's one reason to change.

Three rules shape everything below.

## 1. The row is internal; the event is public

`AuditEventModel.payload_json` is written by thirty-one call sites that were never
audited for what they may contain. It carries `actor_email`, `requested_by_email`,
free-text `reason` and `error` strings from an executor, and `context` blobs.
`docs/api/README.md`'s "Fields that must never ship" applies to every byte of it,
and no existing sanitizer covers a response body.

So the payload is **never passed through**. Each mobile event type names the
handful of payload keys it may read (`_SUMMARY_BUILDERS` below), every free-text
value goes through `routes/sessions.py:redact` on the way out, and a key nobody
whitelisted simply does not leave the process. Adding a field to an audit payload
therefore cannot leak it — the default is exclusion, which is the direction
`design-standards.md` §6 calls fail-closed.

## 2. An audit row with no project is not deliverable

Authorization for this stream is by project (`gateway/app/api/routes/events.py`),
and `AuditEventModel` has no project column. A row's project is derived from the
entity it names: `tasks`, `epics`, `issues` and `conversations` all carry
`project_id`. `DELIVERABLE_ENTITY_TYPES` is exactly that set.

`entity_type == "auth"` is **excluded by construction**, not by a filter someone
must remember: sign-in, sign-in-failure and revocation rows have a `user_id` where
a project would be, they are not in issue #13's list of event kinds, and streaming
them would tell any token holder when the operator signs in. `notification` rows
(preference changes) are excluded the same way — a user's own preference is not a
project's event.

## 3. The vocabulary is closed, and every writer must land in it

`classify` maps one audit `event_type` to one `MobileEventType`. A type it does
not know is **not emitted**, which is safe — and would also be silent, which is
not. `tests/integration/test_events.py::test_every_audited_domain_event_type_is_translated`
parses every `record_event(...)` call in `gateway/` with `ast` and fails when a
call under a deliverable entity type writes a type this module does not map. A
future author who adds an audit event has to decide what the mobile client sees;
they cannot decide it by accident.

## Sessions, missions and decisions are one row under three names

`docs/api/README.md` already establishes that a session, a mission and a decision
are the same `TaskModel` row seen through three vocabularies. This module does not
triple every event to match: it emits **one** event per audit row, with
`entity.kind` naming the vocabulary that fits what happened — `decision` for the
approval lifecycle, `session` for everything else. The id is the same id, so a
mission-control client fetches `/api/v1/missions/{id}` with it and a session
client fetches `/api/v1/sessions/{id}`.

## Types declared here and never emitted by this build

`artifact.created`, `artifact.updated` and `androidBuild.status_changed` are in
`ALL_EVENT_TYPES` and in the contract's `MobileEventType` enum, and **nothing in
this build ever produces one**: there is no `ArtifactModel` and no Android build
record (issue #11 has not shipped). They are declared rather than omitted because
`docs/api/README.md` makes adding a value to a non-`ErrorCode` enum a breaking
change — a client that switches exhaustively on this enum would have to be
rewritten when #11 lands. Declaring them now costs a client nothing (they never
arrive) and saves a `v2`.

`NOT_YET_EMITTED` is what keeps that honest rather than becoming a quiet promise:
`test_events.py::test_the_declared_but_unemitted_types_are_not_produced_by_this_build`
asserts `classify` can never return one.
"""

from __future__ import annotations

from dataclasses import dataclass

from gateway.app.services.issue_types import EPIC_STATUSES, ISSUE_PRIORITIES, ISSUE_STATUSES
from shared.protocol import ApprovalDecision, TaskState


# Entity types whose rows carry a `project_id` this stream can authorize against.
# Everything else — `auth`, `notification` — is out by construction. See §2 above.
DELIVERABLE_ENTITY_TYPES: frozenset[str] = frozenset({"task", "epic", "issue", "conversation"})

# What a client fetches to see the whole resource behind an event.
ENTITY_KIND_SESSION = "session"
ENTITY_KIND_DECISION = "decision"
ENTITY_KIND_EPIC = "epic"
ENTITY_KIND_ISSUE = "issue"
ENTITY_KIND_CONVERSATION = "conversation"
ENTITY_KIND_ARTIFACT = "artifact"
ENTITY_KIND_ANDROID_BUILD = "androidBuild"

ENTITY_KINDS: tuple[str, ...] = (
    ENTITY_KIND_SESSION,
    ENTITY_KIND_DECISION,
    ENTITY_KIND_EPIC,
    ENTITY_KIND_ISSUE,
    ENTITY_KIND_CONVERSATION,
    ENTITY_KIND_ARTIFACT,
    ENTITY_KIND_ANDROID_BUILD,
)


@dataclass(frozen=True)
class MobileEvent:
    """One translated event, in the shape the contract publishes.

    `action` is not stored anywhere: it is the part of `type` after the dot, so
    a client can branch coarsely (`created`, `state_changed`) without parsing
    the string and the two can never disagree.
    """

    id: int
    type: str
    project_id: str
    entity_kind: str
    entity_id: str
    at: str
    summary: str
    state: str | None = None
    actor_id: str | None = None

    @property
    def action(self) -> str:
        return self.type.partition(".")[2]

    def as_dict(self) -> dict:
        body: dict = {
            "id": self.id,
            "type": self.type,
            "projectId": self.project_id,
            "entity": {"kind": self.entity_kind, "id": self.entity_id},
            "action": self.action,
            "at": self.at,
            "summary": self.summary,
        }
        # Both are optional rather than always-null: a null-always field is
        # indistinguishable from one a client can build against
        # (docs/api/README.md, the `probes.CAPABILITIES` reasoning).
        if self.state is not None:
            body["state"] = self.state
        if self.actor_id is not None:
            body["actorId"] = self.actor_id
        return body


# --------------------------------------------------------------------------
# The vocabulary
# --------------------------------------------------------------------------

# audit `event_type` -> (mobile type, entity kind). One entry per writer.
#
# `task.created` is deliberately absent: it is the one row whose mobile type
# depends on the payload (a task created straight into `awaiting_approval` is a
# decision being requested, not a session starting), and `classify` resolves it.
_STATIC_MAPPING: dict[str, tuple[str, str]] = {
    # --- sessions: the run's own lifecycle -------------------------------
    "task.state_changed": ("session.state_changed", ENTITY_KIND_SESSION),
    "task.result": ("session.completed", ENTITY_KIND_SESSION),
    "task.recovered": ("session.recovered", ENTITY_KIND_SESSION),
    "task.restarted": ("session.restarted", ENTITY_KIND_SESSION),
    "task.stopped_by_actor": ("session.stopped", ENTITY_KIND_SESSION),
    "task.control_requested": ("session.control_requested", ENTITY_KIND_SESSION),
    "task.control_acknowledged": ("session.control_acknowledged", ENTITY_KIND_SESSION),
    "task.cancel_acknowledged": ("session.stop_acknowledged", ENTITY_KIND_SESSION),
    "task.ack_refused": ("session.control_refused", ENTITY_KIND_SESSION),
    # --- decisions: the approval lifecycle over the same row -------------
    "task.approval_decision": ("decision.resolved", ENTITY_KIND_DECISION),
    "task.decision_resolved_by_actor": ("decision.resolved_by_actor", ENTITY_KIND_DECISION),
    # --- planning ---------------------------------------------------------
    "epic.created": ("epic.created", ENTITY_KIND_EPIC),
    "issue.created": ("issue.created", ENTITY_KIND_ISSUE),
    "issue.updated": ("issue.updated", ENTITY_KIND_ISSUE),
    "issue.linked_to_epic": ("issue.linked_to_epic", ENTITY_KIND_ISSUE),
    # --- conversations ----------------------------------------------------
    "conversation.created": ("conversation.created", ENTITY_KIND_CONVERSATION),
    "conversation.message_created": ("conversation.message_created", ENTITY_KIND_CONVERSATION),
}

# Both halves of the `task.created` fork.
SESSION_CREATED = "session.created"
DECISION_REQUESTED = "decision.requested"

# Audit event types this module translates. This is what the SQL query filters
# on, so a row nothing maps is excluded *by the query* rather than dropped after
# the fact — which is what keeps `hasMore` truthful (docs/api/README.md:
# "Project scope is enforced on the query, not on the response", same reasoning).
TRANSLATED_AUDIT_EVENT_TYPES: frozenset[str] = frozenset(_STATIC_MAPPING) | {"task.created"}

# Declared in the contract, never produced here. See the module docstring.
NOT_YET_EMITTED: tuple[str, ...] = (
    "artifact.created",
    "artifact.updated",
    "androidBuild.status_changed",
)

EMITTED_EVENT_TYPES: tuple[str, ...] = tuple(
    sorted({mobile for mobile, _ in _STATIC_MAPPING.values()} | {SESSION_CREATED, DECISION_REQUESTED})
)

# Everything a client may filter on or switch over: what this build emits, plus
# what a later build will. A value outside this set is a client error.
ALL_EVENT_TYPES: tuple[str, ...] = tuple(sorted(set(EMITTED_EVENT_TYPES) | set(NOT_YET_EMITTED)))

# Stream control frames. Not entity events and deliberately not in
# `MobileEventType`: they carry no entity, no project and no resume id, and a
# client that switched over the entity enum must not have to know them to
# compile. See `routes/events.py`.
STREAM_OPEN = "stream.open"
STREAM_GAP = "stream.gap"
STREAM_CLOSED = "stream.closed"
STREAM_CONTROL_TYPES: tuple[str, ...] = (STREAM_OPEN, STREAM_GAP, STREAM_CLOSED)


def classify(audit_event_type: str, payload: dict) -> tuple[str, str] | None:
    """`(mobile type, entity kind)` for one audit row, or None when it is internal.

    The one payload-dependent fork is `task.created`: `store.create_task` writes
    it for every submission, and a submission that `shared/policy.py` held for
    approval is a *decision being requested* — the event issue #13 names — while
    every other submission is a session starting. The two are the same row and
    the same audit type, so the fork lives here rather than in a second writer.
    """
    if audit_event_type == "task.created":
        state = payload.get("state")
        if state == "awaiting_approval":
            return DECISION_REQUESTED, ENTITY_KIND_DECISION
        return SESSION_CREATED, ENTITY_KIND_SESSION
    return _STATIC_MAPPING.get(audit_event_type)


# --------------------------------------------------------------------------
# Summaries — the only place a stored payload is read
# --------------------------------------------------------------------------

# Payload keys whose values are echoed, and the **closed set each one may take**.
#
# The first cut of this module keyed on the name alone and returned any non-empty
# string, on the stated premise that these values "are server-generated enums
# rather than free text". That premise was false for two of them, and the council
# reproduced it end to end (round 1, the adversarial user): `control` and `state`
# on a `task.control_acknowledged` / `task.ack_refused` row come straight from an
# executor's `task.ack` frame — `gateway/app/main.py` reads
# `envelope.payload.get("control")` and `.get("state")` with no validation, and
# the `invalid_state` branch deliberately records the very string it just refused
# as a `TaskState`. A connected executor could therefore put a filesystem path, an
# internal `host:port`, a `Bearer` value or a 200 KB blob into a mobile
# notification line, past every guard in this module.
#
# Membership, not redaction, is the fix. `redact` strips the patterns it knows;
# a closed set admits only the values this system actually defines, so a value
# nobody defined cannot be echoed at all whatever it contains. That is the
# fail-closed direction (`design-standards.md` §6) and it bounds the length for
# free, because every member is short by construction.
_ENUM_VOCABULARIES: dict[str, frozenset[str]] = {
    # Every `TaskState`. The one enum a client is most likely to switch on.
    "state": frozenset(state.value for state in TaskState),
    # The controls `routes/sessions.py` dispatches, plus the cancel path that
    # `main.py` acknowledges under its own audit type.
    "control": frozenset({"pause", "resume", "restart", "cancel"}),
    # `decision` and `outcome` are both an `ApprovalDecision`; they differ only
    # in which writer chose the key.
    "decision": frozenset(decision.value for decision in ApprovalDecision),
    "outcome": frozenset(decision.value for decision in ApprovalDecision),
    "status": EPIC_STATUSES | ISSUE_STATUSES,
    "priority": ISSUE_PRIORITIES,
}


def _enum(payload: dict, key: str, default: str = "unknown") -> str:
    """One closed-vocabulary payload value, or `default` for anything else.

    Anything else means: a missing key, a non-string, an empty string, and — the
    case that matters — a string this system does not define. `payload_json` is
    years of rows on disk written by many call sites, and one of those call sites
    records unvalidated executor text; a value that is not in the vocabulary is
    not a value this endpoint may repeat.
    """
    allowed = _ENUM_VOCABULARIES.get(key)
    if allowed is None:
        # Not an assert: `python -O` strips those, and a guard that disappears
        # under a flag is not a guard. An unknown key yields the default, which
        # is the same fail-closed answer with no way to switch it off.
        return default
    value = payload.get(key)
    return value if isinstance(value, str) and value in allowed else default


def _free_text(payload: dict, key: str, redact) -> str | None:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        return None
    cleaned = redact(value)
    if cleaned is None:
        return None
    cleaned = cleaned.strip()
    # Bounded: a summary is a notification line, and `last_error` can be a
    # multi-kilobyte executor traceback. Truncating here rather than at the
    # route keeps every caller of this module bounded by construction.
    return (cleaned[:SUMMARY_TEXT_LIMIT] + "…") if len(cleaned) > SUMMARY_TEXT_LIMIT else cleaned


SUMMARY_TEXT_LIMIT = 200


def summarize(mobile_type: str, payload: dict, redact) -> str:
    """A short, human-readable line for one event. Never the raw payload.

    `redact` is injected rather than imported so this module does not depend on
    a route module (and so a test can prove redaction is actually applied, by
    passing a spy). It is `gateway/app/api/routes/sessions.py:redact`.
    """
    builder = _SUMMARY_BUILDERS.get(mobile_type)
    if builder is None:
        # Unreachable for anything `classify` returns — `test_events.py`
        # asserts every emitted type has a builder — and a bland, correct
        # sentence rather than an exception if that ever stops being true.
        return "Event recorded."
    return builder(payload, redact)


def _session_created(payload: dict, redact) -> str:
    return f"Session submitted; state {_enum(payload, 'state')}."


def _decision_requested(payload: dict, redact) -> str:
    return "A sensitive session is waiting for a decision."


def _session_state_changed(payload: dict, redact) -> str:
    error = _free_text(payload, "error", redact)
    return f"State changed to {_enum(payload, 'state')}." + (f" {error}" if error else "")


def _session_completed(payload: dict, redact) -> str:
    return f"Execution finished; state {_enum(payload, 'state')}."


def _session_recovered(payload: dict, redact) -> str:
    return f"Recovered after a gateway restart; marked {_enum(payload, 'state')}."


def _session_restarted(payload: dict, redact) -> str:
    return f"Session restarted; state {_enum(payload, 'state')}."


def _session_stopped(payload: dict, redact) -> str:
    reason = _free_text(payload, "reason", redact)
    return "Cancelled by an operator." + (f" {reason}" if reason else "")


def _session_control_requested(payload: dict, redact) -> str:
    return f"An operator requested {_enum(payload, 'control', 'a control')}."


def _session_control_acknowledged(payload: dict, redact) -> str:
    accepted = payload.get("accepted")
    verb = "accepted" if accepted is True else "refused" if accepted is False else "answered"
    return f"The executor {verb} {_enum(payload, 'control', 'a control')}."


def _session_stop_acknowledged(payload: dict, redact) -> str:
    return "The executor confirmed the session is stopped."


def _session_control_refused(payload: dict, redact) -> str:
    # `reason` here is one of three server-side constants
    # (`unknown_task`/`not_owner`/`invalid_state`, gateway/app/main.py), never
    # caller text — but it is read through the free-text path anyway rather than
    # `_enum`, so that widening it later cannot turn this line into a leak.
    reason = _free_text(payload, "reason", redact)
    return "A control acknowledgement was refused." + (f" Reason: {reason}." if reason else "")


def _decision_resolved(payload: dict, redact) -> str:
    reason = _free_text(payload, "reason", redact)
    return f"Decision recorded: {_enum(payload, 'decision')}." + (f" {reason}" if reason else "")


def _decision_resolved_by_actor(payload: dict, redact) -> str:
    return f"An operator resolved the decision: {_enum(payload, 'outcome')}."


def _epic_created(payload: dict, redact) -> str:
    return f"Epic created with status {_enum(payload, 'status')}."


def _issue_created(payload: dict, redact) -> str:
    return f"Issue created with status {_enum(payload, 'status')}."


def _issue_updated(payload: dict, redact) -> str:
    return f"Issue updated; status {_enum(payload, 'status')}, priority {_enum(payload, 'priority')}."


def _issue_linked_to_epic(payload: dict, redact) -> str:
    return "Issue attached to an epic."


def _conversation_created(payload: dict, redact) -> str:
    # `context` is deliberately not read: it is a list of entity references the
    # conversation endpoints already authorize individually, and echoing ids
    # from it here would publish them under this event's single-project check.
    return "Conversation started."


def _conversation_message_created(payload: dict, redact) -> str:
    attachments = payload.get("attachments")
    count = attachments if isinstance(attachments, int) and attachments > 0 else 0
    # The message body is never read. `Message.body` is operator/agent prose and
    # belongs behind `GET /api/v1/conversations/{id}/messages`, which authorizes
    # it; a notification says *that* there is a message, not what it says.
    return "New message." + (f" {count} attachment(s)." if count else "")


_SUMMARY_BUILDERS = {
    SESSION_CREATED: _session_created,
    DECISION_REQUESTED: _decision_requested,
    "session.state_changed": _session_state_changed,
    "session.completed": _session_completed,
    "session.recovered": _session_recovered,
    "session.restarted": _session_restarted,
    "session.stopped": _session_stopped,
    "session.control_requested": _session_control_requested,
    "session.control_acknowledged": _session_control_acknowledged,
    "session.stop_acknowledged": _session_stop_acknowledged,
    "session.control_refused": _session_control_refused,
    "decision.resolved": _decision_resolved,
    "decision.resolved_by_actor": _decision_resolved_by_actor,
    "epic.created": _epic_created,
    "issue.created": _issue_created,
    "issue.updated": _issue_updated,
    "issue.linked_to_epic": _issue_linked_to_epic,
    "conversation.created": _conversation_created,
    "conversation.message_created": _conversation_message_created,
}


# Payload keys read for the two structured fields on `MobileEvent`. `actor_id`
# is the opaque user id the mission timeline already publishes; `actor_email` is
# in several payloads and is read by nothing here, which is the whole point of
# whitelisting rather than filtering.
def actor_of(payload: dict) -> str | None:
    for key in ("actor_id", "requested_by_user_id"):
        value = payload.get(key)
        if isinstance(value, str) and value:
            return value
    return None


def state_of(payload: dict) -> str | None:
    """The entity's state, or None when the row does not record a defined one.

    Checked against `TaskState` for the same reason `_enum` is, and it is the
    same defect: `main.py`'s `invalid_state` branch records the executor's raw
    `state` string — the one the gateway just refused *because* it is not a
    `TaskState` — and this field was echoing it verbatim into a response body.
    None rather than "unknown" here, because `state` is omitted from the event
    when absent and a client switching on it must not be handed a value that is
    not in the enum it was given.
    """
    value = payload.get("state")
    if not isinstance(value, str) or value not in _ENUM_VOCABULARIES["state"]:
        return None
    return value
