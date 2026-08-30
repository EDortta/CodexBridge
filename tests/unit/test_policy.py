from datetime import datetime, timedelta, timezone

from shared.policy import evaluate_task_policy, policy_level_for_mode, push_is_preauthorized
from shared.protocol import DeliveryRequest, PolicyLevel, SubmitTaskRequest, TaskMode


def _request(
    instruction: str,
    mode: TaskMode = TaskMode.IMPLEMENT,
    delivery: DeliveryRequest | None = None,
) -> SubmitTaskRequest:
    return SubmitTaskRequest(
        executor_id="T610",
        project_id="repo",
        instruction=instruction,
        mode=mode,
        timeout_seconds=300,
        expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
        delivery=delivery,
    )


def test_policy_level_for_mode():
    assert policy_level_for_mode(TaskMode.ANALYZE) == PolicyLevel.READ
    assert policy_level_for_mode(TaskMode.IMPLEMENT) == PolicyLevel.CONTROLLED_WRITE


def test_sensitive_instruction_requires_approval():
    decision = evaluate_task_policy(_request("fazer deploy em production", TaskMode.IMPLEMENT))
    assert decision.level == PolicyLevel.SENSITIVE
    assert decision.approved is False
    assert "instruction_matches_sensitive_keyword" in decision.reasons


# WK-20260830-chatgpt-entry-provider-and-delivery, plan §1C's four-cell matrix.
# Every `SENSITIVE_KEYWORDS` entry gets its own case in the loop below: only
# "push " and "pull request" may ever be lifted by pre-authorization, and
# every other keyword must keep `approved=False` even with a fully-authorized
# `delivery` attached.
NON_PUSH_SENSITIVE_KEYWORDS = (
    "deploy",
    "production",
    "migration",
    "secret",
    "secrets",
    "terraform apply",
    "kubectl apply",
    "rm -rf",
)


def test_keyword_only_is_sensitive_and_unapproved():
    decision = evaluate_task_policy(_request("please push the branch"))
    assert decision.level == PolicyLevel.SENSITIVE
    assert decision.approved is False
    assert decision.reasons == ["instruction_matches_sensitive_keyword"]


def test_allow_push_without_keyword_is_sensitive_but_preauthorized():
    request = _request(
        "implement the feature",
        delivery=DeliveryRequest(branch="feature/uc-1", allow_push=True),
    )
    assert push_is_preauthorized(request) is True
    decision = evaluate_task_policy(request)
    assert decision.level == PolicyLevel.SENSITIVE
    assert decision.approved is True
    assert "delivery_requests_push" in decision.reasons
    assert "push_preauthorized_by_request" in decision.reasons


def test_allow_push_to_main_is_refused_not_preauthorized():
    request = _request(
        "implement the feature",
        delivery=DeliveryRequest(branch="main", allow_push=True),
    )
    assert push_is_preauthorized(request) is False
    decision = evaluate_task_policy(request)
    assert decision.level == PolicyLevel.SENSITIVE
    assert decision.approved is False


def test_keyword_and_preauthorized_push_is_one_decision_not_two():
    """A "push " hit plus a matching `delivery` must not stack into two

    separate sensitive reasons that each independently block approval --
    the pre-authorization has to cover the keyword hit it names.
    """
    request = _request(
        "please push the changes",
        delivery=DeliveryRequest(branch="development", allow_push=True),
    )
    decision = evaluate_task_policy(request)
    assert decision.level == PolicyLevel.SENSITIVE
    assert decision.approved is True
    assert decision.reasons.count("push_preauthorized_by_request") == 1


def test_no_other_sensitive_keyword_is_ever_preauthorized():
    delivery = DeliveryRequest(branch="development", allow_push=True)
    for keyword in NON_PUSH_SENSITIVE_KEYWORDS:
        request = _request(f"please {keyword} now", delivery=delivery)
        decision = evaluate_task_policy(request)
        assert decision.level == PolicyLevel.SENSITIVE, keyword
        assert decision.approved is False, keyword
        assert "push_preauthorized_by_request" not in decision.reasons, keyword
