from datetime import datetime, timedelta, timezone

from shared.policy import evaluate_task_policy, policy_level_for_mode
from shared.protocol import PolicyLevel, SubmitTaskRequest, TaskMode


def _request(instruction: str, mode: TaskMode) -> SubmitTaskRequest:
    return SubmitTaskRequest(
        executor_id="T610",
        project_id="repo",
        instruction=instruction,
        mode=mode,
        timeout_seconds=300,
        expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
    )


def test_policy_level_for_mode():
    assert policy_level_for_mode(TaskMode.ANALYZE) == PolicyLevel.READ
    assert policy_level_for_mode(TaskMode.IMPLEMENT) == PolicyLevel.CONTROLLED_WRITE


def test_sensitive_instruction_requires_approval():
    decision = evaluate_task_policy(_request("fazer deploy em production", TaskMode.IMPLEMENT))
    assert decision.level == PolicyLevel.SENSITIVE
    assert decision.approved is False
    assert "instruction_matches_sensitive_keyword" in decision.reasons

