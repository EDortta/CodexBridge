from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, String, Text
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
    # SHA-256 of the machine token, issue #76's minimal cut. `/agent/ws`
    # (`gateway/app/main.py:agent_ws`) compares `hash_token(presented)`
    # against this column instead of a clear-text value read out of
    # `metadata_json`. Nullable for the same portability reason as `node_id`
    # above: an executor seeded from `registry.json` before this column
    # existed has none until `store.upsert_registry` backfills it from its
    # own `metadata_json["machine_token"]` at startup -- see that function's
    # docstring for why the backfill lives in Python rather than in the
    # migration.
    machine_token_hash: Mapped[str | None] = mapped_column(String(128), nullable=True)


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
    # Issue #76 (minimal cut): why this node may or may not be dispatched to,
    # distinct from `enabled` -- `enabled` keeps meaning "may this node be
    # given work right now" and is flipped alongside a revoke as a matter of
    # course; `admission_state` is what `/agent/ws` actually gates the
    # handshake on (`admission_state == "revoked"` closes the reconnect with
    # `4403`), so a future reason to disable a node without revoking its
    # credential does not have to reuse revocation's enforcement path.
    # `"invited"`/`"suspended"` are states the issue anticipates; only
    # `"enrolled"` (the default, and every pre-#76 row via
    # `0013_node_enrollment.sql`'s backfill) and `"revoked"` are written by
    # this cut.
    admission_state: Mapped[str] = mapped_column(String(32), default="enrolled")


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
    trusted association only because directory and repository names happen to
    match": an unconfirmed guess is recorded as `observed`, never as
    `confirmed`, and only an operator moves it.
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

    `resource_key`/`resource_path` split (WK-20260902-gh73-discovery-adoption,
    `migrations/0013_discovery_resource_key_hash.sql`). Issue #73 Stage 3
    wrote the candidate's absolute path straight into `resource_key`, a
    `varchar(255)` that also anchors the composite unique index `(node_id,
    kind, resource_key)`. SQLite never enforced that width; MySQL -- a
    declared target via `aiomysql` -- does, so a path near the protocol's own
    2048-character limit was one `codex exec` scan away from an insert
    failure nobody had hit yet. See `shared.security.hash_resource_key`'s
    docstring for why widening the column was rejected in favor of hashing.

    `resource_key` is now `hash_resource_key(path)` -- 64 hex characters,
    comfortably inside both the column and the MySQL index-key limit that
    likely sized the original 255. `resource_path` carries the real path, at
    the same 2048-character width `DiscoveredCandidate.resource_key` already
    allows, unindexed. It joins `root_path` in the same sensitive-data
    category `docs/control-plane.md` documents for `WorkspaceBindingModel.
    local_path`: operator-surface-only, never `ProjectStatus`/`Session`/
    `Mission`/any MCP tool (`docs/api/README.md`, "Fields that must never
    ship").
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
    resource_path: Mapped[str | None] = mapped_column(String(2048), nullable=True)
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
    # WK-20260902-issue-materialize / issue #78, Commit 1. Set only by
    # `store.apply_epic_materialization`, once the executor confirms it wrote
    # this epic's markdown -- never guessed or defaulted by the gateway,
    # which does not know the project's real filesystem layout
    # (`docs/architecture.md`). `materialized_path` is relative to the
    # project root, as the executor reported it.
    # `materialized_revision` is a COPY of `revision` as of that publish, not
    # the current value -- comparing the two at read time is what lets an
    # operator distinguish "never published" (`materialized_path IS NULL`)
    # from "published, N edits ago".
    materialized_path: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    materialized_revision: Mapped[int | None] = mapped_column(Integer, nullable=True)


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
    # WK-20260902-issue-materialize / issue #78, Commit 1. Same meaning as
    # `EpicModel.materialized_path`/`materialized_revision` above -- see that
    # pair's comment for why these are not `provider`/`external_id`.
    materialized_path: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    materialized_revision: Mapped[int | None] = mapped_column(Integer, nullable=True)


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


class ArtifactModel(Base):
    """A retained file this gateway can hand to CodexBridgeMobile — issue #11.

    Nothing in this build *produces* one: there is no ingestion path, no upload
    endpoint and no executor message that writes a row here (see
    `gateway/app/services/artifact_types.py`). Every artifact served today was
    created through `store.create_artifact`, which means a test fixture or an
    operator script. The catalogue endpoints are honest about that rather than
    reporting an always-empty list as if a producer existed.

    `storage_path` is the trap on this table, exactly as `ProjectModel.path` is
    on that one: it is a path relative to `settings.artifacts_root` and it never
    appears in a response (`docs/api/README.md` §"Fields that must never ship").
    `gateway/app/services/artifact_storage.py` is the only code that turns it
    into a real file, and it is what confines it to the root.
    """

    __tablename__ = "artifacts"

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    project_id: Mapped[str] = mapped_column(String(128), ForeignKey("projects.id"))
    # `artifact_types.ARTIFACT_TYPES` / `.ARTIFACT_ORIGINS`. Stored as text
    # rather than a database enum for the same reason every other status column
    # here is: the vocabulary is the contract's, and widening a database enum is
    # a migration where widening a frozenset is not.
    type: Mapped[str] = mapped_column(String(32))
    name: Mapped[str] = mapped_column(String(255))
    version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    size_bytes: Mapped[int] = mapped_column(Integer)
    # Lowercase hex SHA-256 of the bytes. Reported *before* a download so a
    # client can verify what it received — issue #11's "checksums and signing
    # metadata are included before download/install".
    sha256: Mapped[str] = mapped_column(String(64))
    origin: Mapped[str] = mapped_column(String(32))
    content_type: Mapped[str] = mapped_column(String(255), default="application/octet-stream")
    # NEVER serialized. See the class docstring.
    storage_path: Mapped[str] = mapped_column(String(512))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    # Retention metadata, and load-bearing: past this instant the gateway
    # refuses to mint a download token or serve the bytes (`409 conflict`),
    # while the catalogue still lists the row so a client can say why. Null
    # means "kept until an operator removes it".
    retained_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class AndroidBuildModel(Base):
    """APK metadata for one artifact — issue #11's Android half.

    One row per `apk` artifact, keyed by the artifact's own id: an Android build
    *is* an artifact plus this metadata, so inventing a second identifier would
    give the mobile client two ids for one thing and a mapping to keep. That is
    why `GET /api/v1/builds/android/{buildId}` takes an `ArtifactId`.

    `signing_fingerprint` is the SHA-256 certificate fingerprint in the
    colon-separated form `apksigner` prints, normalized on write
    (`artifact_types.normalize_fingerprint`) so one certificate has one
    spelling. It is not a credential: a certificate fingerprint is public by
    construction, and publishing it is what lets an operator refuse an APK
    signed by something else before installing it.
    """

    __tablename__ = "android_builds"

    artifact_id: Mapped[str] = mapped_column(String(128), ForeignKey("artifacts.id"), primary_key=True)
    package_name: Mapped[str] = mapped_column(String(255))
    version_name: Mapped[str] = mapped_column(String(64))
    version_code: Mapped[int] = mapped_column(Integer)
    environment: Mapped[str] = mapped_column(String(32))
    min_sdk_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    changelog: Mapped[str | None] = mapped_column(Text, nullable=True)
    signing_fingerprint: Mapped[str] = mapped_column(String(128))


class ArtifactDownloadTokenModel(Base):
    """A short-lived bearer credential for the bytes of exactly one artifact.

    Stored **hashed**, the same way `OAuthAccessTokenModel` is and through the
    same `shared.security.hash_token`: a reader of the database must not be able
    to download anything. The plaintext exists once, in the response to
    `POST /api/v1/artifacts/{artifactId}/download-token`.

    Four columns make it narrow. `artifact_id` — presenting it on another
    artifact is refused, so a token minted for a public report cannot fetch a
    signed APK. `user_id` — the download re-reads that account at request time
    and re-checks project visibility, so an account disabled or narrowed a
    minute after minting cannot still pull the bytes, the same rule
    refresh-token rotation already applies. `expires_at` — minutes, not hours
    (`settings.artifact_download_token_ttl_seconds`). `grant_id` — which
    sign-in minted it, so `POST /api/v1/auth/revoke` can delete exactly this
    grant's download credentials: a sign-out that left an APK streaming is the
    failure that endpoint exists to prevent, and revoking *by actor* instead
    let a replayed dead token kill a live grant's downloads (found by a council
    round). Null for the grantless browser-OAuth session, which is a value.

    The count in this paragraph is the columns, not the narrowings — the router
    module counts five, because a re-read of the account covers two of them.
    They are consistent; they are counting different things, and saying so here
    is cheaper than the next reader reconciling them.

    It is deliberately **not** single-use. Issue #11 asks for range and
    resumable downloads in the same breath as short-lived authorization, and a
    token consumed by the first request makes a resumed download impossible: the
    client would have to re-authenticate mid-transfer, which is exactly what a
    download token exists to avoid. The lifetime is the control, and it is short
    for that reason.
    """

    __tablename__ = "artifact_download_tokens"

    token_hash: Mapped[str] = mapped_column(String(128), primary_key=True)
    artifact_id: Mapped[str] = mapped_column(String(128), ForeignKey("artifacts.id"))
    user_id: Mapped[str] = mapped_column(String(255))
    # Nullable on purpose: the browser OAuth flow issues access tokens that
    # belong to no grant, and null here means "minted by a grantless session",
    # not "unknown".
    grant_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class TaskLogModel(Base):
    __tablename__ = "task_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    task_id: Mapped[str] = mapped_column(String(128), ForeignKey("tasks.id"))
    offset: Mapped[int]
    stream: Mapped[str] = mapped_column(String(16))
    line: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class AuditEventModel(Base):
    # Declared in the model as well as in `migrations/0011_event_subscriptions.sql`
    # so a **fresh** install gets it: `main.py` bootstraps a new database with
    # `Base.metadata.create_all`, which knows nothing about the migrations
    # directory, so an index that lived only in SQL would exist on upgraded
    # deployments and be missing on new ones — the harder of the two to notice,
    # because it is the one nobody ran a migration for (council round 1, the
    # second caller). `create_all(checkfirst=True)` does not add an index to a
    # table that already exists, which is exactly why 0009 has to carry it too.
    __table_args__ = (
        Index("audit_events_entity_type_id_idx", "entity_type", "id"),
    )

    __tablename__ = "audit_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    entity_type: Mapped[str] = mapped_column(String(64))
    entity_id: Mapped[str] = mapped_column(String(128))
    event_type: Mapped[str] = mapped_column(String(128))
    payload_json: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class NotificationPreferenceModel(Base):
    """Which events one actor wants to be notified about — issue #13.

    Recorded intent, not a delivery mechanism. This build has no push transport —
    reported to the client as `pushDeliveryAvailable: false` in the preferences
    body, not by `GET /api/version`, whose `capabilities` map has no push key —
    and these rows do
    **not** filter `GET /api/v1/events/stream`: a client that subscribed to the
    stream asked for the stream, and silently withholding events from it because
    of a preference set on another device is how a mobile client misses a
    decision it was waiting for. See `gateway/app/api/routes/notifications.py`.

    One row per actor, keyed by `user_id` — the id from `users.json`, never an
    email. There is no `revision`/`ETag`: the only writer of a row is the actor
    it belongs to, through a `PUT` that replaces the document wholesale, so
    there is no concurrent third party for an optimistic check to protect
    against (`ConversationModel` is this schema's other revision-less table, for
    the same kind of reason).
    """

    __tablename__ = "notification_preferences"

    user_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    # JSON list of `event_types.ALL_EVENT_TYPES` members, validated at the route
    # before it is written: an unvalidated list here would be a store of
    # arbitrary caller text echoed back to that caller later.
    event_types_json: Mapped[str] = mapped_column(Text, default="[]", server_default="[]")
    # No `server_default`: `"0"` renders as a quoted literal that Postgres
    # refuses for a boolean column, and every other boolean in this schema
    # (`ExecutorModel.enabled`, `TaskModel.run_when_available`) sets its default
    # in Python and in the migration rather than through SQLAlchemy's DDL.
    push_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


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


class NodeInviteModel(Base):
    """A bearer credential that authorizes exactly one `POST /api/v1/nodes/enroll`.

    Issue #76 (minimal cut). `id` is a separate surrogate key from
    `token_hash` on purpose, unlike `OAuthAccessTokenModel`/
    `OAuthRefreshTokenModel` (where the hash IS the primary key): an invite is
    read by the operator surface that issued it (an id) as often as it is
    looked up by the token a would-be node presents (`token_hash`), and those
    are two different callers with two different keys on hand.

    Protected by `expires_at` (15 minutes, decided at issue time, not
    reconfigurable per invite) rather than by binding it to a claimed
    hostname or machine identity -- `migrations/0009_control_plane.sql`
    already refused to trust a hostname for node identity, for the same
    reason: it is mutable and spoofable, and the TTL is the real boundary.

    `token_hash` only. The raw value is returned once, in the
    `POST /api/v1/nodes/invite` response body, and `gateway/app/api/routes/
    enrollment.py` never passes it to `record_event` or to a log call.
    """

    __tablename__ = "node_invites"

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    token_hash: Mapped[str] = mapped_column(String(128), unique=True)
    created_by: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    consumed_by_node_id: Mapped[str | None] = mapped_column(
        String(128), ForeignKey("nodes.id"), nullable=True
    )
    display_name_hint: Mapped[str | None] = mapped_column(String(255), nullable=True)
