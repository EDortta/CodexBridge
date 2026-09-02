from __future__ import annotations

from dataclasses import dataclass

from shared.protocol import (
    DeliveryRequest,
    ForgeOperationKind,
    PolicyLevel,
    PUSHABLE_BRANCH_PATTERN,
    SubmitTaskRequest,
    TaskMode,
)


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


def forge_operation_policy_level(kind: ForgeOperationKind) -> PolicyLevel:
    """The policy tier a forge operation is classified at -- issue #80/#79.

    `ISSUE_LIST` is `READ`: it costs the forge nothing and changes nothing.
    Every write kind -- `ISSUE_OPEN`, `ISSUE_COMMENT`, `ISSUE_CLOSE` -- is
    `SENSITIVE`, unconditionally, for every value of every field on
    `ForgeOperationRequest`.

    This is the single most important thing in this module, so read it
    before adding anything near this function. There is deliberately no
    `forge_operation_is_preauthorized` sibling to `push_is_preauthorized`
    above, and there must never be one added by analogy. `push_is_preauthorized`
    exists because push already had a typed, narrow shape --
    `DeliveryRequest.allow_push` plus `PUSHABLE_BRANCH_PATTERN` -- before
    pre-authorization was layered onto it; the field predates the bypass, and
    the bypass is scoped to exactly what that field already meant. Reaching
    for the same shape here -- "a forge write needs its own
    `allow_forge_write` flag the way push needed `allow_push`" -- is exactly
    the mistake this function exists to head off. No field on
    `ForgeOperationRequest`, present or future, may let a write skip the
    human approval gate.

    `delivery.allow_push` already establishes the pattern this follows:
    `evaluate_task_policy` forces `SENSITIVE` for it "whether or not the word
    push ever appears in instruction" -- a structural classification, not a
    textual one. A forge write is `SENSITIVE` the same way, structurally, and
    for a stronger reason than push has: the credential that performs it
    never enters the agent's sandbox at all
    (WK-20260902-forge-protocol-and-policy -- the sandbox has no network,
    tested empirically on devel3 on 2026-09-01, so forge writes run on the
    EXECUTOR process, outside the sandbox, and the credential stays there).
    A forge write is also a published, third-party-visible act -- an issue
    opened, a comment posted, an issue closed -- made in the operator's name
    on infrastructure this codebase does not control. There is no request
    shape trusted enough to skip a human seeing it first.

    If a future change wants to narrow which forge writes need approval, it
    must not live here as a bypass function: `forge_operation_policy_level`
    returning `SENSITIVE` for every kind but `ISSUE_LIST` is the whole
    guarantee. `tests/unit/test_forge_policy.py` iterates
    `ForgeOperationKind` by the enum itself, not a literal list, and asserts
    this property exhaustively over field combinations for every write kind,
    so it fails the moment a new kind or a new field quietly earns an
    exception.
    """
    if kind is ForgeOperationKind.ISSUE_LIST:
        return PolicyLevel.READ
    return PolicyLevel.SENSITIVE


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
