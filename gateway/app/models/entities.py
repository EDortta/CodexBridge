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


class OAuthAuthorizationCodeModel(Base):
    __tablename__ = "oauth_authorization_codes"

    code_hash: Mapped[str] = mapped_column(String(128), primary_key=True)
    client_id: Mapped[str] = mapped_column(String(255))
    redirect_uri: Mapped[str] = mapped_column(String(2048))
    user_id: Mapped[str] = mapped_column(String(255))
    user_email: Mapped[str] = mapped_column(String(255))
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
    user_email: Mapped[str] = mapped_column(String(255))
    scopes_json: Mapped[str] = mapped_column(Text, default="[]")
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
