"""The commit/push step a completed task's own `delivery` block authorizes.

WK-20260830-chatgpt-entry-provider-and-delivery, slice of issue #51
("delivery contract"). Runs on the executor, OUTSIDE the provider's own
sandbox (`agent/codex_bridge_agent/runners/`) -- push needs network, which
`workspace-write` does not grant, and a commit/push made by the AGENT itself
(inside `codex exec`/`claude -p`) would be an uncontrolled side effect no
approval gate ever saw. This module is the only place in this codebase that
writes a commit or pushes a branch, and it does so only when:

  1. `AgentSettings.allow_git_delivery` is `True` on THIS executor (the
     machine-level kill switch, off by default -- see `config.py`);
  2. the dispatched task's own `delivery.branch` matches
     `shared.protocol.PUSHABLE_BRANCH_PATTERN` -- checked again here even
     though the gateway (`shared.policy.push_is_preauthorized`) already
     checked it, because a compromised or buggy gateway must not be able to
     grant `main` by lying about what it already verified.

Nothing here ever emits `--force`, `--force-with-lease`, or a `+refs`
refspec. Nothing here ever runs `git add -A`, `git add .`, or `git commit -a`
-- every stage is by explicit path, taken from `git status`'s own output
(shared working-tree gate, `.docs/workflows/git-delivery.md`).

Issue #66 ARO finding F34 ("a cancelled task that still has a running git
delivery step in flight is a real interaction this issue does not resolve
... the git step should check for cancellation before committing"): this is
that check. `deliver_changes` accepts an `is_cancelled` callable and reads it
exactly once, immediately before the `git commit` call, at the same point --
and for the same reason -- `head_before`/`head_now` are re-read: the last
safe moment to still refuse before an irreversible local write.

The three outcomes a cancel arriving during delivery could produce are
deliberately NOT symmetric, chosen against the shape cancel already has
everywhere else in this codebase (`STOPPABLE_TASK_STATES`, `RunnerPool.
cancel`, the reconnect-replay path issue #17 added):

  - **Before the commit checkpoint** (still validating, staging, or
    switching branches): refused outright, exactly like `head_moved` --
    `outcome="refused", reason="cancelled_before_commit"`, nothing
    committed, the staged tree left exactly as `git add` left it,
    inspectable rather than unstaged or "fixed".
  - **After the commit checkpoint has already passed** (the commit itself,
    and any push that follows it): runs to completion UNINTERRUPTED. Once
    this module has decided to make the commit, cancelling becomes
    strictly worse than finishing: a killed `git commit` risks nothing
    (git's own commit is atomic), but a killed `git push` is a subprocess
    torn down mid-transfer with no defined recovery -- this module already
    refuses to `--force` or rewrite a ref under any circumstance, so there
    is no corrective action it could take afterward, only an ambiguous
    local/remote state and a branch an operator cannot trust. Letting an
    in-flight push finish and reporting exactly what happened
    (`committed_and_pushed` / `committed_only` with `pushed=False` and a
    `reason` naming why) is the one behaviour that keeps every claim this
    module makes -- verified post-condition, no forced ref, no half state
    -- true regardless of when the cancel arrived.
  - A cancel is therefore never allowed to interrupt a `git push` already
    running. That is a deliberate rejection of "attempt to interrupt
    mid-push": this module has no way to safely reason about a subprocess
    killed after it may have already started transferring objects, and
    every other guard here exists specifically to avoid leaving git state
    that cannot be trusted at a glance.

The caller (`AgentService._handle_dispatch`) does not gate the call to
`deliver_changes` on cancellation itself -- per `design-standards.md` §3,
the guard lives in the one place that is actually dangerous (the commit),
not at the caller, so a future second call site cannot forget it.

WK-20260903-gh66-push-verify, issue #66's own Definition-of-Done live smoke
test (2026-09-03, first run against a real GitHub remote): the post-push
verification below queries the REMOTE (`git ls-remote`), not a local
remote-tracking ref (`git rev-parse <remote>/<branch>`, what it did before).
A single-branch clone (`git clone --branch <b> --depth N`) narrows
`remote.<remote>.fetch` to just `<b>`, so `rev-parse` on any OTHER pushed
branch fails for want of a local ref this module never asked git to
create -- even though the push reached the remote intact. That live run
reported a real, verified GitHub push as `pushed=False,
reason="push_verification_failed"`. See the comment at the verification
call site for the fix and the new `push_verification_unreachable` reason
this introduces alongside it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Awaitable, Callable

from agent.codex_bridge_agent.config import AgentSettings
from agent.codex_bridge_agent.git_tools import run_git
from shared.protocol import DeliveryRequest, PUSHABLE_BRANCH_PATTERN


LogSender = Callable[[str, str], Awaitable[None]]

# A conservative git remote-name shape: must start with a letter, so it can
# never be parsed as a flag (`git push --set-upstream <remote> <branch>`
# would otherwise let a value like "--force" inject a flag into git's own
# argv, since this module builds argv lists rather than a shell string --
# `PUSHABLE_BRANCH_PATTERN` already rules this out for `branch` the same way,
# by never allowing a leading `-`). `DeliveryRequest.remote` has no such
# constraint of its own (it defaults to "origin" but is not otherwise
# validated), so this module is where that gap is closed.
_REMOTE_NAME_PATTERN = re.compile(r"^[a-zA-Z][a-zA-Z0-9._-]{0,63}$")

_PROTECTED_BRANCHES = frozenset({"main", "master", "HEAD"})

# A change this large is not what a conversational "resolve this issue"
# request authorized -- refuse rather than stage it blindly.
MAX_STAGED_PATHS = 200


def _is_forbidden_path(path: str) -> str | None:
    """Names the reason a path must never be staged, or `None` if it's fine.

    `AGENTS.md` §7: "Do not commit caches, local runtime data, backups,
    credentials, .env*, or token files." This is that rule, enforced in code
    rather than only in an instruction the agent might not follow.
    """
    p = Path(path)
    name = p.name
    parts = p.parts
    if name == ".env" or name.startswith(".env."):
        return "env_file"
    if ".credentials" in parts:
        return "credentials_dir"
    if name.endswith(".pem") or name.endswith(".key"):
        return "key_file"
    if name.startswith("id_rsa"):
        return "ssh_key"
    if "node_modules" in parts:
        return "node_modules"
    if name == "codex_bridge.db":
        return "dev_database"
    if ".git" in parts:
        return "git_internal"
    return None


def _parse_porcelain_z(output: str) -> list[str]:
    """Parses `git status --porcelain=v1 -z --untracked-files=all` output.

    NUL-separated records: `XY PATH\\0` for an ordinary change, or
    `XY PATH\\0ORIG_PATH\\0` for a rename/copy (status code contains `R`/`C`)
    -- the extra field must be consumed too, or the next record is
    misread as a path.
    """
    fields = output.split("\x00")
    paths: list[str] = []
    i = 0
    while i < len(fields):
        entry = fields[i]
        i += 1
        if not entry or len(entry) < 4:
            continue
        status = entry[:2]
        path = entry[3:]
        paths.append(path)
        if "R" in status or "C" in status:
            i += 1  # consume the ORIG_PATH field this record also carries
    return paths


_SHORTSTAT_FILES = re.compile(r"(\d+) files? changed")
_SHORTSTAT_INSERTIONS = re.compile(r"(\d+) insertions?\(\+\)")
_SHORTSTAT_DELETIONS = re.compile(r"(\d+) deletions?\(-\)")


def _parse_shortstat(text: str) -> tuple[int, int, int]:
    files_match = _SHORTSTAT_FILES.search(text)
    insertions_match = _SHORTSTAT_INSERTIONS.search(text)
    deletions_match = _SHORTSTAT_DELETIONS.search(text)
    return (
        int(files_match.group(1)) if files_match else 0,
        int(insertions_match.group(1)) if insertions_match else 0,
        int(deletions_match.group(1)) if deletions_match else 0,
    )


@dataclass(frozen=True)
class DeliveryOutcome:
    attempted: bool
    outcome: str  # "committed_and_pushed" | "committed_only" | "skipped" | "refused"
    reason: str | None = None
    branch: str | None = None
    base_branch: str | None = None
    created_branch: bool = False
    head_before: str | None = None
    commit: str | None = None
    remote: str | None = None
    remote_sha: str | None = None
    pushed: bool = False
    staged_paths: list[str] = field(default_factory=list)
    files_changed: int = 0
    insertions: int = 0
    deletions: int = 0
    commit_subject: str | None = None

    def to_dict(self) -> dict:
        return {
            "attempted": self.attempted,
            "outcome": self.outcome,
            "reason": self.reason,
            "branch": self.branch,
            "base_branch": self.base_branch,
            "created_branch": self.created_branch,
            "head_before": self.head_before,
            "commit": self.commit,
            "remote": self.remote,
            "remote_sha": self.remote_sha,
            "pushed": self.pushed,
            "staged_paths": self.staged_paths,
            "files_changed": self.files_changed,
            "insertions": self.insertions,
            "deletions": self.deletions,
            "commit_subject": self.commit_subject,
        }


def _refused(reason: str, delivery: DeliveryRequest, **extra: object) -> DeliveryOutcome:
    fields: dict[str, object] = {
        "branch": delivery.branch,
        "base_branch": delivery.base_branch,
        "remote": delivery.remote,
    }
    fields.update(extra)  # a caller-supplied value (e.g. a branch already resolved) wins
    return DeliveryOutcome(attempted=True, outcome="refused", reason=reason, **fields)  # type: ignore[arg-type]


async def deliver_changes(
    *,
    project_root: Path,
    delivery: DeliveryRequest,
    settings: AgentSettings,
    task_id: str,
    issue_ref: str | None,
    engine: str,
    send_log: LogSender,
    is_cancelled: Callable[[], bool] | None = None,
) -> DeliveryOutcome:
    """Commits (and, if authorized, pushes) whatever a completed task changed.

    Only called by `AgentService._handle_dispatch` after the provider runner
    exits successfully (`final_state == COMPLETED`) -- never on a failed or
    cancelled run, and never from inside the provider's own sandbox.

    `is_cancelled` is optional and defaults to "never cancelled" -- every
    existing caller (this module's own materialize call site, every test in
    `tests/unit/test_git_delivery.py`) keeps working unchanged without
    passing it. When given, it is polled exactly once, immediately before
    the commit -- see this module's own docstring, "Issue #66 ARO finding
    F34", for why that single checkpoint and not any other.
    """
    check_cancelled = is_cancelled or (lambda: False)
    branch = delivery.branch

    if branch in _PROTECTED_BRANCHES:
        return _refused("protected_branch", delivery)
    if not PUSHABLE_BRANCH_PATTERN.match(branch):
        # Defense in depth: `shared.policy.push_is_preauthorized` already
        # checked this at submission. A compromised or buggy gateway must not
        # be able to grant `main` by lying about what it already verified.
        return _refused("branch_not_allowed", delivery)
    if not settings.allow_git_delivery:
        return _refused("executor_delivery_disabled", delivery)
    if delivery.allow_push and not _REMOTE_NAME_PATTERN.match(delivery.remote):
        return _refused("invalid_remote", delivery)

    code, toplevel_out, _ = await run_git(project_root, "rev-parse", "--show-toplevel")
    if code != 0 or Path(toplevel_out.strip() or "/dev/null").resolve() != project_root.resolve():
        return _refused("not_repo_root", delivery)

    code, remotes_out, _ = await run_git(project_root, "remote")
    configured_remotes = set(remotes_out.split())
    if delivery.allow_push and delivery.remote not in configured_remotes:
        return _refused("no_remote", delivery)

    code, status_out, _ = await run_git(project_root, "status", "--porcelain=v1", "-z", "--untracked-files=all")
    if code != 0:
        return _refused("status_failed", delivery)
    staged_paths = _parse_porcelain_z(status_out)
    if not staged_paths:
        return DeliveryOutcome(
            attempted=True, outcome="skipped", reason="no_changes",
            branch=branch, base_branch=delivery.base_branch, remote=delivery.remote,
        )
    if len(staged_paths) > MAX_STAGED_PATHS:
        return _refused("too_many_paths", delivery, staged_paths=staged_paths[:MAX_STAGED_PATHS])
    for path in staged_paths:
        forbidden_reason = _is_forbidden_path(path)
        if forbidden_reason is not None:
            return _refused(f"forbidden_path:{forbidden_reason}:{path}", delivery)

    code, _, _ = await run_git(project_root, "rev-parse", "--verify", "--quiet", f"refs/heads/{branch}")
    branch_exists = code == 0
    created_branch = not branch_exists
    if branch_exists:
        code, _, err = await run_git(project_root, "switch", branch)
    else:
        code, _, err = await run_git(project_root, "switch", "-c", branch, delivery.base_branch)
    if code != 0:
        return _refused("checkout_conflict", delivery, staged_paths=staged_paths)
    await send_log(
        "stderr",
        f"task.branch_created:{branch}" if created_branch else f"task.branch_switched:{branch}",
    )

    code, head_out, _ = await run_git(project_root, "rev-parse", "HEAD")
    head_before = head_out.strip() if code == 0 else None

    code, _, err = await run_git(project_root, "add", "--", *staged_paths)
    if code != 0:
        return _refused("stage_failed", delivery, branch=branch, created_branch=created_branch, head_before=head_before, staged_paths=staged_paths)

    # Re-read HEAD immediately before committing (shared working-tree gate):
    # another process may have written to this branch between the switch
    # above and this instant. Nothing is unstaged on a mismatch -- the tree
    # is left exactly as it is, inspectable, rather than "fixed" by force.
    code, head_now_out, _ = await run_git(project_root, "rev-parse", "HEAD")
    head_now = head_now_out.strip() if code == 0 else None
    if head_now != head_before:
        return _refused(
            f"head_moved:{head_before}->{head_now}", delivery,
            branch=branch, created_branch=created_branch, head_before=head_before, staged_paths=staged_paths,
        )

    # Issue #66 ARO finding F34 -- the check this module's own docstring
    # names ("check for cancellation before committing"), placed at the
    # last possible moment before the commit itself, the same way
    # `head_moved` just above is re-read immediately before use rather than
    # trusted from earlier in this function. Nothing is unstaged on a
    # cancel: the tree is left exactly as `git add` left it, inspectable,
    # not "cleaned up" by force. Once this check has passed, delivery is
    # allowed to run the commit and any push through to completion
    # uninterrupted -- see the module docstring for why interrupting a
    # push in flight is rejected outright.
    if check_cancelled():
        await send_log("stderr", f"task.delivery_cancelled:{task_id}")
        return _refused(
            "cancelled_before_commit", delivery,
            branch=branch, created_branch=created_branch, head_before=head_before, staged_paths=staged_paths,
        )

    subject = (delivery.commit_subject or f"Deliver task {task_id}")[:200]
    body_lines = [f"Task-Id: {task_id}"]
    if issue_ref:
        body_lines.append(f"Issue: {issue_ref}")
    body_lines.append(f"Engine: {engine}")
    body_lines.append(f"Executor: {settings.executor_id}")
    body = "\n".join(body_lines)

    code, _, err = await run_git(
        project_root,
        "-c", f"user.name={settings.git_author_name}",
        "-c", f"user.email={settings.git_author_email}",
        "commit", "-m", subject, "-m", body,
    )
    if code != 0:
        return _refused(
            "commit_failed", delivery,
            branch=branch, created_branch=created_branch, head_before=head_before, staged_paths=staged_paths,
        )

    code, commit_out, _ = await run_git(project_root, "rev-parse", "HEAD")
    commit_sha = commit_out.strip() if code == 0 else None
    _, shortstat_out, _ = await run_git(project_root, "diff", "--shortstat", "HEAD~1..HEAD")
    files_changed, insertions, deletions = _parse_shortstat(shortstat_out)

    common_fields = dict(
        attempted=True,
        branch=branch,
        base_branch=delivery.base_branch,
        created_branch=created_branch,
        head_before=head_before,
        commit=commit_sha,
        remote=delivery.remote,
        staged_paths=staged_paths,
        files_changed=files_changed,
        insertions=insertions,
        deletions=deletions,
        commit_subject=subject,
    )

    if not delivery.allow_push:
        return DeliveryOutcome(outcome="committed_only", pushed=False, **common_fields)

    code, _, err = await run_git(
        project_root, "push", "--set-upstream", delivery.remote, branch,
        timeout_seconds=settings.git_push_timeout_seconds,
    )
    if code != 0:
        return DeliveryOutcome(outcome="committed_only", pushed=False, reason="push_failed_or_non_fast_forward", **common_fields)

    # Verify the post-condition -- a command that returns 0 is not proof.
    #
    # Issue #66, observed 2026-09-03 in the live smoke test against a real
    # GitHub remote: `git rev-parse <remote>/<branch>` (what this used to do)
    # reads a LOCAL remote-tracking ref, and that ref only exists for
    # branches covered by this clone's own `remote.<remote>.fetch` refspec.
    # A single-branch clone (`git clone --branch development --depth N`,
    # where `--depth` implies `--single-branch` unless overridden) narrows
    # that refspec to just `development` -- so pushing any OTHER branch
    # reaches the remote intact (`git ls-remote` against the same remote
    # showed the exact commit just made) while `rev-parse` fails with
    # "unknown revision" for want of a local ref that nothing here ever
    # asked git to create. The result was a real, live push reported as
    # `pushed=False, reason="push_verification_failed"` -- correctness
    # matters here specifically because `GET /api/v1/missions/{id}/delivery`
    # and the task result are what an operator reads to decide whether a
    # branch exists, not the local clone's own bookkeeping.
    #
    # `ls-remote` asks the remote directly, which has no such dependency,
    # and is the only local check this module needs: a `rev-parse` first
    # pass would only pretend to be cheap -- it fails by construction on
    # every single-branch clone pushing anything but its cloned branch, so
    # every such push would pay for both calls anyway. One authoritative
    # check, not two commands to keep in sync.
    code, ls_remote_out, _ = await run_git(
        project_root, "ls-remote", delivery.remote, f"refs/heads/{branch}",
        timeout_seconds=settings.git_push_verify_timeout_seconds,
    )
    if code != 0:
        # The remote itself could not be queried (network dropped right
        # after a push that already reported success, a transient DNS/TLS
        # failure, the verify timeout above firing...). This is deliberately
        # NOT the same `reason` as a query that succeeds and disagrees --
        # one means "we know the push did not land as expected," the other
        # means "we no longer know anything," and telling an operator
        # "not pushed" for the second case would be its own false claim.
        # `remote_sha` stays None: nothing was learned about the remote.
        return DeliveryOutcome(
            outcome="committed_only", pushed=False, reason="push_verification_unreachable", **common_fields
        )
    remote_sha = ls_remote_out.split()[0] if ls_remote_out.strip() else None
    if remote_sha != commit_sha:
        return DeliveryOutcome(outcome="committed_only", pushed=False, reason="push_verification_failed", remote_sha=remote_sha, **common_fields)

    return DeliveryOutcome(outcome="committed_and_pushed", pushed=True, remote_sha=remote_sha, **common_fields)
