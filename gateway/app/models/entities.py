from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from gateway.app.db.base import Base


class ExecutorModel(Base):
    __tablename__ = "executors"

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    display_name: Mapped[str] = mapped_column(String(255))
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    connected: Mapped[bool] = mapped_column(Boolean, default=False)
    metadata_json: Mapped[str] = mapped_column(Text, default="{}")
    # Which Bridge Node this connection belongs to (issue #73). Nullable so
    # `0009_control_plane.sql`'s ALTER stays portable; every row is backfilled
    # by that same migration, and the application treats a null as a pre-#73
    # row to repair at startup rather than as "no node".
    node_id: Mapped[str | None] = mapped_column(String(128), ForeignKey("nodes.id"), nullable=True)


class NodeModel(Base):
    """A registered CodexBridge installation — issue #73's Bridge Node.

    Distinct from `ExecutorModel` on purpose. #73 warns against "conflating
    `node`, `executor`, `engine` and `project` into one entity": the node is
    the machine and its capabilities, the executor is the authenticated
    connection that carries work to it. They are 1:1 today (seeded that way by
    `0009_control_plane.sql`) and the schema does not require them to stay so.

    `capabilities_observed_at` and `inventory_observed_at` exist because #42
    requires last-known capabilities to be persisted "with freshness
    timestamp" and stale data to be "visibly marked". Freshness is derived
    from these at read time — the same posture `store.executor_is_live` takes
    toward `ExecutorModel.connected`, and for the same reason: a stored
    boolean survives a restart that invalidated it.
    """

    __tablename__ = "nodes"

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    display_name: Mapped[str] = mapped_column(String(255))
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    os: Mapped[str | None] = mapped_column(String(64), nullable=True)
    arch: Mapped[str | None] = mapped_column(String(64), nullable=True)
    agent_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    capabilities_json: Mapped[str] = mapped_column(Text, default="{}")
    capabilities_observed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    inventory_observed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    health_reason: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class WorkspaceBindingModel(Base):
    """A logical Project as it exists on one Node's disk (issue #73).

    This is what makes "the same project on two machines at two paths"
    representable, which a column on `projects` could not be — #73: "A project
    MUST NOT be structurally owned by a node or by GitHub."

    `local_path` is sensitive operational data. #73 allows it only on
    "appropriately authorized operator surfaces"; it must never reach
    `ProjectStatus`, `Session`, `Mission` or any MCP tool
    (`docs/api/README.md`, "Fields that must never ship").

    `state` is the OBSERVED world (is this workspace usable right now), which
    is not the same question as the operator's decision — that one lives in
    `DiscoveredResourceModel.state`. Collapsing the two would lose the
    difference between "I revoked this" and "the disk went away".
    """

    __tablename__ = "workspace_bindings"

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    node_id: Mapped[str] = mapped_column(String(128), ForeignKey("nodes.id"))
    project_id: Mapped[str] = mapped_column(String(128), ForeignKey("projects.id"))
    local_path: Mapped[str] = mapped_column(String(2048))
    head: Mapped[str | None] = mapped_column(String(255), nullable=True)
    dirty: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    state: Mapped[str] = mapped_column(String(32), default="active")
    last_scan_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class ScmAssociationModel(Base):
    """Project <-> source-control repository, as an association rather than an

    attribute. #73 requires GitHub to be "an external project/repository
    source and association, not the owner of the project model", and requires
    a local project with no remote to be "represented honestly as
    unassociated rather than rejected" — which a non-null column on `projects`
    would make impossible.

    `confidence` is the direct consequence of #73's "Do not silently infer a
    trusted association only because directory and repository names happen
    to match": nothing in this codebase infers an association automatically
    yet (this table was empty and unwritten until WK-20260902-forge-binding,
    issue #79/#80 PR B4), so the value in use today is `declared` -- an
    operator named this repository through `gateway/app/mcp/server.py`'s
    `bind_project_forge` tool, which is a real decision, but not the same
    claim as "I confirmed this workspace's remote actually points there".
    `confirmed` is that stronger claim, and `gateway/app/services/
    forge_routing.py`'s own docstring is explicit that nothing moves a row
    from `declared` to `confirmed` automatically, ever -- not a matching
    directory name, not a `repo_identity_mismatch` check that happened to
    pass once (`agent/codex_bridge_agent/forge/github.py`'s live remote
    confirmation is a per-operation gate, not a promotion). Only an
    operator's own explicit `confirm=true` on that same tool call does.
    `observed` is reserved for a future automatic-discovery writer this PR
    does not add.
    """

    __tablename__ = "scm_associations"

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    project_id: Mapped[str] = mapped_column(String(128), ForeignKey("projects.id"))
    provider: Mapped[str] = mapped_column(String(32), default="github")
    remote_url: Mapped[str] = mapped_column(String(2048))
    repo_identity: Mapped[str | None] = mapped_column(String(512), nullable=True)
    confidence: Mapped[str] = mapped_column(String(32), default="observed")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class ProjectAuthorizationModel(Base):
    """What a node may actually do to a project (issue #73's authorization plane).

    Separate from the binding because the two are written by different actors:
    a node announces a binding, an operator (or a standing discovery-root
    grant) writes an authorization. #73: "A node cannot grant itself project
    authorization merely by reporting a discovery."

    `granted_by` is what keeps the automatic half auditable: `root-config:
    <path>` for a capability that came from a discovery root's
    `auto_authorize` (revoked by editing that root), `operator:<user_id>` for
    an explicit decision. A grant with no attributable origin is not a grant.
    """

    __tablename__ = "project_authorizations"

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    node_id: Mapped[str] = mapped_column(String(128), ForeignKey("nodes.id"))
    project_id: Mapped[str] = mapped_column(String(128), ForeignKey("projects.id"))
    capabilities_json: Mapped[str] = mapped_column(Text, default="[]")
    granted_by: Mapped[str] = mapped_column(String(255))
    granted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class DiscoveredResourceModel(Base):
    """Something a node can see that Control has not necessarily adopted.

    The entity that makes "Discovery is not authorization" structural rather
    than a convention: a node writes rows here and nothing else, so reporting
    a directory can never, by construction, produce the right to operate it.

    `state` carries all five values of `shared.protocol.DiscoveredState`.
    #73 forbids collapsing them into one boolean, and each pair it would merge
    loses a real distinction — notably `denied` vs `discovered` (without it a
    refused candidate returns to the adoption queue on every reconnect) and
    `stale` vs absent (the row and its history survive a project that moved).

    `resource_key` is the node's own identifier for the candidate and is
    deliberately NOT a foreign key: a candidate exists precisely before there
    is a `projects` row to point at. `kind` leaves room for the
    processes/services #73 anticipates without a schema change.
    """

    __tablename__ = "discovered_resources"

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    node_id: Mapped[str] = mapped_column(String(128), ForeignKey("nodes.id"))
    kind: Mapped[str] = mapped_column(String(32), default="project")
    resource_key: Mapped[str] = mapped_column(String(255))
    project_id: Mapped[str | None] = mapped_column(String(128), ForeignKey("projects.id"), nullable=True)
    evidence_json: Mapped[str] = mapped_column(Text, default="{}")
    state: Mapped[str] = mapped_column(String(32), default="discovered")
    root_path: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    decided_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ProjectModel(Base):
    __tablename__ = "projects"

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    name: Mapped[str] = mapped_column(String(255))
    path: Mapped[str] = mapped_column(String(2048))
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    config_json: Mapped[str] = mapped_column(Text, default="{}")


class TaskModel(Base):
    __tablename__ = "tasks"

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    executor_id: Mapped[str] = mapped_column(String(128), ForeignKey("executors.id"))
    project_id: Mapped[str] = mapped_column(String(128), ForeignKey("projects.id"))
    instruction: Mapped[str] = mapped_column(Text)
    mode: Mapped[str] = mapped_column(String(64))
    state: Mapped[str] = mapped_column(String(64))
    priority: Mapped[str] = mapped_column(String(32))
    run_when_available: Mapped[bool] = mapped_column(Boolean, default=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    timeout_seconds: Mapped[int]
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    requested_by_user_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    requested_by_email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    correlation_id: Mapped[str] = mapped_column(String(128))
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    command_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    session_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    result_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    approval_state: Mapped[str | None] = mapped_column(String(64), nullable=True)
    approval_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    # The policy level at the moment this task needed a decision (`shared.policy`),
    # set once and never overwritten (issue #6). `approval_state` cannot serve the
    # same purpose: `decide_task_approval` overwrites it with the outcome
    # ("approved"/"rejected"/"revision_requested"), so the risk a decision was
    # raised at would be lost the instant it was resolved — and the decisions API
    # filters and reports on it after resolution, not only while pending.
    policy_level: Mapped[str | None] = mapped_column(String(32), nullable=True)
    # Monotonic revision, bumped by every mutator in gateway/app/services/store.py.
    # It is what optimistic concurrency compares against: the timestamps cannot
    # serve, because none of started_at/completed_at moves when approval_state or
    # last_error changes, so an ETag derived from them would match on both sides
    # of a concurrent approval and no stale write would ever be detected.
    revision: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    # WK-20260830-chatgpt-entry-provider-and-delivery / migration 0008.
    # Which agent CLI ran this task. Defaults to "codex" so a row from before
    # this column existed reads back as what it always was.
    engine: Mapped[str] = mapped_column(String(32), default="codex", server_default="codex")
    # Opaque token naming the source issue ("docs:NNN", "local:<id>", a bare
    # number, or "gh:N" for the not-yet-supported GitHub form). Never a
    # filesystem path -- the gateway does not resolve it, the executor does
    # (see `agent/codex_bridge_agent/instructions.py`), because the gateway
    # never learns a project's real path (`docs/architecture.md`).
    issue_ref: Mapped[str | None] = mapped_column(String(512), nullable=True)
    # What delivery was *requested* (branch, allow_push, base_branch, remote) --
    # `shared.protocol.DeliveryRequest`, serialized. Distinct from
    # `delivery_result_json` below on purpose: a restart must be able to clear
    # what *happened* on the previous attempt without losing what was *asked*.
    delivery_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    # What delivery *actually did* -- branch, head commit, pushed y/n, refusal
    # reason. Kept out of `result_json` so "did it push, what commit" is a
    # column read, not a JSON parse, and so `restart_finished_task` resets it
    # the same way it resets `result_json` (issue-adjacent: a restarted task
    # that keeps a stale `delivery_result_json` would report the *previous*
    # run's commit as if it were this one's).
    delivery_result_json: Mapped[str | None] = mapped_column(Text, nullable=True)


class EpicModel(Base):
    __tablename__ = "epics"

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    project_id: Mapped[str] = mapped_column(String(128), ForeignKey("projects.id"))
    # Which system owns this row. "local" is the only value this build writes:
    # there is no GitHub sync yet, and this column is the seam a future one
    # would use to tell a gateway-authored epic from a mirrored one, the same
    # way ProjectModel already mirrors registry.json rather than owning it.
    provider: Mapped[str] = mapped_column(String(32), default="local", server_default="local")
    external_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    title: Mapped[str] = mapped_column(String(255))
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(32))
    created_by_user_id: Mapped[str] = mapped_column(String(255))
    created_by_email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    updated_by_user_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    updated_by_email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    # Bumped by every mutator in gateway/app/services/store.py. Same role as
    # TaskModel.revision: the ETag optimistic-concurrency check compares
    # against this, not against a timestamp.
    revision: Mapped[int] = mapped_column(Integer, default=1, server_default="1")


class IssueModel(Base):
    __tablename__ = "issues"

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    project_id: Mapped[str] = mapped_column(String(128), ForeignKey("projects.id"))
    epic_id: Mapped[str | None] = mapped_column(String(128), ForeignKey("epics.id"), nullable=True)
    provider: Mapped[str] = mapped_column(String(32), default="local", server_default="local")
    external_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    title: Mapped[str] = mapped_column(String(255))
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(32))
    priority: Mapped[str] = mapped_column(String(32))
    labels_json: Mapped[str] = mapped_column(Text, default="[]", server_default="[]")
    assignee_user_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    assignee_email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # Issue ids this issue is blocked on, JSON-encoded. Not a join table: the
    # scope here is "record and surface dependencies", not a full graph API,
    # and a join table with no second consumer is the architecture expansion
    # docs/limits.md rules out.
    dependencies_json: Mapped[str] = mapped_column(Text, default="[]", server_default="[]")
    blocked_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by_user_id: Mapped[str] = mapped_column(String(255))
    created_by_email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    updated_by_user_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    updated_by_email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revision: Mapped[int] = mapped_column(Integer, default=1, server_default="1")


class ConversationModel(Base):
    """A contextual thread linked to at least one product entity — issue #10.

    `context_json` is a JSON list of `{"type", "id"}` pairs, not a join table:
    the scope here is "record and surface which entities this conversation is
    about", the same reasoning `IssueModel.dependencies_json` documents, and a
    join table with a single consumer is the architecture expansion
    `docs/limits.md` rules out. `project_id` is denormalized from the context
    references at creation time (every reference resolves to exactly one
    project, checked in `store.resolve_conversation_context`) so authorization
    and listing do not have to parse `context_json` on every query.
    """

    __tablename__ = "conversations"

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    project_id: Mapped[str] = mapped_column(String(128), ForeignKey("projects.id"))
    title: Mapped[str | None] = mapped_column(String(255), nullable=True)
    context_json: Mapped[str] = mapped_column(Text)
    created_by_user_id: Mapped[str] = mapped_column(String(255))
    created_by_email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    # Null until the first message. Bumped by `store.create_conversation_message`
    # alone — this row itself is never PATCHable, so unlike Epic/Issue there is
    # no `revision`/`ETag` on a conversation: nothing here can go stale under a
    # concurrent write, because nothing here can be written except by appending
    # a message, which is its own idempotent, unconditional operation.
    last_activity_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ConversationMessageModel(Base):
    """One message in a conversation. Immutable once written — no update path."""

    __tablename__ = "conversation_messages"

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    conversation_id: Mapped[str] = mapped_column(String(128), ForeignKey("conversations.id"))
    author_user_id: Mapped[str] = mapped_column(String(255))
    author_email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # Markdown source, stored and returned verbatim. The server never renders
    # it; rendering is the mobile client's responsibility (docs/api/README.md).
    body: Mapped[str] = mapped_column(Text)
    # Opaque artifact/file identifiers, JSON-encoded. Not validated against a
    # backing model: no `ArtifactModel` exists yet (issue #11), so these are
    # recorded as caller-supplied references and returned unchanged, the same
    # way `IssueModel.dependencies_json` records ids without owning a graph.
    attachments_json: Mapped[str] = mapped_column(Text, default="[]", server_default="[]")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class ConversationReadStateModel(Base):
    """How far one actor has read into one conversation.

    Not exposed by any endpoint of its own: `GET .../messages` advances it as a
    side effect of fetching the current messages, and `POST .../messages`
    advances the sender's own past the message just sent — issue #10 names no
    "mark as read" endpoint, so this is the only mechanism that can move it.
    """

    __tablename__ = "conversation_read_states"

    conversation_id: Mapped[str] = mapped_column(String(128), ForeignKey("conversations.id"), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    last_read_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class TaskLogModel(Base):
    __tablename__ = "task_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    task_id: Mapped[str] = mapped_column(String(128), ForeignKey("tasks.id"))
    offset: Mapped[int]
    stream: Mapped[str] = mapped_column(String(16))
    line: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class ForgeOperationModel(Base):
    """One request to act on an external forge (GitHub today) -- issue #80/#79,
    WK-20260902-forge-wiring-and-gate (PR B3).

    Deliberately its OWN table, not a `TaskModel` row, even though the two
    look similar at a glance (both name a project/executor, both can sit
    `awaiting_approval`, both resolve to a stored result). `TaskModel`'s
    columns -- `mode`, `instruction`, `engine`, `timeout_seconds`,
    `session_id`, `delivery_json` -- all encode one specific thing: a
    coding-agent session running inside a sandbox on the executor. A forge
    operation has none of that shape: it is `kind` + `repo_identity` + a
    handful of optional fields, it runs OUTSIDE any sandbox as one bounded
    `gh` subprocess call, and `shared.policy.forge_operation_policy_level`'s
    own docstring is explicit that a forge write's `SENSITIVE` classification
    has no bypass field, structurally, unlike `TaskModel`'s
    `push_is_preauthorized`. Reusing `TaskModel` would mean inventing sentinel
    `TaskMode`/`engine` values nothing else in this codebase understands, or
    teaching `AgentHub.dispatch_next`/`RunnerPool` to special-case a `kind` no
    coding session has -- a worse coupling than the small parallel table this
    is. See `docs/protocol.md` and this migration's own commit message for
    the fuller writeup of that decision.

    What IS reused, deliberately, is the *vocabulary*: `state` values below
    read like `TaskState` (`awaiting_approval`, `approved`, `dispatched`,
    `completed`, `failed`) plus the two rejection outcomes
    `shared.protocol.ApprovalDecision` already names (`rejected`,
    `revision_requested`) -- an operator who has approved/rejected a task
    decision before sees the same shape here, never a third semantics to
    learn. `TaskState` itself is not imported: no forge operation is ever
    `QUEUED`/`RUNNING`/`PAUSED`/etc, so importing it would invite a branch on
    a value that can never occur here.

    Lifecycle: a row is born `awaiting_approval` (a write --
    `shared.policy.forge_operation_policy_level` returned `SENSITIVE`) or
    `approved` (a read, i.e. `issue_list` -- never gated at all) ->
    `approved` (a human decided, via `store.decide_forge_operation`) ->
    `dispatched` (the `FORGE_OPERATION` envelope left the gateway, via
    `AgentHub.dispatch_forge_operation`) -> `completed`/`failed` (a
    `FORGE_OPERATION_RESULT` came back). Or terminal without ever
    dispatching: `rejected`/`revision_requested`, set once by
    `decide_task_approval`'s forge sibling and never revisited -- this
    protocol has no message that reopens a forge operation, the same gap
    `routes/decisions.py` documents for `TaskModel`.
    """

    __tablename__ = "forge_operations"

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    project_id: Mapped[str] = mapped_column(String(128), ForeignKey("projects.id"))
    executor_id: Mapped[str] = mapped_column(String(128), ForeignKey("executors.id"))
    kind: Mapped[str] = mapped_column(String(32))
    repo_identity: Mapped[str] = mapped_column(String(200))
    # The full `ForgeOperationRequest`, serialized -- `title`/`body`/
    # `issue_number`/`state` all live here rather than as their own columns,
    # the same "one JSON blob, not five nullable columns" choice
    # `TaskModel.delivery_json` already makes for `DeliveryRequest`.
    payload_json: Mapped[str] = mapped_column(Text, default="{}")
    state: Mapped[str] = mapped_column(String(32))
    # `ForgeOutcome.to_dict()`, once a `FORGE_OPERATION_RESULT` resolves this
    # row. Null until then -- same "what happened, not what was asked"
    # split `TaskModel.result_json` already has against `payload_json` above.
    result_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    requested_by_user_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    requested_by_email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    approval_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # WK-20260902-forge-binding, issue #79/#80 (PR B4), migrations/
    # 0014_forge_binding.sql. Same role `TaskModel.revision` plays: bumped
    # by every mutator in `store.py` that touches this row (create, decide,
    # dispatch, resolve), and what `/api/v1/decisions`'s ETag/If-Match
    # optimistic concurrency compares against once that endpoint started
    # projecting this table alongside `TaskModel`. Added a migration after
    # 0012 rather than in it, because nothing needed it until the Decision
    # Center did.
    revision: Mapped[int] = mapped_column(Integer, default=1, server_default="1")


class AuditEventModel(Base):
    __tablename__ = "audit_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    entity_type: Mapped[str] = mapped_column(String(64))
    entity_id: Mapped[str] = mapped_column(String(128))
    event_type: Mapped[str] = mapped_column(String(128))
    payload_json: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class MessageReceiptModel(Base):
    __tablename__ = "message_receipts"

    message_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    executor_id: Mapped[str] = mapped_column(String(128))
    message_type: Mapped[str] = mapped_column(String(128))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class IdempotencyRecordModel(Base):
    """A completed write, keyed so an offline retry replays instead of repeating.

    Scoped by (key, endpoint, actor): the same Idempotency-Key sent by a
    different actor, or to a different endpoint, is a different operation and
    must not collide. `request_fingerprint` catches the dangerous case of one key
    reused for a *different* payload, which is a client bug and must be reported
    rather than silently answered with the earlier result.
    """

    __tablename__ = "idempotency_records"

    key: Mapped[str] = mapped_column(String(255), primary_key=True)
    endpoint: Mapped[str] = mapped_column(String(255), primary_key=True)
    actor_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    request_fingerprint: Mapped[str] = mapped_column(String(64))
    status_code: Mapped[int] = mapped_column(Integer)
    response_json: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class OAuthAuthorizationCodeModel(Base):
    __tablename__ = "oauth_authorization_codes"

    code_hash: Mapped[str] = mapped_column(String(128), primary_key=True)
    client_id: Mapped[str] = mapped_column(String(255))
    redirect_uri: Mapped[str] = mapped_column(String(2048))
    user_id: Mapped[str] = mapped_column(String(255))
    scopes_json: Mapped[str] = mapped_column(Text, default="[]")
    code_challenge: Mapped[str] = mapped_column(String(255))
    code_challenge_method: Mapped[str] = mapped_column(String(32), default="S256")
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class OAuthAccessTokenModel(Base):
    __tablename__ = "oauth_access_tokens"

    token_hash: Mapped[str] = mapped_column(String(128), primary_key=True)
    client_id: Mapped[str] = mapped_column(String(255))
    user_id: Mapped[str] = mapped_column(String(255))
    scopes_json: Mapped[str] = mapped_column(Text, default="[]")
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    # The grant this token belongs to: one sign-in and every refresh rotated
    # from it (migrations/0003_mobile_auth.sql). Null for a token issued by the
    # browser OAuth flow, which has no refresh chain — revoking one of those
    # revokes that single token.
    grant_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    # Set once and never cleared. `store.get_oauth_access_token` refuses a
    # revoked token, so revocation reaches the MCP transport and the mobile API
    # alike — one credential store, not two.
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class OAuthRefreshTokenModel(Base):
    """A single-use credential that mints access tokens for one grant.

    `consumed_at` is what makes rotation safe to detect: presenting a refresh
    token that was already exchanged means a replay or a stolen copy, and the
    only safe reading is theft. That presentation revokes the whole grant
    instead of being answered with a fresh pair.

    `expires_at` is carried forward unchanged by every rotation, so a grant has
    an absolute lifetime. Extending it on each refresh would turn a stolen
    refresh token into an unbounded session.
    """

    __tablename__ = "oauth_refresh_tokens"

    token_hash: Mapped[str] = mapped_column(String(128), primary_key=True)
    grant_id: Mapped[str] = mapped_column(String(128))
    client_id: Mapped[str] = mapped_column(String(255))
    user_id: Mapped[str] = mapped_column(String(255))
    scopes_json: Mapped[str] = mapped_column(Text, default="[]")
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
