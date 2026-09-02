"""Pure markdown renderer for epic materialization -- issue #78, Commit 2a.

`render_epic_markdown` turns an `EpicModel` and its `IssueModel`s into the
exact bytes `publish_epic_to_repo` (`gateway/app/mcp/server.py`) hands the
executor to write. It does no I/O, calls no LLM, and is fully deterministic:
the same epic/issues in produce the same dict of relative-path -> content
out, byte for byte -- see `tests/unit/test_issue_render.py`, which asserts
exact strings rather than "looks about right". That determinism is the whole
point (see `.docs/agents/issue-automation.md`'s own template, reproduced
below): a human approved specific content in ChatGPT, and what lands in git
must be that content, not a paraphrase an LLM produced on a second pass.

Canonical layout (`.docs/issues/README.md`, `docs/issues/063-.../` in this
repo for a worked example)::

    docs/issues/NNN-<epic-slug>-[<status>]/README.md
    docs/issues/NNN-<epic-slug>-[<status>]/epic.md
    docs/issues/NNN-<epic-slug>-[<status>]/issues/NNN-<task-slug>-[<status>].md

Every `NNN` above is chosen by the EXECUTOR
(`agent/codex_bridge_agent/issue_materialize.py`), never here: this module
has no filesystem to scan, and the gateway never learns a project's real path
(`docs/architecture.md`) -- the same boundary `resolve_issue_text` already
respects on the read side. So the paths this function returns are relative
to the epic's own directory and carry NO `NNN` prefix anywhere:

    "README.md"
    "epic.md"
    "issues/<issue_id>/<task-slug>-[<status>].md"

The per-issue key's `<issue_id>/` segment is a correlation token, not a real
directory -- `MaterializeRequest.files` (`shared/protocol.py`) is a bare
`dict[str, str]`, so there is nowhere else to carry "which `IssueModel` does
this file belong to" through the round trip to
`AgentMessageType.ISSUE_MATERIALIZE_RESULT`, which may arrive long after
this gateway process forgot the request (a restart in between is fine).
`agent/codex_bridge_agent/issue_materialize.py` strips that segment before
choosing the real, numbered filename; `store.apply_epic_materialization`
parses the same id back out of the RESULT's echoed keys.

Status vocabulary mapping (`gateway/app/services/issue_types.py`'s
`EPIC_STATUSES`/`ISSUE_STATUSES` are NOT the same set as the file-status
suffixes `.docs/agents/issue-automation.md` allows -- `[draft] [ready]
[started] [blocked] [review] [finished] [cancelled]` -- so the mapping below
is explicit rather than assumed):

    epic status       -> file suffix       issue status   -> file suffix
    ----------------------------------     --------------------------------
    open               -> ready             open           -> ready
    in_progress         -> started          in_progress    -> started
    done                -> finished         blocked        -> blocked
    cancelled           -> cancelled        in_review      -> review
                                             done           -> finished
                                             cancelled      -> cancelled

`draft` is deliberately unreachable from either vocabulary: nothing in this
gateway's database means "not yet approved for a repo" (an epic/issue this
gateway holds is, by definition, already a real planning row) -- `draft` is
reserved for a status a human assigns by renaming the file after
materialization, per `.docs/issues/README.md`'s "status changes must be
performed by rename." An epic/issue status this module has never seen (a
future value added to the vocabulary without updating this mapping) falls
back to `draft` rather than raising, so a schema-level status addition fails
loud in review (a new value renders as `[draft]` for every epic, which looks
wrong immediately) instead of blowing up publication for every existing
epic.
"""

from __future__ import annotations

import json
import re

from gateway.app.models.entities import EpicModel, IssueModel


EPIC_STATUS_SUFFIX: dict[str, str] = {
    "open": "ready",
    "in_progress": "started",
    "done": "finished",
    "cancelled": "cancelled",
}

ISSUE_STATUS_SUFFIX: dict[str, str] = {
    "open": "ready",
    "in_progress": "started",
    "blocked": "blocked",
    "in_review": "review",
    "done": "finished",
    "cancelled": "cancelled",
}

_DEFAULT_SUFFIX = "draft"

_SLUG_STRIP = re.compile(r"[^a-z0-9]+")


def _slugify(text: str) -> str:
    slug = _SLUG_STRIP.sub("-", text.strip().lower()).strip("-")
    return slug or "untitled"


def epic_directory_slug(epic: EpicModel) -> str:
    """The `<epic-slug>-[<status>]` component of the epic's directory name.

    No `NNN-` prefix -- the executor chooses that (see the module docstring).
    `publish_epic_to_repo` (`gateway/app/mcp/server.py`) passes this straight
    through as `MaterializeRequest.slug`, so this is the ONE place that
    string is built; nothing recomputes it independently.
    """
    suffix = EPIC_STATUS_SUFFIX.get(epic.status, _DEFAULT_SUFFIX)
    return f"{_slugify(epic.title)}-[{suffix}]"


def issue_relative_key(issue: IssueModel) -> str:
    """The `issues/<issue_id>/<task-slug>-[<status>].md` key for one issue.

    Shared by `render_epic_markdown` (building `files`) so the key a caller
    sees in the returned dict is always exactly this shape -- there is no
    second place that assembles it.
    """
    suffix = ISSUE_STATUS_SUFFIX.get(issue.status, _DEFAULT_SUFFIX)
    return f"issues/{issue.id}/{_slugify(issue.title)}-[{suffix}].md"


def _render_readme(epic: EpicModel, ordered_issues: list[IssueModel]) -> str:
    lines = [f"# Epic — {epic.title}", ""]
    if epic.description:
        lines += [epic.description, ""]
    lines += ["## Issues", "", "| Title | Status | Priority |", "| --- | --- | --- |"]
    for issue in ordered_issues:
        lines.append(f"| {issue.title} | {issue.status} | {issue.priority} |")
    lines.append("")
    return "\n".join(lines)


def _render_epic_body(epic: EpicModel) -> str:
    suffix = EPIC_STATUS_SUFFIX.get(epic.status, _DEFAULT_SUFFIX)
    lines = [
        f"# {epic.title}",
        "",
        f"Status: `{epic.status}` (materialized as `[{suffix}]`)",
    ]
    if epic.description:
        lines += ["", epic.description]
    lines.append("")
    return "\n".join(lines)


def _render_issue_body(issue: IssueModel) -> str:
    suffix = ISSUE_STATUS_SUFFIX.get(issue.status, _DEFAULT_SUFFIX)
    lines = [
        f"# {issue.title}",
        "",
        f"Status: `{issue.status}` (materialized as `[{suffix}]`) · Priority: `{issue.priority}`",
    ]
    if issue.description:
        lines += ["", issue.description]
    labels = json.loads(issue.labels_json or "[]")
    if labels:
        lines += ["", "## Labels", ""]
        lines += [f"- {label}" for label in labels]
    dependencies = json.loads(issue.dependencies_json or "[]")
    if dependencies:
        lines += ["", "## Dependencies", ""]
        lines += [f"- {dep}" for dep in dependencies]
    if issue.blocked_reason:
        lines += ["", "## Blocked reason", "", issue.blocked_reason]
    lines.append("")
    return "\n".join(lines)


def render_epic_markdown(epic: EpicModel, issues: list[IssueModel]) -> dict[str, str]:
    """Relative path -> content, for every file one epic materializes to.

    Pure: no I/O, no LLM, deterministic given `epic`/`issues`. `issues` is
    sorted by `(created_at, id)` here so the README table and the set of
    `issues/...` keys are stable across two calls with the same input in a
    different order (a caller that re-fetched from the database with no
    explicit `ORDER BY` must not see the output shuffle).
    """
    ordered_issues = sorted(issues, key=lambda issue: (issue.created_at, issue.id))
    files: dict[str, str] = {
        "README.md": _render_readme(epic, ordered_issues),
        "epic.md": _render_epic_body(epic),
    }
    for issue in ordered_issues:
        files[issue_relative_key(issue)] = _render_issue_body(issue)
    return files
