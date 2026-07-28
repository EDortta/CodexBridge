from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class TaskMode(str, Enum):
    ANALYZE = "analyze"
    REVIEW = "review"
    EDIT = "edit"
    TEST = "test"
    IMPLEMENT = "implement"


class TaskState(str, Enum):
    QUEUED = "queued"
    WAITING_EXECUTOR = "waiting_executor"
    AWAITING_APPROVAL = "awaiting_approval"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    EXPIRED = "expired"
    LOST = "lost"


class PolicyLevel(str, Enum):
    READ = "read"
    CONTROLLED_WRITE = "controlled_write"
    SENSITIVE = "sensitive"


class TaskPriority(str, Enum):
    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"


class AgentMessageType(str, Enum):
    HELLO = "hello"
    HELLO_ACK = "hello_ack"
    HEARTBEAT = "heartbeat"
    TASK_DISPATCH = "task.dispatch"
    TASK_ACK = "task.ack"
    TASK_LOG = "task.log"
    TASK_RESULT = "task.result"
    TASK_CANCEL = "task.cancel"
    TASK_CANCELLED = "task.cancelled"
    ERROR = "error"


class ApprovalDecision(str, Enum):
    APPROVED = "approved"
    REJECTED = "rejected"


class ProjectRegistration(BaseModel):
    project_id: str
    name: str
    path: str
    allowed_modes: list[TaskMode] = Field(default_factory=lambda: list(TaskMode))
    max_timeout_seconds: int = 3600
    sensitive_patterns: list[str] = Field(default_factory=list)
    enabled: bool = True


class ExecutorRegistration(BaseModel):
    executor_id: str
    display_name: str
    machine_token: str
    max_concurrent_tasks: int = 1
    allowed_projects: list[str]
    enabled: bool = True
    expected_timezone: str = "America/Sao_Paulo"
    expected_online_windows: list[str] = Field(default_factory=list)


class SubmitTaskRequest(BaseModel):
    executor_id: str
    project_id: str
    instruction: str = Field(min_length=1, max_length=12000)
    mode: TaskMode
    timeout_seconds: int = Field(ge=30, le=86400)
    priority: TaskPriority = TaskPriority.NORMAL
    run_when_available: bool = False
    expires_at: datetime
    require_destructive_approval: bool = True


class ContinueSessionRequest(BaseModel):
    task_id: str
    instruction: str = Field(min_length=1, max_length=12000)
    timeout_seconds: int = Field(ge=30, le=86400)


class AgentEnvelope(BaseModel):
    message_id: str
    executor_id: str
    sent_at: datetime
    type: AgentMessageType
    payload: dict[str, Any] = Field(default_factory=dict)


class ToolResponse(BaseModel):
    ok: bool = True
    message: str
    data: dict[str, Any] = Field(default_factory=dict)
