"""Runs one `ForgeOperationRequest` against GitHub, via `gh`.

WK-20260902-forge-github-module, issue #80/#79 (PR B2). This module is
**isolated** on purpose: nothing in `service.py`, nothing in the gateway,
nothing dispatches a `FORGE_OPERATION` envelope into `run_forge_operation`
yet. That wiring is a separate PR (B3), for the same reason B1
(`shared/protocol.py`, `shared/policy.py`) shipped before this one -- each
slice reviewable on its own, and a module that can reach the real network
does not exist half-wired in the meantime.

When B3 does wire this in, it belongs on the same side of the boundary
`agent/codex_bridge_agent/git_delivery.py` already established for
`deliver_changes`: called by `AgentService` AFTER the coding-agent provider's
own process has exited (or, for a forge operation, independent of any
provider process at all -- there is no "coding session" a forge operation
runs inside), never from inside a runner's sandbox
(`agent/codex_bridge_agent/runners/`). A forge write needs network, which
`workspace-write` does not grant, and it carries a credential
(`gh_tool.run_gh`'s `GH_TOKEN`) that must never enter the sandbox a coding
agent's own process attaches to.

Every property this module borrows from `git_delivery.py` is named at its
own point below, in a comment starting `# git_delivery property:` -- so a
reviewer can check each one against its original rather than trusting a
paraphrase.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any, Callable

from agent.codex_bridge_agent.config import AgentSettings
from agent.codex_bridge_agent.forge.base import ForgeOutcome, LogSender
from agent.codex_bridge_agent.forge.gh_tool import GhResult, run_gh
from shared.protocol import ForgeOperationKind, ForgeOperationRequest, REPO_IDENTITY_PATTERN


# `gh issue create`/`gh issue comment` print the created/commented issue's
# URL to stdout on success -- e.g. "https://github.com/owner/repo/issues/42".
# Used only for `issue_open`'s post-condition check below: exit 0 alone is
# not proof an issue exists (# git_delivery property: post-condition
# verification, `git_delivery.py:311-315` compares the remote sha the same
# way rather than trusting `push`'s exit code).
_ISSUE_URL_PATTERN = re.compile(r"/issues/(\d+)\s*$")

# `gh issue list --json ... --limit N`: bounded and explicit rather than
# relying on `gh`'s own default (which is also 30, as of the CLI versions
# this codebase has been run against, but an explicit flag does not drift
# quietly if that default ever changes upstream).
_ISSUE_LIST_DEFAULT_LIMIT = 30
_ISSUE_LIST_JSON_FIELDS = "number,title,state,url"

# `ISSUE_LIST`'s only meaningful `state` value when the request leaves it
# unset -- `gh issue list --state` defaults to "open" too, but this module
# passes it explicitly for the same reason as the `--limit` above.
_DEFAULT_ISSUE_STATE = "open"


def _refused(
    reason: str,
    *,
    kind: ForgeOperationKind | str | None,
    repo_identity: str | None,
    **extra: Any,
) -> ForgeOutcome:
    fields: dict[str, Any] = {
        "kind": kind.value if isinstance(kind, ForgeOperationKind) else kind,
        "repo_identity": repo_identity,
    }
    fields.update(extra)
    return ForgeOutcome(attempted=True, outcome="refused", reason=reason, **fields)


# git_delivery property: re-validation on the executor of what the gateway
# sent (`git_delivery.py`'s module docstring, point 2 -- checked again here
# even though the gateway/`ForgeOperationRequest`'s own pydantic validators
# already checked it, because a compromised or buggy gateway must not be able
# to grant a write by lying about what it already verified). This
# intentionally duplicates `ForgeOperationRequest`'s own
# `@model_validator`/`@field_validator` logic rather than trusting that the
# object handed to this function actually went through it (e.g. a
# `model_construct` bypass upstream).
def _revalidate_locally(operation: ForgeOperationRequest) -> str | None:
    """Returns a refusal reason, or `None` if the request is coherent."""
    if not isinstance(operation.kind, ForgeOperationKind):
        return "invalid_kind"
    # git_delivery property: `_REMOTE_NAME_PATTERN` reapplied to `remote` even
    # though the model has no constraint of its own; here
    # `REPO_IDENTITY_PATTERN` (from B1, `shared/protocol.py`) is reapplied to
    # `repo_identity` even though `ForgeOperationRequest` already enforces it
    # at parse time -- the executor never trusts that the object in hand
    # actually went through that validator.
    if not REPO_IDENTITY_PATTERN.match(operation.repo_identity):
        return "invalid_repo_identity"
    if operation.kind in (ForgeOperationKind.ISSUE_COMMENT, ForgeOperationKind.ISSUE_CLOSE):
        if operation.issue_number is None or operation.issue_number <= 0:
            return "invalid_issue_number"
    if operation.kind is ForgeOperationKind.ISSUE_COMMENT and not operation.body:
        return "invalid_empty_body"
    if operation.kind is ForgeOperationKind.ISSUE_OPEN and not operation.title:
        return "invalid_missing_title"
    if operation.state is not None and operation.state not in {"open", "closed", "all"}:
        return "invalid_state"
    return None


async def run_forge_operation(
    *,
    project_root: Path,
    operation: ForgeOperationRequest,
    settings: AgentSettings,
    task_id: str | None,
    send_log: LogSender,
) -> ForgeOutcome:
    """Runs `operation` against GitHub via `gh`, and reports what happened.

    Never called by anything in this PR -- see the module docstring. Every
    caller this signature is written for (B3) is expected to have already
    checked `shared.policy.forge_operation_policy_level` and gotten a human
    approval for anything but `ISSUE_LIST`; this function does not re-derive
    that decision, because -- like `deliver_changes` -- it trusts that the
    approval gate already ran, and instead re-checks the things a compromised
    gateway could lie about (see `_revalidate_locally`).
    """
    # git_delivery property: machine-level kill switch, off by default,
    # checked BEFORE anything else touches `gh` (`allow_git_delivery` is
    # `git_delivery.py`'s analogous check; `git_delivery.py:198`).
    if not settings.allow_forge_operations:
        return _refused("executor_forge_disabled", kind=operation.kind, repo_identity=operation.repo_identity)

    invalid_reason = _revalidate_locally(operation)
    if invalid_reason is not None:
        return _refused(invalid_reason, kind=operation.kind, repo_identity=operation.repo_identity)

    if operation.kind is ForgeOperationKind.ISSUE_OPEN:
        return await _run_issue_open(project_root, operation, settings, send_log)
    if operation.kind is ForgeOperationKind.ISSUE_COMMENT:
        return await _run_issue_comment(project_root, operation, settings, send_log)
    if operation.kind is ForgeOperationKind.ISSUE_LIST:
        return await _run_issue_list(project_root, operation, settings, send_log)
    if operation.kind is ForgeOperationKind.ISSUE_CLOSE:
        return await _run_issue_close(project_root, operation, settings, send_log)
    # Unreachable given `_revalidate_locally`'s `isinstance` check above and
    # `ForgeOperationKind` being a closed enum -- kept as an explicit refusal
    # rather than falling off the end of the function silently.
    return _refused("unknown_kind", kind=operation.kind, repo_identity=operation.repo_identity)


# git_delivery property: arbitrary caller-supplied text must never become a
# flag position (`git_delivery.py`'s own reasoning for `commit -m subject -m
# body`, applied here to `gh issue create`/`gh issue comment`'s
# `--body-file`). The temp file this function creates is the only thing that
# ever reaches that flag's value -- never `body` itself, positionally or
# otherwise.
async def _run_gh_with_body_file(
    project_root: Path,
    settings: AgentSettings,
    body: str,
    argv_builder: Callable[[Path], list[str]],
) -> tuple[GhResult, list[str]]:
    """Writes `body` to a temp file, runs `argv_builder(tmp_path)` through
    `run_gh`, and always removes the temp file -- including when `gh` fails.
    """
    tmp_path: Path | None = None
    try:
        with NamedTemporaryFile(
            mode="w", prefix="codexbridge-forge-body-", suffix=".md", delete=False, encoding="utf-8"
        ) as handle:
            handle.write(body)
            tmp_path = Path(handle.name)
        args = argv_builder(tmp_path)
        result = await run_gh(
            project_root,
            *args,
            gh_bin=settings.forge_gh_bin,
            credential_relative_path=settings.forge_credential_relative_path,
            timeout_seconds=settings.forge_operation_timeout_seconds,
        )
        return result, args
    finally:
        if tmp_path is not None:
            tmp_path.unlink(missing_ok=True)


async def _run_issue_open(
    project_root: Path,
    operation: ForgeOperationRequest,
    settings: AgentSettings,
    send_log: LogSender,
) -> ForgeOutcome:
    def build(tmp_path: Path) -> list[str]:
        return [
            "issue",
            "create",
            "--repo",
            operation.repo_identity,
            "--title",
            operation.title or "",
            "--body-file",
            str(tmp_path),
        ]

    result, args = await _run_gh_with_body_file(project_root, settings, operation.body or "", build)
    await send_log("stderr", f"forge.gh_argv:{' '.join(args)}")

    if result.refused_reason is not None:
        return _refused(result.refused_reason, kind=operation.kind, repo_identity=operation.repo_identity)
    if not result.ok:
        return _refused(
            "gh_command_failed",
            kind=operation.kind,
            repo_identity=operation.repo_identity,
            return_code=result.returncode,
            stdout=result.stdout,
            stderr=result.stderr,
        )

    # git_delivery property: post-condition verification
    # (`git_delivery.py:311-315`) -- exit code 0 is not proof. Confirm the
    # issue actually exists by parsing its number out of the URL `gh` prints,
    # rather than trusting the return code alone.
    match = _ISSUE_URL_PATTERN.search(result.stdout.strip())
    if match is None:
        return _refused(
            "forge_postcondition_failed:no_issue_url_in_output",
            kind=operation.kind,
            repo_identity=operation.repo_identity,
            return_code=result.returncode,
            stdout=result.stdout,
            stderr=result.stderr,
        )
    return ForgeOutcome(
        attempted=True,
        outcome="succeeded",
        kind=operation.kind.value,
        repo_identity=operation.repo_identity,
        issue_number=int(match.group(1)),
        issue_url=result.stdout.strip(),
        return_code=result.returncode,
        stdout=result.stdout,
        stderr=result.stderr,
    )


async def _run_issue_comment(
    project_root: Path,
    operation: ForgeOperationRequest,
    settings: AgentSettings,
    send_log: LogSender,
) -> ForgeOutcome:
    issue_number = operation.issue_number
    assert issue_number is not None  # guaranteed by `_revalidate_locally`

    def build(tmp_path: Path) -> list[str]:
        return [
            "issue",
            "comment",
            str(issue_number),
            "--repo",
            operation.repo_identity,
            "--body-file",
            str(tmp_path),
        ]

    result, args = await _run_gh_with_body_file(project_root, settings, operation.body or "", build)
    await send_log("stderr", f"forge.gh_argv:{' '.join(args)}")

    if result.refused_reason is not None:
        return _refused(result.refused_reason, kind=operation.kind, repo_identity=operation.repo_identity)
    if not result.ok:
        return _refused(
            "gh_command_failed",
            kind=operation.kind,
            repo_identity=operation.repo_identity,
            issue_number=issue_number,
            return_code=result.returncode,
            stdout=result.stdout,
            stderr=result.stderr,
        )
    return ForgeOutcome(
        attempted=True,
        outcome="succeeded",
        kind=operation.kind.value,
        repo_identity=operation.repo_identity,
        issue_number=issue_number,
        return_code=result.returncode,
        stdout=result.stdout,
        stderr=result.stderr,
    )


async def _run_issue_close(
    project_root: Path,
    operation: ForgeOperationRequest,
    settings: AgentSettings,
    send_log: LogSender,
) -> ForgeOutcome:
    issue_number = operation.issue_number
    assert issue_number is not None  # guaranteed by `_revalidate_locally`

    args = ["issue", "close", str(issue_number), "--repo", operation.repo_identity]
    await send_log("stderr", f"forge.gh_argv:{' '.join(args)}")
    result = await run_gh(
        project_root,
        *args,
        gh_bin=settings.forge_gh_bin,
        credential_relative_path=settings.forge_credential_relative_path,
        timeout_seconds=settings.forge_operation_timeout_seconds,
    )

    if result.refused_reason is not None:
        return _refused(result.refused_reason, kind=operation.kind, repo_identity=operation.repo_identity)
    if not result.ok:
        return _refused(
            "gh_command_failed",
            kind=operation.kind,
            repo_identity=operation.repo_identity,
            issue_number=issue_number,
            return_code=result.returncode,
            stdout=result.stdout,
            stderr=result.stderr,
        )
    return ForgeOutcome(
        attempted=True,
        outcome="succeeded",
        kind=operation.kind.value,
        repo_identity=operation.repo_identity,
        issue_number=issue_number,
        return_code=result.returncode,
        stdout=result.stdout,
        stderr=result.stderr,
    )


async def _run_issue_list(
    project_root: Path,
    operation: ForgeOperationRequest,
    settings: AgentSettings,
    send_log: LogSender,
) -> ForgeOutcome:
    state = operation.state or _DEFAULT_ISSUE_STATE
    args = [
        "issue",
        "list",
        "--repo",
        operation.repo_identity,
        "--state",
        state,
        "--json",
        _ISSUE_LIST_JSON_FIELDS,
        "--limit",
        str(_ISSUE_LIST_DEFAULT_LIMIT),
    ]
    await send_log("stderr", f"forge.gh_argv:{' '.join(args)}")
    result = await run_gh(
        project_root,
        *args,
        gh_bin=settings.forge_gh_bin,
        credential_relative_path=settings.forge_credential_relative_path,
        timeout_seconds=settings.forge_operation_timeout_seconds,
    )

    if result.refused_reason is not None:
        return _refused(result.refused_reason, kind=operation.kind, repo_identity=operation.repo_identity)
    if not result.ok:
        return _refused(
            "gh_command_failed",
            kind=operation.kind,
            repo_identity=operation.repo_identity,
            return_code=result.returncode,
            stdout=result.stdout,
            stderr=result.stderr,
        )
    try:
        issues = json.loads(result.stdout)
        if not isinstance(issues, list):
            raise ValueError("gh issue list --json did not return a JSON array")
    except (json.JSONDecodeError, ValueError):
        return _refused(
            "forge_postcondition_failed:not_json_array",
            kind=operation.kind,
            repo_identity=operation.repo_identity,
            return_code=result.returncode,
            stdout=result.stdout,
            stderr=result.stderr,
        )
    return ForgeOutcome(
        attempted=True,
        outcome="succeeded",
        kind=operation.kind.value,
        repo_identity=operation.repo_identity,
        issues=issues,
        return_code=result.returncode,
        stdout=result.stdout,
        stderr=result.stderr,
    )
