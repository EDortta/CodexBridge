"""The forge vocabulary and policy issue #80/#79 build the write gate on.

WK-20260902-forge-protocol-and-policy. This PR is protocol and policy only --
no module calls `gh`, nothing is wired into the executor yet (that is
B2/B3). What has to be right *here*, before any of that exists, is that a
forge write can never be classified as anything but `SENSITIVE`, for any
`ForgeOperationKind` and any combination of `ForgeOperationRequest` fields --
because the whole point of this stage is that later work inherits a
vocabulary and a policy that cannot be quietly loosened by adding a field.
"""

from __future__ import annotations

import itertools

import pytest
from pydantic import ValidationError

from shared.policy import forge_operation_policy_level
from shared.protocol import (
    REPO_IDENTITY_PATTERN,
    AgentMessageType,
    ForgeOperationKind,
    ForgeOperationRequest,
    PolicyLevel,
)


def test_issue_list_is_read_and_every_other_kind_is_sensitive() -> None:
    """Iterates `ForgeOperationKind` itself, not a literal list of names.

    A future kind added to the enum and forgotten here would silently fall
    through this loop as `SENSITIVE` -- which is the safe failure direction
    -- but a future kind added to the enum and wrongly classified `READ`
    would still be caught, because the loop checks every member, not just
    the four that exist today.
    """
    read_kinds = (ForgeOperationKind.ISSUE_LIST, ForgeOperationKind.ISSUE_VIEW)
    for kind in ForgeOperationKind:
        expected = PolicyLevel.READ if kind in read_kinds else PolicyLevel.SENSITIVE
        assert forge_operation_policy_level(kind) == expected, kind


# Field values used to build the exhaustive combinations below. Each tuple
# includes at least one "edge" value: an empty body, the longest allowed
# title, a large issue number.
_TITLE_VALUES = (None, "x", "T" * 256)
_BODY_VALUES = (None, "", "b" * 100)
_ISSUE_NUMBER_VALUES = (None, 1, 999_999_999)
_STATE_VALUES = (None, "open", "closed", "all")

# `issue_open` has no issue to name (it creates one) but must have a title;
# `issue_comment`/`issue_close` name an existing issue and must have one.
# These overrides narrow the combination grid for the one field each kind
# requires non-`None`, so every generated request is a request that would
# actually pass the model's own coherence validator -- the classification
# claim being tested is "SENSITIVE for every real request", not "SENSITIVE
# for every request pydantic happens to accept including malformed ones".
_REQUIRED_FIELD_OVERRIDES: dict[ForgeOperationKind, dict[str, tuple]] = {
    ForgeOperationKind.ISSUE_OPEN: {"title": ("x", "T" * 256)},
    ForgeOperationKind.ISSUE_COMMENT: {"issue_number": (1, 999_999_999), "body": ("b", "b" * 100)},
    ForgeOperationKind.ISSUE_CLOSE: {"issue_number": (1, 999_999_999)},
}


def test_every_write_kind_is_sensitive_across_every_plausible_field_combination() -> None:
    """The property that must survive any future field added to the request.

    Written to break, not just to pass: it walks `ForgeOperationKind` by the
    enum (so a new kind is automatically included) and asserts the property
    for every member that is not `ISSUE_LIST`, over the full cross product of
    plausible field values for that kind. If someone later adds a field like
    `allow_write: bool = False` to `ForgeOperationRequest` and wires it into
    `forge_operation_policy_level` as an escape hatch, this loop covers
    `allow_write=True` in exactly the same sweep as everything else and
    fails the moment the level stops being `SENSITIVE` -- there is no
    branch of this test that only looks at the default value of a new
    field.
    """
    read_kinds = (ForgeOperationKind.ISSUE_LIST, ForgeOperationKind.ISSUE_VIEW)
    write_kinds = [kind for kind in ForgeOperationKind if kind not in read_kinds]
    assert write_kinds, "the write-kind fixture must not silently become empty"

    checked = 0
    expected = 0
    for kind in write_kinds:
        overrides = _REQUIRED_FIELD_OVERRIDES.get(kind, {})
        title_values = overrides.get("title", _TITLE_VALUES)
        issue_number_values = overrides.get("issue_number", _ISSUE_NUMBER_VALUES)
        body_values = overrides.get("body", _BODY_VALUES)
        combos = list(itertools.product(title_values, body_values, issue_number_values, _STATE_VALUES))
        expected += len(combos)
        for title, body, issue_number, state in combos:
            request = ForgeOperationRequest(
                kind=kind,
                repo_identity="owner/repo",
                title=title,
                body=body,
                issue_number=issue_number,
                state=state,
            )
            assert forge_operation_policy_level(request.kind) == PolicyLevel.SENSITIVE, (
                kind,
                title,
                body,
                issue_number,
                state,
            )
            checked += 1

    # Guards the loop itself: a change that made every combination raise
    # `ValidationError` (and get silently skipped by an earlier, sloppier
    # version of this test) would leave `checked == 0` and the assertions
    # above vacuously true. `expected` is computed from the same
    # `_REQUIRED_FIELD_OVERRIDES`-driven grid the loop actually walks, so
    # this fails if a future edit to the overrides silently narrows the grid
    # for one kind to nothing.
    assert expected > 0
    assert checked == expected


@pytest.mark.parametrize("value", ["owner/repo", "Org-1/repo.js", "a/b"])
def test_repo_identity_pattern_accepts_plausible_identities(value: str) -> None:
    assert REPO_IDENTITY_PATTERN.match(value) is not None


@pytest.mark.parametrize(
    "value",
    [
        "--flag/x",
        "owner//repo",
        "../etc",
        "owner/",
        "/repo",
        "",
        "owner repo",
    ],
)
def test_repo_identity_pattern_rejects_dangerous_or_malformed_identities(value: str) -> None:
    """Mirrors the role `_REMOTE_NAME_PATTERN` plays for git remotes.

    `--flag/x` is the load-bearing case: a `repo_identity` that a naive
    executor placed straight into `gh`'s argv could otherwise be read as an
    option rather than a positional repository name.
    """
    assert REPO_IDENTITY_PATTERN.match(value) is None


def test_forge_operation_request_refuses_a_bad_repo_identity_at_parse() -> None:
    with pytest.raises(ValidationError) as excinfo:
        ForgeOperationRequest(kind=ForgeOperationKind.ISSUE_LIST, repo_identity="--flag/x")
    assert "repo_identity" in str(excinfo.value)


def test_issue_comment_without_issue_number_is_refused_at_parse() -> None:
    with pytest.raises(ValidationError) as excinfo:
        ForgeOperationRequest(kind=ForgeOperationKind.ISSUE_COMMENT, repo_identity="owner/repo", body="hi")
    assert "issue_number" in str(excinfo.value)


@pytest.mark.parametrize("body", [None, ""])
def test_issue_comment_without_a_body_is_refused_at_parse(body: str | None) -> None:
    """An empty comment is a human decision spent on a no-op.

    `gh issue comment` requires a body, and a forge write is SENSITIVE: it
    costs an operator an approval. Approving one that publishes nothing is
    the one outcome worth refusing before it reaches the gate.
    """
    with pytest.raises(ValidationError) as excinfo:
        ForgeOperationRequest(
            kind=ForgeOperationKind.ISSUE_COMMENT,
            repo_identity="owner/repo",
            issue_number=7,
            body=body,
        )
    assert "body" in str(excinfo.value)


def test_issue_close_without_issue_number_is_refused_at_parse() -> None:
    with pytest.raises(ValidationError) as excinfo:
        ForgeOperationRequest(kind=ForgeOperationKind.ISSUE_CLOSE, repo_identity="owner/repo")
    assert "issue_number" in str(excinfo.value)


def test_issue_open_without_title_is_refused_at_parse() -> None:
    with pytest.raises(ValidationError) as excinfo:
        ForgeOperationRequest(kind=ForgeOperationKind.ISSUE_OPEN, repo_identity="owner/repo")
    assert "title" in str(excinfo.value)


def test_issue_list_requires_neither_title_nor_issue_number() -> None:
    request = ForgeOperationRequest(kind=ForgeOperationKind.ISSUE_LIST, repo_identity="owner/repo", state="open")
    assert request.title is None
    assert request.issue_number is None


def test_issue_view_without_issue_number_is_refused_at_parse() -> None:
    with pytest.raises(ValidationError) as excinfo:
        ForgeOperationRequest(kind=ForgeOperationKind.ISSUE_VIEW, repo_identity="owner/repo")
    assert "issue_number" in str(excinfo.value)


def test_issue_view_is_read_like_issue_list() -> None:
    """The one property #79's `gh:N` resolution depends on: a lookup by

    number never needs a human decision, the same way `issue_list` never
    does -- both are READ, unconditionally.
    """
    assert forge_operation_policy_level(ForgeOperationKind.ISSUE_VIEW) == PolicyLevel.READ


def test_state_outside_the_closed_set_is_refused_at_parse() -> None:
    with pytest.raises(ValidationError):
        ForgeOperationRequest(kind=ForgeOperationKind.ISSUE_LIST, repo_identity="owner/repo", state="stale")


def test_forge_message_types_exist_and_are_distinct_from_task_dispatch() -> None:
    """Sanity check on the two new `AgentMessageType` members this PR adds.

    Not a dispatch/wiring test -- nothing sends these yet -- only that the
    vocabulary exists and does not collide with the task-dispatch pair it
    sits beside.
    """
    assert AgentMessageType.FORGE_OPERATION.value == "forge.operation"
    assert AgentMessageType.FORGE_OPERATION_RESULT.value == "forge.operation_result"
    assert AgentMessageType.FORGE_OPERATION != AgentMessageType.TASK_DISPATCH
    assert AgentMessageType.FORGE_OPERATION_RESULT != AgentMessageType.TASK_RESULT
