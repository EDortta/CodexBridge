"""The forge-neutral surface any provider module in this package exposes.

WK-20260902-forge-github-module, issue #80/#79 (PR B2). Mirrors
`agent/codex_bridge_agent/runners/base.py`'s role for `runners/` almost
exactly: `Runner`/`RunnerCapabilities` there declare what a coding-agent
provider can do inside its own sandbox; `ForgeOutcome`/`ForgeOperationRunner`
here declare what a forge provider did OUTSIDE any sandbox, on the executor
process itself, against real third-party infrastructure.

`ForgeOutcome` is deliberately shaped like `agent.codex_bridge_agent.
git_delivery.DeliveryOutcome` -- the other executor-side, outside-the-sandbox,
network-touching operation this codebase already has, and the module this PR
is instructed to copy property-by-property from. Both are frozen dataclasses
with an `attempted` flag, a closed `outcome` vocabulary, an optional `reason`
naming a refusal, and a `to_dict()` for the envelope that eventually reports
this back (wiring that envelope is B3; nothing here sends one yet).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable


LogSender = Callable[[str, str], Awaitable[None]]


# `gh`'s own stdout/stderr is third-party text of unbounded size: it crosses
# the websocket to the gateway and lands in a stored result blob. The
# precedent this module mirrors, `DeliveryOutcome`, avoids the question
# entirely by carrying structured facts only (`commit`, `remote_sha`,
# `files_changed`) and never a command's raw output. Keeping the output here
# is a deliberate departure -- a refusal is much harder to diagnose without
# it, and `gh` reports the forge's own error text nowhere else -- so it is
# bounded instead of dropped, at the one place every outcome is built.
MAX_CAPTURED_OUTPUT = 2000

# `issue_view`'s (WK-20260902-forge-binding, issue #79/#80 PR B4) own bound,
# separate from `MAX_CAPTURED_OUTPUT` above on purpose: `stdout`/`stderr` are
# DIAGNOSTIC -- `gh`'s own process output, useful for debugging a refusal,
# never the primary payload a caller reads. `issue_title`/`issue_body` below
# ARE the primary payload for `issue_view` -- the text
# `instructions.build_task_instruction` places inside
# `--- BEGIN UNTRUSTED ISSUE CONTENT ---`, the same role a `docs:NNN` file's
# contents already play. Truncating it at 2000 characters the way diagnostic
# output is truncated would silently hand the provider a clipped issue body
# with no signal that anything was cut. Matches
# `shared.protocol.ForgeOperationRequest.body`'s own `max_length=65536` --
# the size GitHub already lets an operator write into an issue via this same
# codebase's `issue_open`/`issue_comment`, so a `gh issue view` reading one
# back needs at least as much room.
MAX_CAPTURED_ISSUE_BODY = 65536


def _truncate_captured(text: str | None) -> str | None:
    if text is None or len(text) <= MAX_CAPTURED_OUTPUT:
        return text
    dropped = len(text) - MAX_CAPTURED_OUTPUT
    return f"{text[:MAX_CAPTURED_OUTPUT]}\n[... {dropped} more characters dropped]"


def _truncate_issue_body(text: str | None) -> str | None:
    if text is None or len(text) <= MAX_CAPTURED_ISSUE_BODY:
        return text
    dropped = len(text) - MAX_CAPTURED_ISSUE_BODY
    return f"{text[:MAX_CAPTURED_ISSUE_BODY]}\n[... {dropped} more characters dropped]"


@dataclass(frozen=True)
class ForgeOutcome:
    """What happened when the executor tried to run one forge operation.

    `outcome` is one of `"succeeded"`, `"skipped"`, `"refused"` -- the same
    three-way split `DeliveryOutcome.outcome` uses (that one also has
    `"committed_only"`/`"committed_and_pushed"`, which do not apply here: a
    forge operation has no partial-success shape, it either ran and its
    post-condition held, or it did not run at all). `"skipped"` is kept for
    parity even though no operation in this PR produces it yet -- `DELETE`
    does not exist in `ForgeOperationKind`, so there is no "nothing to do"
    case today; a future kind might have one.

    The per-operation result fields below are a union across all four
    `ForgeOperationKind` members, exactly like `DeliveryOutcome` unions the
    fields of a commit-only and a commit-and-push result: `issue_number` and
    `issue_url` are populated by `issue_open` (and `issue_number` echoed back
    by `issue_comment`/`issue_close`); `issues` only by `issue_list`. A field
    a given `kind` does not produce is simply left at its default.
    """

    attempted: bool
    outcome: str  # "succeeded" | "skipped" | "refused"
    reason: str | None = None
    kind: str | None = None
    repo_identity: str | None = None
    issue_number: int | None = None
    issue_url: str | None = None
    issues: list[dict[str, Any]] = field(default_factory=list)
    # `issue_view` only (WK-20260902-forge-binding, PR B4) -- the fields
    # `gh:N` resolution actually reads. Left at their default (`None`) by
    # every other kind, the same "a field a given kind does not produce is
    # simply left at its default" posture this dataclass's own docstring
    # already states for `issue_number`/`issue_url`/`issues`.
    issue_title: str | None = None
    issue_body: str | None = None
    return_code: int | None = None
    stdout: str | None = None
    stderr: str | None = None

    def __post_init__(self) -> None:
        # Truncation lives here rather than at each construction site in
        # `github.py`: there are twenty of them today and every future
        # operation adds more, so a per-site cap is a rule that holds until
        # someone forgets it once.
        object.__setattr__(self, "stdout", _truncate_captured(self.stdout))
        object.__setattr__(self, "stderr", _truncate_captured(self.stderr))
        object.__setattr__(self, "issue_body", _truncate_issue_body(self.issue_body))

    def to_dict(self) -> dict[str, Any]:
        return {
            "attempted": self.attempted,
            "outcome": self.outcome,
            "reason": self.reason,
            "kind": self.kind,
            "repo_identity": self.repo_identity,
            "issue_number": self.issue_number,
            "issue_url": self.issue_url,
            "issues": self.issues,
            "issue_title": self.issue_title,
            "issue_body": self.issue_body,
            "return_code": self.return_code,
            "stdout": self.stdout,
            "stderr": self.stderr,
        }


# The common signature every forge provider module in this package exposes --
# `github.py`'s `run_forge_operation` today, a future `gitlab.py`/`forgejo.py`
# tomorrow. A plain `Callable` type alias, not a `typing.Protocol` class: the
# function takes keyword-only arguments (`project_root`, `operation`,
# `settings`, `task_id`, `send_log`), which `Protocol.__call__` cannot express
# precisely, and this package has no dispatch table yet that would need to
# hold one of these polymorphically -- that routing (which provider a given
# operation targets) does not exist before B3 wires anything in. Kept here,
# next to `ForgeOutcome`, purely as the documented contract a new provider
# module must match.
ForgeOperationRunner = Callable[..., Awaitable[ForgeOutcome]]
"""`async def run_forge_operation(*, project_root: Path, operation:
ForgeOperationRequest, settings: AgentSettings, task_id: str | None,
send_log: LogSender) -> ForgeOutcome`"""
