from __future__ import annotations

from dataclasses import dataclass

from shared.protocol import DeliveryRequest, PolicyLevel, PUSHABLE_BRANCH_PATTERN, SubmitTaskRequest, TaskMode


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


def push_branch_is_allowed(delivery: DeliveryRequest | None) -> bool:
    """Whether `delivery.branch` is a branch a pre-authorized push may target.

    `main`/`master` are refused by NOT matching `PUSHABLE_BRANCH_PATTERN`,
    never by a separate denylist -- one definition, imported by both sides
    (see the pattern's own docstring). A `delivery` with no branch, or a
    branch failing the pattern, is never "pushable" regardless of
    `allow_push`.
    """
    if delivery is None or not delivery.branch:
        return False
    return bool(PUSHABLE_BRANCH_PATTERN.match(delivery.branch))


def push_is_preauthorized(request: SubmitTaskRequest) -> bool:
    """Whether this request's own `delivery` block authorizes a push.

    WK-20260830-chatgpt-entry-provider-and-delivery. This is narrow by
    construction: it only ever answers `True` for the exact shape
    `allow_push=True` + a branch matching `PUSHABLE_BRANCH_PATTERN`. It is
    never a general bypass of `SENSITIVE_KEYWORDS` -- see
    `evaluate_task_policy` below, which still forces `SENSITIVE` for every
    other keyword regardless of this function's answer.
    """
    delivery = request.delivery
    return bool(delivery is not None and delivery.allow_push and push_branch_is_allowed(delivery))


def evaluate_task_policy(request: SubmitTaskRequest) -> PolicyDecision:
    reasons: list[str] = []
    level = policy_level_for_mode(request.mode)
    lowered = request.instruction.lower()
    sensitive_hits = [keyword for keyword in SENSITIVE_KEYWORDS if keyword in lowered]
    if sensitive_hits:
        reasons.append("instruction_matches_sensitive_keyword")
        level = PolicyLevel.SENSITIVE
    # An intent to push is sensitive *structurally* -- whether or not the word
    # "push" ever appears in `instruction`. `delivery` is a typed request for
    # exactly that intent (`shared.protocol.DeliveryRequest`), so it forces
    # the same classification a keyword hit would, and is auditable the same
    # way: the reason lands in `reasons`, which `store.create_task` already
    # records on `task.created`.
    if request.delivery is not None and request.delivery.allow_push:
        reasons.append("delivery_requests_push")
        level = PolicyLevel.SENSITIVE
    approved = level != PolicyLevel.SENSITIVE
    # Pre-authorization narrows -- never widens -- the set of SENSITIVE
    # requests that may proceed without a human decision in the moment. It
    # applies only when EVERY sensitive signal present is one of the two push
    # keywords (`"push "`, `"pull request"`) and/or the structural
    # `delivery_requests_push` reason above, and the request's own `delivery`
    # names a pushable branch. `deploy`, `production`, `migration`, `secret`,
    # `secrets`, `terraform apply`, `kubectl apply` and `rm -rf` are never
    # eligible: any one of them keeps `approved=False` regardless of
    # `delivery`. This is deliberately narrow, typed pre-authorization, not a
    # general SENSITIVE bypass -- `store.create_task` still resolves it
    # through the existing `decide_task_approval(..., APPROVED, reason=...)`
    # path rather than skipping approval outright, so the decision is
    # recorded and auditable exactly like a human-made one (issue #6's
    # `/api/v1/decisions` surface reports it the same way).
    if level == PolicyLevel.SENSITIVE and not approved:
        push_only_keywords = set(sensitive_hits) <= {"push ", "pull request"}
        non_keyword_reasons = [r for r in reasons if r not in {"instruction_matches_sensitive_keyword", "delivery_requests_push"}]
        if push_only_keywords and not non_keyword_reasons and push_is_preauthorized(request):
            approved = True
            reasons.append("push_preauthorized_by_request")
    if level == PolicyLevel.SENSITIVE and request.require_destructive_approval and not approved:
        approved = False
    return PolicyDecision(level=level, approved=approved, reasons=reasons)
