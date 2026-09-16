import pytest

from gateway.app.services.mission_types import (
    MissionTransitionError,
    assert_legal_transition,
    mission_state_from_task_state,
)
from shared.protocol import TaskState


def test_legacy_terminal_task_states_keep_their_public_mission_state() -> None:
    assert mission_state_from_task_state(TaskState.EXPIRED.value) == "expired"
    assert mission_state_from_task_state(TaskState.LOST.value) == "lost"


@pytest.mark.parametrize(
        ("current", "target"),
        [
            ("queued", "paused"),
            ("completed", "waiting_executor"),
            ("completed", "queued"),
            ("expired", "waiting_executor"),
            ("lost", "queued"),
            ("reviewing", "queued"),
            ("reviewing", "waiting_executor"),
        ],
)
def test_legacy_session_control_paths_can_project_into_mission_state(current: str, target: str) -> None:
    assert_legal_transition(current, target)


def test_unrelated_terminal_missions_still_reject_cancelled_restarts() -> None:
    with pytest.raises(MissionTransitionError):
        assert_legal_transition("cancelled", "running")


def test_finished_missions_do_not_skip_the_queue_on_restart() -> None:
    with pytest.raises(MissionTransitionError):
        assert_legal_transition("completed", "running")
