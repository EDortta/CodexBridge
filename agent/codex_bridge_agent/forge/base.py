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
    return_code: int | None = None
    stdout: str | None = None
    stderr: str | None = None

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
