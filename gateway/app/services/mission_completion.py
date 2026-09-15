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
