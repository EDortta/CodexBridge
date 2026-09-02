"""`render_epic_markdown` -- issue #78, Commit 2a.

Exact-bytes assertions, not "looks about right": the whole point of this
function being pure (no I/O, no LLM) is that its output is reproducible and
checkable, the thing `.docs/napkin-lessons.md`'s "five green tests proved
only that the code was unreachable" lesson warns a shallower test would miss.
Each negative/behavioural assertion below sits next to a positive control in
the same test, per that same lesson.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest

from gateway.app.models.entities import EpicModel, IssueModel
from gateway.app.services.issue_render import (
    epic_directory_slug,
    issue_relative_key,
    render_epic_markdown,
)


def _epic(**overrides) -> EpicModel:
    fields = dict(
        id="epic-1",
        project_id="p1",
        title="Issue materialize bridge",
        description="Bridges planned epics into versioned files.",
        status="open",
        created_by_user_id="alice",
        created_by_email="alice@example.com",
        created_at=datetime(2026, 9, 2, tzinfo=timezone.utc),
        updated_at=datetime(2026, 9, 2, tzinfo=timezone.utc),
        revision=3,
    )
    fields.update(overrides)
    return EpicModel(**fields)


def _issue(**overrides) -> IssueModel:
    fields = dict(
        id="issue-1",
        project_id="p1",
        epic_id="epic-1",
        title="Render pure markdown",
        description="No I/O, no LLM.",
        status="open",
        priority="high",
        labels_json=json.dumps(["backend"]),
        dependencies_json=json.dumps([]),
        blocked_reason=None,
        created_by_user_id="alice",
        created_by_email="alice@example.com",
        created_at=datetime(2026, 9, 2, tzinfo=timezone.utc),
        updated_at=datetime(2026, 9, 2, tzinfo=timezone.utc),
        revision=1,
    )
    fields.update(overrides)
    return IssueModel(**fields)


def test_epic_directory_slug_bakes_title_and_status_suffix_together():
    assert epic_directory_slug(_epic()) == "issue-materialize-bridge-[ready]"
    assert epic_directory_slug(_epic(status="in_progress")) == "issue-materialize-bridge-[started]"
    assert epic_directory_slug(_epic(status="done")) == "issue-materialize-bridge-[finished]"
    assert epic_directory_slug(_epic(status="cancelled")) == "issue-materialize-bridge-[cancelled]"
    # Positive control alongside the fallback below: a KNOWN status is never
    # routed through the draft fallback.
    assert "draft" not in epic_directory_slug(_epic(status="open"))
    # Negative control: a status this mapping has never seen (schema drift,
    # or a future value) falls back to `draft` rather than raising or
    # silently mislabeling.
    assert epic_directory_slug(_epic(status="totally_unknown")) == "issue-materialize-bridge-[draft]"


def test_issue_relative_key_embeds_the_issue_id_as_a_correlation_segment():
    issue = _issue(id="abc-123", title="Render pure markdown", status="in_review")
    key = issue_relative_key(issue)
    assert key == "issues/abc-123/render-pure-markdown-[review].md"
    # Positive control: a different id changes only the correlation segment.
    other = issue_relative_key(_issue(id="xyz-789", title="Render pure markdown", status="in_review"))
    assert other == "issues/xyz-789/render-pure-markdown-[review].md"
    assert other != key


def test_render_epic_markdown_exact_bytes_for_epic_and_two_issues():
    epic = _epic()
    issue_a = _issue(
        id="issue-a", title="First slice", status="open", priority="high",
        description="Do the first thing.",
        created_at=datetime(2026, 9, 1, tzinfo=timezone.utc),
    )
    issue_b = _issue(
        id="issue-b", title="Second slice", status="blocked", priority="low",
        description=None, labels_json=json.dumps([]),
        dependencies_json=json.dumps(["issue-a"]),
        blocked_reason="Waiting on first slice.",
        created_at=datetime(2026, 9, 2, tzinfo=timezone.utc),
    )

    files = render_epic_markdown(epic, [issue_b, issue_a])  # deliberately out of order

    assert set(files) == {
        "README.md",
        "epic.md",
        "issues/issue-a/first-slice-[ready].md",
        "issues/issue-b/second-slice-[blocked].md",
    }

    assert files["README.md"] == (
        "# Epic — Issue materialize bridge\n"
        "\n"
        "Bridges planned epics into versioned files.\n"
        "\n"
        "## Issues\n"
        "\n"
        "| Title | Status | Priority |\n"
        "| --- | --- | --- |\n"
        "| First slice | open | high |\n"
        "| Second slice | blocked | low |\n"
    )

    assert files["epic.md"] == (
        "# Issue materialize bridge\n"
        "\n"
        "Status: `open` (materialized as `[ready]`)\n"
        "\n"
        "Bridges planned epics into versioned files.\n"
    )

    assert files["issues/issue-a/first-slice-[ready].md"] == (
        "# First slice\n"
        "\n"
        "Status: `open` (materialized as `[ready]`) · Priority: `high`\n"
        "\n"
        "Do the first thing.\n"
        "\n"
        "## Labels\n"
        "\n"
        "- backend\n"
    )

    assert files["issues/issue-b/second-slice-[blocked].md"] == (
        "# Second slice\n"
        "\n"
        "Status: `blocked` (materialized as `[blocked]`) · Priority: `low`\n"
        "\n"
        "## Dependencies\n"
        "\n"
        "- issue-a\n"
        "\n"
        "## Blocked reason\n"
        "\n"
        "Waiting on first slice.\n"
    )


def test_render_epic_markdown_with_no_issues_and_no_description():
    epic = _epic(description=None)
    files = render_epic_markdown(epic, [])
    assert set(files) == {"README.md", "epic.md"}
    assert files["README.md"] == (
        "# Epic — Issue materialize bridge\n"
        "\n"
        "## Issues\n"
        "\n"
        "| Title | Status | Priority |\n"
        "| --- | --- | --- |\n"
    )
    assert files["epic.md"] == (
        "# Issue materialize bridge\n"
        "\n"
        "Status: `open` (materialized as `[ready]`)\n"
    )


def test_render_epic_markdown_is_deterministic_regardless_of_input_order():
    epic = _epic()
    issue_a = _issue(id="issue-a", title="A", created_at=datetime(2026, 9, 1, tzinfo=timezone.utc))
    issue_b = _issue(id="issue-b", title="B", created_at=datetime(2026, 9, 2, tzinfo=timezone.utc))

    forward = render_epic_markdown(epic, [issue_a, issue_b])
    backward = render_epic_markdown(epic, [issue_b, issue_a])
    assert forward == backward
