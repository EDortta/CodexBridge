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
