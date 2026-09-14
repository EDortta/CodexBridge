from __future__ import annotations

from enum import Enum

from shared.protocol import TaskState


class MissionState(str, Enum):
    DRAFT = "draft"
    PLANNING = "planning"
    QUEUED = "queued"
    SCHEDULED = "scheduled"
    WAITING_EXECUTOR = "waiting_executor"
    RUNNING = "running"
    TESTING = "testing"
    REVIEWING = "reviewing"
    WAITING_HUMAN = "waiting_human"
    BLOCKED = "blocked"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    EXPIRED = "expired"
    LOST = "lost"


TERMINAL_MISSION_STATES = frozenset(
    {
        MissionState.COMPLETED.value,
        MissionState.FAILED.value,
        MissionState.CANCELLED.value,
        MissionState.EXPIRED.value,
        MissionState.LOST.value,
    }
)


LEGAL_MISSION_TRANSITIONS: dict[str, frozenset[str]] = {
    MissionState.DRAFT.value: frozenset({MissionState.PLANNING.value, MissionState.CANCELLED.value}),
    MissionState.PLANNING.value: frozenset(
        {MissionState.QUEUED.value, MissionState.SCHEDULED.value, MissionState.WAITING_HUMAN.value, MissionState.CANCELLED.value}
    ),
    MissionState.SCHEDULED.value: frozenset({MissionState.QUEUED.value, MissionState.CANCELLED.value}),
    MissionState.QUEUED.value: frozenset(
        {
            MissionState.WAITING_EXECUTOR.value,
            MissionState.RUNNING.value,
            MissionState.WAITING_HUMAN.value,
            MissionState.PAUSED.value,
            MissionState.COMPLETED.value,
            MissionState.FAILED.value,
            MissionState.CANCELLED.value,
            MissionState.EXPIRED.value,
            MissionState.LOST.value,
        }
    ),
    MissionState.WAITING_EXECUTOR.value: frozenset(
        {
            MissionState.QUEUED.value,
            MissionState.RUNNING.value,
            MissionState.WAITING_HUMAN.value,
            MissionState.PAUSED.value,
            MissionState.COMPLETED.value,
            MissionState.FAILED.value,
            MissionState.CANCELLED.value,
            MissionState.EXPIRED.value,
            MissionState.LOST.value,
        }
    ),
    MissionState.RUNNING.value: frozenset(
        {
            MissionState.TESTING.value,
            MissionState.REVIEWING.value,
            MissionState.WAITING_HUMAN.value,
            MissionState.BLOCKED.value,
            MissionState.PAUSED.value,
            MissionState.COMPLETED.value,
            MissionState.FAILED.value,
            MissionState.CANCELLED.value,
            MissionState.EXPIRED.value,
            MissionState.LOST.value,
        }
    ),
    MissionState.TESTING.value: frozenset(
        {MissionState.RUNNING.value, MissionState.REVIEWING.value, MissionState.COMPLETED.value, MissionState.FAILED.value, MissionState.CANCELLED.value}
    ),
    MissionState.REVIEWING.value: frozenset(
        {MissionState.RUNNING.value, MissionState.WAITING_HUMAN.value, MissionState.COMPLETED.value, MissionState.FAILED.value, MissionState.CANCELLED.value}
    ),
    MissionState.WAITING_HUMAN.value: frozenset(
        {
            MissionState.QUEUED.value,
            MissionState.WAITING_EXECUTOR.value,
            MissionState.RUNNING.value,
            MissionState.BLOCKED.value,
            MissionState.CANCELLED.value,
        }
    ),
    MissionState.BLOCKED.value: frozenset(
        {MissionState.PLANNING.value, MissionState.QUEUED.value, MissionState.WAITING_HUMAN.value, MissionState.CANCELLED.value}
    ),
    MissionState.PAUSED.value: frozenset(
        {
            MissionState.RUNNING.value,
            MissionState.WAITING_EXECUTOR.value,
            MissionState.CANCELLED.value,
            MissionState.EXPIRED.value,
            MissionState.LOST.value,
        }
    ),
    MissionState.COMPLETED.value: frozenset({MissionState.WAITING_EXECUTOR.value, MissionState.QUEUED.value}),
    MissionState.FAILED.value: frozenset({MissionState.PLANNING.value, MissionState.QUEUED.value, MissionState.CANCELLED.value}),
    MissionState.CANCELLED.value: frozenset(),
    MissionState.EXPIRED.value: frozenset({MissionState.WAITING_EXECUTOR.value, MissionState.QUEUED.value}),
    MissionState.LOST.value: frozenset({MissionState.WAITING_EXECUTOR.value, MissionState.QUEUED.value}),
}


class MissionTransitionError(ValueError):
    pass


def mission_state_from_task_state(task_state: str) -> str:
    mapping = {
        TaskState.QUEUED.value: MissionState.QUEUED.value,
        TaskState.WAITING_EXECUTOR.value: MissionState.WAITING_EXECUTOR.value,
        TaskState.AWAITING_APPROVAL.value: MissionState.WAITING_HUMAN.value,
        TaskState.RUNNING.value: MissionState.RUNNING.value,
        TaskState.PAUSING.value: MissionState.RUNNING.value,
        TaskState.PAUSED.value: MissionState.PAUSED.value,
        TaskState.RESUMING.value: MissionState.RUNNING.value,
        TaskState.RESTARTING.value: MissionState.RUNNING.value,
        TaskState.COMPLETED.value: MissionState.COMPLETED.value,
        TaskState.FAILED.value: MissionState.FAILED.value,
        TaskState.CANCELLED.value: MissionState.CANCELLED.value,
        TaskState.EXPIRED.value: MissionState.EXPIRED.value,
        TaskState.LOST.value: MissionState.LOST.value,
    }
    return mapping.get(task_state, MissionState.FAILED.value)


def assert_legal_transition(current: str, target: str) -> None:
    if current == target:
        return
    if target not in LEGAL_MISSION_TRANSITIONS.get(current, frozenset()):
        raise MissionTransitionError(f"illegal_mission_transition:{current}:{target}")
