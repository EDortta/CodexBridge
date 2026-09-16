from __future__ import annotations

import json
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class CompletionStage(str, Enum):
    IMPLEMENTED = "implemented"
    VALIDATED = "validated"
    DELIVERED = "delivered"
    MERGED = "merged"


@dataclass(frozen=True)
class ValidationEvidence:
    name: str
    passed: bool
    kind: str = "test"
    details: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "kind": self.kind,
            "passed": self.passed,
            "details": self.details,
        }


@dataclass(frozen=True)
class MissionCompletionEvidence:
    implemented: bool
    validated: bool
    delivered: bool
    merged: bool
    changed_files: tuple[str, ...] = ()
    branch: str | None = None
    commit: str | None = None
    diff_summary: dict[str, int] = field(default_factory=dict)
    validations: tuple[ValidationEvidence, ...] = ()
    review_outcome: str | None = None
    artifacts: tuple[str, ...] = ()
    delivery_outcome: str | None = None
    delivery_mode: str | None = None
    external_links: tuple[str, ...] = ()
    failure_evidence: tuple[str, ...] = ()
    remains: tuple[str, ...] = ()

    @property
    def stage(self) -> str | None:
        if self.merged:
            return CompletionStage.MERGED.value
        if self.delivered:
            return CompletionStage.DELIVERED.value
        if self.validated:
            return CompletionStage.VALIDATED.value
        if self.implemented:
            return CompletionStage.IMPLEMENTED.value
        return None

    def to_dict(self) -> dict[str, Any]:
        return {
            "stage": self.stage,
            "implemented": self.implemented,
            "validated": self.validated,
            "delivered": self.delivered,
            "merged": self.merged,
            "changedFiles": list(self.changed_files),
            "branch": self.branch,
            "commit": self.commit,
            "diffSummary": dict(self.diff_summary),
            "validations": [item.to_dict() for item in self.validations],
            "reviewOutcome": self.review_outcome,
            "artifacts": list(self.artifacts),
            "deliveryOutcome": self.delivery_outcome,
            "deliveryMode": self.delivery_mode,
            "externalLinks": list(self.external_links),
            "failureEvidence": list(self.failure_evidence),
            "remains": list(self.remains),
        }


def _json_dict(raw: str | None) -> dict[str, Any]:
    if not raw:
        return {}
    try:
        value = json.loads(raw)
    except (TypeError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


def _validation_rows(result: dict[str, Any]) -> tuple[ValidationEvidence, ...]:
    rows: list[ValidationEvidence] = []

    tests = result.get("tests_ran") or result.get("tests") or []
    if isinstance(tests, list):
        for item in tests:
            if isinstance(item, str):
                rows.append(ValidationEvidence(name=item, passed=True, kind="test"))
            elif isinstance(item, dict):
                rows.append(
                    ValidationEvidence(
                        name=str(item.get("name") or item.get("command") or "test"),
                        passed=bool(item.get("passed", item.get("success", False))),
                        kind=str(item.get("kind") or "test"),
                        details=item.get("details") or item.get("output"),
                    )
                )

    checks = result.get("static_checks") or result.get("checks") or []
    if isinstance(checks, list):
        for item in checks:
            if isinstance(item, str):
                rows.append(ValidationEvidence(name=item, passed=True, kind="static"))
            elif isinstance(item, dict):
                rows.append(
                    ValidationEvidence(
                        name=str(item.get("name") or item.get("command") or "check"),
                        passed=bool(item.get("passed", item.get("success", False))),
                        kind=str(item.get("kind") or "static"),
                        details=item.get("details") or item.get("output"),
                    )
                )
    return tuple(rows)


def build_completion_evidence(
    *,
    task_state: str,
    result_json: str | None,
    delivery_result_json: str | None,
    delivery_mode: str | None = None,
    review_outcome: str | None = None,
    artifacts: tuple[str, ...] = (),
    external_links: tuple[str, ...] = (),
    merged: bool = False,
) -> MissionCompletionEvidence:
    """Build issue #51's operator contract from durable attempt evidence.

    A provider exiting successfully is only ``implemented``. Validation needs
    explicit passing checks. Delivery needs an explicit delivery outcome or a
    produced artifact/operator-review delivery mode. ``merged`` is never
    inferred from success, a commit, a push, or a PR link; callers must provide
    explicit evidence after policy/approval has allowed that external action.
    """
    result = _json_dict(result_json)
    delivery = _json_dict(delivery_result_json)
    validations = _validation_rows(result)

    implemented = task_state == "completed"
    validated = bool(validations) and all(item.passed for item in validations)

    delivery_outcome = delivery.get("outcome")
    commit = delivery.get("commit")
    branch = delivery.get("branch")
    changed_files = tuple(str(path) for path in delivery.get("staged_paths", []) if isinstance(path, str))
    diff_summary = {
        "filesChanged": int(delivery.get("files_changed") or 0),
        "insertions": int(delivery.get("insertions") or 0),
        "deletions": int(delivery.get("deletions") or 0),
    }

    explicit_delivery = delivery_outcome in {"committed_only", "committed_and_pushed"}
    artifact_delivery = delivery_mode == "artifact" and bool(artifacts)
    operator_review_delivery = delivery_mode == "operator_review" and implemented
    delivered = implemented and (explicit_delivery or artifact_delivery or operator_review_delivery)

    failures: list[str] = []
    if task_state in {"failed", "cancelled", "lost", "expired"}:
        failures.append(f"task:{task_state}")
    failures.extend(f"validation:{item.kind}:{item.name}" for item in validations if not item.passed)
    if delivery_outcome == "refused":
        failures.append(f"delivery:{delivery.get('reason') or 'refused'}")

    remains: list[str] = []
    if implemented and not validated:
        remains.append("validation")
    if validated and not delivered:
        remains.append("delivery")
    if delivered and not merged:
        remains.append("merge_or_operator_finish")

    return MissionCompletionEvidence(
        implemented=implemented,
        validated=validated,
        delivered=delivered,
        merged=bool(merged and delivered),
        changed_files=changed_files,
        branch=branch,
        commit=commit,
        diff_summary=diff_summary,
        validations=validations,
        review_outcome=review_outcome,
        artifacts=artifacts,
        delivery_outcome=delivery_outcome,
        delivery_mode=delivery_mode,
        external_links=external_links,
        failure_evidence=tuple(failures),
        remains=tuple(remains),
    )


class DeliveryMode(str, Enum):
    COMMIT_ONLY = "commit_only"
    PUSH_BRANCH = "push_branch"
    PULL_REQUEST = "pull_request"
    ARTIFACT = "artifact"
    OPERATOR_REVIEW = "operator_review"


@dataclass(frozen=True)
class CompletionPolicy:
    required_validation_kinds: tuple[str, ...] = ("test",)
    delivery_mode: DeliveryMode = DeliveryMode.COMMIT_ONLY
    require_review: bool = False
    allow_merge: bool = False


def infer_delivery_mode(delivery_json: str | None) -> DeliveryMode:
    """Infer the safe delivery mode from the Mission's durable request.

    No delivery request means "return the validated work to the operator".
    A requested delivery is commit-only unless it explicitly authorizes push.
    PR/artifact modes are never inferred because they require explicit project
    policy and external evidence.
    """
    raw = _json_dict(delivery_json)
    if not raw:
        return DeliveryMode.OPERATOR_REVIEW
    if bool(raw.get("allow_push")):
        return DeliveryMode.PUSH_BRANCH
    return DeliveryMode.COMMIT_ONLY


def completion_policy_from_project_config(
    config_json: str | None, delivery_json: str | None
) -> CompletionPolicy:
    """Build issue #51's gate from durable project configuration.

    Projects may define ``completion_policy`` in their existing config JSON:
    ``required_validation_kinds``, ``delivery_mode``, ``require_review`` and
    ``allow_merge``. Missing or malformed values fail to conservative defaults:
    tests are required, merge is forbidden, and delivery mode is inferred only
    from the Mission's already-authorized delivery request.
    """
    config = _json_dict(config_json)
    raw = config.get("completion_policy")
    raw = raw if isinstance(raw, dict) else {}

    kinds = raw.get("required_validation_kinds", ["test"])
    if not isinstance(kinds, list) or not all(isinstance(item, str) and item for item in kinds):
        kinds = ["test"]

    inferred = infer_delivery_mode(delivery_json)
    try:
        mode = DeliveryMode(raw.get("delivery_mode", inferred.value))
    except (TypeError, ValueError):
        mode = inferred

    return CompletionPolicy(
        required_validation_kinds=tuple(kinds),
        delivery_mode=mode,
        require_review=bool(raw.get("require_review", False)),
        allow_merge=bool(raw.get("allow_merge", False)),
    )


@dataclass(frozen=True)
class CompletionDecision:
    complete: bool
    reasons: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {"complete": self.complete, "reasons": list(self.reasons)}


def evaluate_completion_gate(
    evidence: MissionCompletionEvidence,
    policy: CompletionPolicy,
) -> CompletionDecision:
    """Decide whether a Mission may become completed under project policy.

    This is intentionally stricter than provider/task success. Every required
    validation kind must be present and passing, the selected delivery mode must
    have durable evidence, review must be explicit when required, and merged
    state is accepted only when policy explicitly allows merge.
    """
    reasons: list[str] = []

    if not evidence.implemented:
        reasons.append("implementation_not_complete")

    by_kind: dict[str, list[ValidationEvidence]] = {}
    for row in evidence.validations:
        by_kind.setdefault(row.kind, []).append(row)
    for kind in policy.required_validation_kinds:
        rows = by_kind.get(kind, [])
        if not rows:
            reasons.append(f"missing_validation:{kind}")
        elif not all(row.passed for row in rows):
            reasons.append(f"failed_validation:{kind}")

    mode = policy.delivery_mode
    if mode == DeliveryMode.COMMIT_ONLY:
        if evidence.delivery_outcome not in {"committed_only", "committed_and_pushed"} or not evidence.commit:
            reasons.append("commit_delivery_missing")
    elif mode == DeliveryMode.PUSH_BRANCH:
        if evidence.delivery_outcome != "committed_and_pushed" or not evidence.commit:
            reasons.append("push_delivery_missing")
    elif mode == DeliveryMode.PULL_REQUEST:
        if not any(link.startswith("http") and "/pull/" in link for link in evidence.external_links):
            reasons.append("pull_request_missing")
    elif mode == DeliveryMode.ARTIFACT:
        if not evidence.artifacts:
            reasons.append("artifact_missing")
    elif mode == DeliveryMode.OPERATOR_REVIEW:
        # Operator-review-only is a delivery mode, not an approval decision.
        # Reaching this mode means the implementation/validation evidence is
        # handed back to the operator; explicit approval is required only when
        # policy.require_review says so.
        if not evidence.implemented:
            reasons.append("operator_review_handoff_missing")

    if policy.require_review and evidence.review_outcome not in {"approved", "accepted"}:
        reasons.append("review_not_approved")

    if evidence.merged and not policy.allow_merge:
        reasons.append("merge_not_permitted")

    return CompletionDecision(complete=not reasons, reasons=tuple(reasons))
