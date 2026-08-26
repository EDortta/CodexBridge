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
