import json

from gateway.app.services.mission_completion import (
    CompletionPolicy,
    DeliveryMode,
    build_completion_evidence,
    evaluate_completion_gate,
)


def test_successful_agent_exit_is_only_implemented_without_validation() -> None:
    evidence = build_completion_evidence(
        task_state="completed",
        result_json=json.dumps({}),
        delivery_result_json=None,
    )
    assert evidence.implemented is True
    assert evidence.validated is False
    assert evidence.delivered is False
    assert evidence.stage == "implemented"
    assert evidence.remains == ("validation",)


def test_passing_tests_advance_to_validated_but_not_delivered() -> None:
    evidence = build_completion_evidence(
        task_state="completed",
        result_json=json.dumps({"tests_ran": [{"name": "pytest -q", "passed": True}]}),
        delivery_result_json=None,
    )
    assert evidence.validated is True
    assert evidence.delivered is False
    assert evidence.stage == "validated"
    assert evidence.remains == ("delivery",)


def test_failed_validation_is_preserved_as_machine_readable_evidence() -> None:
    evidence = build_completion_evidence(
        task_state="completed",
        result_json=json.dumps({"tests_ran": [{"name": "pytest -q", "passed": False, "details": "1 failed"}]}),
        delivery_result_json=None,
    )
    assert evidence.validated is False
    assert evidence.failure_evidence == ("validation:test:pytest -q",)


def test_commit_and_push_are_delivery_but_never_imply_merge() -> None:
    evidence = build_completion_evidence(
        task_state="completed",
        result_json=json.dumps({"tests_ran": [{"name": "pytest -q", "passed": True}]}),
        delivery_result_json=json.dumps(
            {
                "outcome": "committed_and_pushed",
                "branch": "codexbridge/mission-1",
                "commit": "abc123",
                "staged_paths": ["a.py", "b.py"],
                "files_changed": 2,
                "insertions": 10,
                "deletions": 3,
            }
        ),
    )
    assert evidence.delivered is True
    assert evidence.merged is False
    assert evidence.stage == "delivered"
    assert evidence.changed_files == ("a.py", "b.py")
    assert evidence.remains == ("merge_or_operator_finish",)


def test_merge_requires_explicit_evidence_and_prior_delivery() -> None:
    not_delivered = build_completion_evidence(
        task_state="completed",
        result_json=json.dumps({"tests_ran": [{"name": "pytest", "passed": True}]}),
        delivery_result_json=None,
        merged=True,
    )
    assert not_delivered.merged is False

    delivered = build_completion_evidence(
        task_state="completed",
        result_json=json.dumps({"tests_ran": [{"name": "pytest", "passed": True}]}),
        delivery_result_json=json.dumps({"outcome": "committed_only", "commit": "abc"}),
        merged=True,
    )
    assert delivered.merged is True
    assert delivered.stage == "merged"


def test_refused_delivery_preserves_reason() -> None:
    evidence = build_completion_evidence(
        task_state="completed",
        result_json=json.dumps({"tests_ran": [{"name": "pytest", "passed": True}]}),
        delivery_result_json=json.dumps({"outcome": "refused", "reason": "protected_branch"}),
    )
    assert evidence.delivered is False
    assert evidence.failure_evidence == ("delivery:protected_branch",)


def test_artifact_and_operator_review_modes_are_explicit_delivery_modes() -> None:
    artifact = build_completion_evidence(
        task_state="completed",
        result_json=json.dumps({"tests_ran": [{"name": "build", "passed": True, "kind": "static"}]}),
        delivery_result_json=None,
        delivery_mode="artifact",
        artifacts=("artifact://apk/42",),
    )
    assert artifact.delivered is True

    review = build_completion_evidence(
        task_state="completed",
        result_json=json.dumps({"tests_ran": [{"name": "pytest", "passed": True}]}),
        delivery_result_json=None,
        delivery_mode="operator_review",
    )
    assert review.delivered is True
    assert review.merged is False


def test_completion_gate_requires_project_validation_and_delivery_policy() -> None:
    evidence = build_completion_evidence(
        task_state="completed",
        result_json=json.dumps(
            {
                "tests_ran": [{"name": "pytest -q", "passed": True}],
                "static_checks": [{"name": "ruff check .", "passed": True, "kind": "static"}],
            }
        ),
        delivery_result_json=json.dumps({"outcome": "committed_only", "commit": "abc123"}),
    )
    decision = evaluate_completion_gate(
        evidence,
        CompletionPolicy(
            required_validation_kinds=("test", "static"),
            delivery_mode=DeliveryMode.COMMIT_ONLY,
        ),
    )
    assert decision.complete is True
    assert decision.reasons == ()


def test_completion_gate_refuses_missing_required_validation() -> None:
    evidence = build_completion_evidence(
        task_state="completed",
        result_json=json.dumps({"tests_ran": [{"name": "pytest -q", "passed": True}]}),
        delivery_result_json=json.dumps({"outcome": "committed_only", "commit": "abc123"}),
    )
    decision = evaluate_completion_gate(
        evidence,
        CompletionPolicy(required_validation_kinds=("test", "static")),
    )
    assert decision.complete is False
    assert "missing_validation:static" in decision.reasons


def test_completion_gate_never_treats_push_as_merge_permission() -> None:
    evidence = build_completion_evidence(
        task_state="completed",
        result_json=json.dumps({"tests_ran": [{"name": "pytest", "passed": True}]}),
        delivery_result_json=json.dumps({"outcome": "committed_and_pushed", "commit": "abc"}),
        merged=True,
    )
    denied = evaluate_completion_gate(
        evidence,
        CompletionPolicy(delivery_mode=DeliveryMode.PUSH_BRANCH, allow_merge=False),
    )
    assert denied.complete is False
    assert "merge_not_permitted" in denied.reasons

    allowed = evaluate_completion_gate(
        evidence,
        CompletionPolicy(delivery_mode=DeliveryMode.PUSH_BRANCH, allow_merge=True),
    )
    assert allowed.complete is True


def test_pull_request_mode_requires_explicit_link() -> None:
    without_pr = build_completion_evidence(
        task_state="completed",
        result_json=json.dumps({"tests_ran": [{"name": "pytest", "passed": True}]}),
        delivery_result_json=json.dumps({"outcome": "committed_and_pushed", "commit": "abc"}),
    )
    denied = evaluate_completion_gate(
        without_pr,
        CompletionPolicy(delivery_mode=DeliveryMode.PULL_REQUEST),
    )
    assert denied.complete is False
    assert denied.reasons == ("pull_request_missing",)

    with_pr = build_completion_evidence(
        task_state="completed",
        result_json=json.dumps({"tests_ran": [{"name": "pytest", "passed": True}]}),
        delivery_result_json=json.dumps({"outcome": "committed_and_pushed", "commit": "abc"}),
        external_links=("https://github.com/EDortta/CodexBridge/pull/123",),
    )
    allowed = evaluate_completion_gate(
        with_pr,
        CompletionPolicy(delivery_mode=DeliveryMode.PULL_REQUEST),
    )
    assert allowed.complete is True
