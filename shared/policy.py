from __future__ import annotations

from dataclasses import dataclass

from shared.protocol import PolicyLevel, SubmitTaskRequest, TaskMode


SENSITIVE_KEYWORDS = (
    "deploy",
    "production",
    "migration",
    "secret",
    "secrets",
    "push ",
    "pull request",
    "terraform apply",
    "kubectl apply",
    "rm -rf",
)


@dataclass(frozen=True)
class PolicyDecision:
    level: PolicyLevel
    approved: bool
    reasons: list[str]


def policy_level_for_mode(mode: TaskMode) -> PolicyLevel:
    if mode in {TaskMode.ANALYZE, TaskMode.REVIEW, TaskMode.TEST}:
        return PolicyLevel.READ
    if mode in {TaskMode.EDIT, TaskMode.IMPLEMENT}:
        return PolicyLevel.CONTROLLED_WRITE
    return PolicyLevel.SENSITIVE


def evaluate_task_policy(request: SubmitTaskRequest) -> PolicyDecision:
    reasons: list[str] = []
    level = policy_level_for_mode(request.mode)
    lowered = request.instruction.lower()
    sensitive_hit = any(keyword in lowered for keyword in SENSITIVE_KEYWORDS)
    if sensitive_hit:
        reasons.append("instruction_matches_sensitive_keyword")
        level = PolicyLevel.SENSITIVE
    approved = level != PolicyLevel.SENSITIVE
    if level == PolicyLevel.SENSITIVE and request.require_destructive_approval:
        approved = False
    return PolicyDecision(level=level, approved=approved, reasons=reasons)
