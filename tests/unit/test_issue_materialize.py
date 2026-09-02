"""`materialize_epic` and the shared numbering scanner -- issue #78, Commit 2c.

Against real throwaway directory trees under pytest's `tmp_path`, same
posture as `tests/unit/test_instructions.py`: this module does real
filesystem globbing and atomic file creation, so a fake filesystem would test
the wrong thing.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from agent.codex_bridge_agent.instructions import list_used_issue_numbers
from agent.codex_bridge_agent.issue_materialize import (
    MaterializeError,
    _allocate_dir,
    _allocate_file,
    materialize_epic,
)
from shared.protocol import MaterializeRequest


def _write(path: Path, text: str = "x") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _request(**overrides) -> MaterializeRequest:
    fields = dict(
        epic_id="epic-1",
        project_id="p1",
        slug="issue-materialize-bridge-[ready]",
        files={
            "README.md": "readme body",
            "epic.md": "epic body",
            "issues/issue-a/first-slice-[ready].md": "issue a body",
            "issues/issue-b/second-slice-[blocked].md": "issue b body",
        },
        existing_path=None,
        epic_revision=3,
        issue_revisions={"issue-a": 1, "issue-b": 2},
        delivery=None,
    )
    fields.update(overrides)
    return MaterializeRequest(**fields)


# --------------------------------------------------------------------------
# `list_used_issue_numbers` -- the three layouts `resolve_issue_text` tolerates.
# --------------------------------------------------------------------------


def test_list_used_issue_numbers_covers_all_three_layouts(tmp_path: Path):
    # Layout A: nested under some epic's own issues/.
    _write(tmp_path / "docs/issues/063-chatgpt-entry/issues/065-start-task.md")
    # Layout B: a whole numbered folder.
    _write(tmp_path / "docs/issues/001-mobile-api-foundation/README.md")
    # Layout C: a bare numbered file.
    _write(tmp_path / "docs/issues/042-standalone-issue.md")
    # A status-suffixed name (brackets) must not break the scan.
    _write(tmp_path / "docs/issues/078-bridge-[draft]/README.md")

    # 65 is used too -- it is the nested issue file from Layout A itself,
    # a real number in the shared pool, not a fixture artifact.
    assert list_used_issue_numbers(tmp_path) == {63, 65, 1, 42, 78}

    # Positive control: an unrelated, non-numbered entry contributes nothing.
    _write(tmp_path / "docs/issues/templates/README.md")
    assert list_used_issue_numbers(tmp_path) == {63, 65, 1, 42, 78}


def test_list_used_issue_numbers_empty_when_docs_issues_missing(tmp_path: Path):
    assert list_used_issue_numbers(tmp_path) == set()


# --------------------------------------------------------------------------
# Fresh publish: numbering, atomic creation, race resolution.
# --------------------------------------------------------------------------


def test_materialize_epic_allocates_the_next_free_number(tmp_path: Path):
    _write(tmp_path / "docs/issues/077-something-else/README.md")

    outcome = materialize_epic(tmp_path, _request())

    assert outcome.epic_path == "docs/issues/078-issue-materialize-bridge-[ready]"
    assert (tmp_path / outcome.epic_path / "README.md").read_text() == "readme body"
    assert (tmp_path / outcome.epic_path / "epic.md").read_text() == "epic body"

    # Both issue files landed under issues/, each with its own allocated
    # number, continuing the SAME shared pool the epic directory drew from.
    assert set(outcome.written_paths) == {
        "README.md",
        "epic.md",
        "issues/issue-a/first-slice-[ready].md",
        "issues/issue-b/second-slice-[blocked].md",
    }
    written_a = tmp_path / outcome.written_paths["issues/issue-a/first-slice-[ready].md"]
    written_b = tmp_path / outcome.written_paths["issues/issue-b/second-slice-[blocked].md"]
    assert written_a.read_text() == "issue a body"
    assert written_b.read_text() == "issue b body"
    assert written_a.name.endswith("-first-slice-[ready].md")
    assert written_b.name.endswith("-second-slice-[blocked].md")
    # Every allocated number is unique and none collides with the pre-existing 077.
    numbers = {int(p.split("/")[-1].split("-")[0]) for p in [outcome.epic_path, str(written_a.relative_to(tmp_path)), str(written_b.relative_to(tmp_path))]}
    assert 77 not in numbers
    assert len(numbers) == 3


def test_allocate_dir_retries_past_a_real_collision(tmp_path: Path):
    """Direct test of the atomic-creation retry loop itself -- the exact

    mechanism `materialize_epic` relies on to survive a numbering race (two
    publications whose OWN scans both missed each other, e.g. because they
    ran concurrently before either's write landed on disk).
    `list_used_issue_numbers` cannot catch that case by construction -- only
    the atomic `mkdir()` here can -- so this is exercised directly against a
    REAL pre-existing directory, not through a mocked scan.
    """
    docs_issues = tmp_path / "docs_issues"
    docs_issues.mkdir()
    (docs_issues / "001-slug").mkdir()

    next_cursor, path = _allocate_dir(docs_issues, 1, "slug")

    assert path == docs_issues / "002-slug"
    assert path.is_dir()
    assert next_cursor == 3
    # The colliding directory a concurrent publication already claimed was
    # left untouched, not overwritten.
    assert list((docs_issues / "001-slug").iterdir()) == []


def test_allocate_file_retries_past_a_real_collision(tmp_path: Path):
    """Same mechanism, for an issue file -- `os.open(..., O_CREAT|O_EXCL)`

    instead of `mkdir()`, same retry-with-next-number shape.
    """
    issues_dir = tmp_path / "issues"
    issues_dir.mkdir()
    (issues_dir / "001-foo-[ready].md").write_text("someone else's file", encoding="utf-8")

    next_cursor, path = _allocate_file(issues_dir, 1, "foo-[ready].md")

    assert path == issues_dir / "002-foo-[ready].md"
    assert path.exists()
    assert next_cursor == 3
    assert (issues_dir / "001-foo-[ready].md").read_text() == "someone else's file"


def test_materialize_epic_survives_a_numbering_race_end_to_end(tmp_path: Path, monkeypatch):
    """`materialize_epic` wired end-to-end against a numbering scan that

    UNDER-reports what is really on disk (simulating two publications racing
    before either's own scan saw the other's write) -- proving the atomic
    retry in `_allocate_dir` is what actually saves this call, not the scan
    alone.
    """
    docs_issues = tmp_path / "docs" / "issues"
    docs_issues.mkdir(parents=True)
    (docs_issues / "001-issue-materialize-bridge-[ready]").mkdir()

    monkeypatch.setattr(
        "agent.codex_bridge_agent.issue_materialize.list_used_issue_numbers",
        lambda project_root: set(),  # blind to the directory that already exists
    )

    outcome = materialize_epic(tmp_path, _request(files={"README.md": "r", "epic.md": "e"}))

    assert outcome.epic_path == "docs/issues/002-issue-materialize-bridge-[ready]"
    assert list((docs_issues / "001-issue-materialize-bridge-[ready]").iterdir()) == []


# --------------------------------------------------------------------------
# Path traversal.
# --------------------------------------------------------------------------


def test_materialize_epic_refuses_a_traversing_existing_path(tmp_path: Path):
    request = _request(existing_path="../outside", files={"README.md": "r", "epic.md": "e"})
    with pytest.raises(MaterializeError) as raised:
        materialize_epic(tmp_path, request)
    assert raised.value.code == "existing_path_invalid"


def test_materialize_epic_refuses_a_missing_existing_path(tmp_path: Path):
    request = _request(existing_path="docs/issues/999-does-not-exist", files={"README.md": "r", "epic.md": "e"})
    with pytest.raises(MaterializeError) as raised:
        materialize_epic(tmp_path, request)
    assert raised.value.code == "existing_path_not_found"


# --------------------------------------------------------------------------
# Republish: updates the existing directory instead of creating a new one.
# --------------------------------------------------------------------------


def test_materialize_epic_republish_updates_in_place_and_adds_new_issues(tmp_path: Path):
    first = materialize_epic(tmp_path, _request(files={
        "README.md": "readme v1",
        "epic.md": "epic v1",
        "issues/issue-a/first-slice-[ready].md": "issue a v1",
    }))
    assert first.epic_path == "docs/issues/001-issue-materialize-bridge-[ready]"

    second = materialize_epic(
        tmp_path,
        _request(
            existing_path=first.epic_path,
            files={
                "README.md": "readme v2",
                "epic.md": "epic v2",
                # Same relative key as before -- must overwrite the SAME
                # numbered file rather than allocate a second one.
                "issues/issue-a/first-slice-[ready].md": "issue a v2",
                # A brand-new issue on the republish -- must allocate a
                # fresh number rather than collide with the epic dir (001)
                # or the existing issue file.
                "issues/issue-b/second-slice-[blocked].md": "issue b v1",
            },
        ),
    )

    # Same directory, not a second one.
    assert second.epic_path == first.epic_path
    assert (tmp_path / second.epic_path / "README.md").read_text() == "readme v2"
    assert (tmp_path / second.epic_path / "epic.md").read_text() == "epic v2"

    # The republished issue kept its original number and file.
    original_written = tmp_path / first.written_paths["issues/issue-a/first-slice-[ready].md"]
    republished_written = tmp_path / second.written_paths["issues/issue-a/first-slice-[ready].md"]
    assert original_written == republished_written
    assert republished_written.read_text() == "issue a v2"

    # The new issue got a fresh, non-colliding number.
    new_written = tmp_path / second.written_paths["issues/issue-b/second-slice-[blocked].md"]
    assert new_written.read_text() == "issue b v1"
    assert new_written != original_written

    # No second epic directory was created for the same epic.
    assert sorted(p.name for p in (tmp_path / "docs" / "issues").iterdir()) == [
        "001-issue-materialize-bridge-[ready]"
    ]
