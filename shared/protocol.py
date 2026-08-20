from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


EXECUTOR_TOKEN_HEADER = "X-Executor-Token"
"""Header carrying the executor machine token on the `/agent/ws` handshake.

The token used to travel as a query parameter, which put it verbatim in every
access log on the path — 37 lines in the gateway journal and 70 in nginx's,
counted on 2026-08-10 (#15). A WebSocket handshake is an HTTP request and
carries headers normally, so the credential does not belong in the URL.
"""


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
    PAUSING = "pausing"
    PAUSED = "paused"
    RESUMING = "resuming"
    RESTARTING = "restarting"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    EXPIRED = "expired"
    LOST = "lost"


# States from which a cancel is meaningful, shared by the HTTP `/stop` route
# and the MCP `cancel_codex_task` tool. A single definition so the two
# surfaces cannot drift the way they did before issue #17's review caught
# `cancel_codex_task` silently no-op'ing on `paused`/`pausing`/`resuming`/
# `restarting` while `/stop` already covered them.
STOPPABLE_TASK_STATES = frozenset(
    {
        TaskState.QUEUED.value,
        TaskState.WAITING_EXECUTOR.value,
        TaskState.PAUSING.value,
        TaskState.PAUSED.value,
        TaskState.RESUMING.value,
        TaskState.RESTARTING.value,
        TaskState.RUNNING.value,
        TaskState.AWAITING_APPROVAL.value,
    }
)

# Default window (seconds) a cancelled-but-unacknowledged task stays worth
# resending `task.cancel` for on executor reconnect. One literal, referenced
# by `Settings.cancel_replay_max_age_seconds`, `AgentHub.__init__` and
# `store.list_tasks_requiring_cancel_replay` so the three cannot drift apart.
DEFAULT_CANCEL_REPLAY_MAX_AGE_SECONDS = 86400

# Same idea, for tasks stuck in PAUSING/RESUMING/RESTARTING with no `task.ack`
# (issue #17 council, "the sweep skeptic"): `list_tasks_requiring_control_replay`
# used to have no bound at all, unlike its cancel sibling above, so a
# year-old pending control was replayed on every reconnect forever.
DEFAULT_CONTROL_REPLAY_MAX_AGE_SECONDS = 86400

# Upper bound accepted for either replay window. `datetime.now(tz) -
# timedelta(seconds=...)` raises `OverflowError` well before this — the cap
# exists so a misconfigured operator gets a rejected setting at startup
# instead of every `AgentHub.register()` crashing after `websocket.accept()`,
# which left a dead connection in `hub.connections` with no way to close it
# (issue #17 council, "the second caller"). 10 years is generous against any
# realistic "replay indefinitely" intent without going anywhere near the
# `timedelta` ceiling (~2.7e11 seconds).
MAX_REPLAY_MAX_AGE_SECONDS = 315360000


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
    TASK_PAUSE = "task.pause"
    TASK_RESUME = "task.resume"
    TASK_RESTART = "task.restart"
    TASK_CANCELLED = "task.cancelled"
    ERROR = "error"


class ApprovalDecision(str, Enum):
    APPROVED = "approved"
    REJECTED = "rejected"
    # Distinct from REJECTED so a Decision DTO can tell an operator "send this
    # back for changes" apart from "this will not run" (issue #6). Both still
    # cancel the task: there is no protocol capability to hold it open for a
    # resubmission, so pretending otherwise would be the same failure
    # `routes/sessions.py` names for pause/resume/restart — a control that
    # reports success and changes nothing.
    REVISION_REQUESTED = "revision_requested"


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
