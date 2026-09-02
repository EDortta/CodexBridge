"""Writes one epic's rendered markdown to disk -- issue #78, Commit 2c.

The EXECUTOR, not the gateway, chooses every `NNN` this module writes, for
the same reason `instructions.py`'s `resolve_issue_text` reads
`docs/issues/` on the executor instead of the gateway: the gateway never
learns a project's real path (`docs/architecture.md`). Numbering has the same
constraint one layer deeper -- deciding "the next free number" requires
listing what is already on disk, which only the executor can see.

Correlation trick, spelled out in full here because two other modules depend
on it without sharing any in-process state (see
`gateway/app/services/issue_render.py` and `gateway/app/services/store.py:
apply_epic_materialization`): `MaterializeRequest.files` keys embed the issue
id as a path segment -- `issues/<issue_id>/<slug>-[<status>].md` -- purely as
an addressing convention for this one round trip. It is NEVER written to
disk: this module strips the `<issue_id>/` segment before choosing the real,
numbered filename, and echoes the ORIGINAL key (with the id segment intact)
back in `ISSUE_MATERIALIZE_RESULT.written_paths`, so the gateway can parse the
id back out on the other side of a round trip that may cross a gateway
restart.

Numbering is a single shared pool across the epic's own directory AND every
issue file under it (and every OTHER epic/issue already on disk) --
`list_used_issue_numbers` (`instructions.py`) does not distinguish "this
number names a folder" from "this number names a file nested under some
other epic's issues/": a bare `NNN` issue reference must resolve
unambiguously, so no two things under `docs/issues/` may ever share a
number, regardless of what kind of thing each one is.

Race safety: two publications racing for the same number are resolved by
atomic creation -- `Path.mkdir()` for the epic directory, `os.open(...,
O_CREAT | O_EXCL)` for an issue file -- retried with the next number on a
collision, never by a lock file (`tests/unit/test_issue_materialize.py`
exercises this directly by pre-creating the first candidate).
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from agent.codex_bridge_agent.instructions import list_used_issue_numbers
from shared.protocol import MaterializeRequest
from shared.security import ensure_within_root


class MaterializeError(RuntimeError):
    """A typed reason a `MaterializeRequest` could not be written.

    `str(error)` is exactly the code -- what `AgentService._handle_materialize`
    reports back as `ISSUE_MATERIALIZE_RESULT.error`, never a raw traceback.
    """

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class MaterializeOutcome:
    epic_path: str
    written_paths: dict[str, str] = field(default_factory=dict)


def _split_issue_key(key: str) -> tuple[str, str] | None:
    """`"issues/<issue_id>/<rest>"` -> `(issue_id, rest)`, or `None` for a

    key with no `issues/<id>/` segment (`README.md`, `epic.md`).
    """
    if not key.startswith("issues/"):
        return None
    remainder = key[len("issues/"):]
    issue_id, sep, rest = remainder.partition("/")
    if not sep or not rest:
        return None
    return issue_id, rest


# A collision run this long means something is wrong beyond an ordinary
# numbering race (two publications landing on the same starting number) --
# refuse loudly rather than spin forever.
_MAX_ALLOCATION_ATTEMPTS = 10_000


def _allocate_dir(docs_issues: Path, start: int, slug: str) -> tuple[int, Path]:
    n = start
    for _ in range(_MAX_ALLOCATION_ATTEMPTS):
        candidate = docs_issues / f"{n:03d}-{slug}"
        try:
            candidate.mkdir()
            return n + 1, candidate
        except FileExistsError:
            n += 1
    raise MaterializeError("numbering_exhausted")


def _allocate_file(issues_dir: Path, start: int, suffix: str) -> tuple[int, Path]:
    n = start
    for _ in range(_MAX_ALLOCATION_ATTEMPTS):
        candidate = issues_dir / f"{n:03d}-{suffix}"
        try:
            fd = os.open(str(candidate), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
        except FileExistsError:
            n += 1
            continue
        os.close(fd)
        return n + 1, candidate
    raise MaterializeError("numbering_exhausted")


def _find_existing_issue_file(issues_dir: Path, suffix: str) -> Path | None:
    """A previously-published file for this issue, matched by trailing

    filename (everything after its own `NNN-` prefix). Plain string
    comparison, not `glob(f"*{suffix}")`: `suffix` legitimately contains `[`
    and `]` (the status suffix, e.g. `foo-[ready].md`), which `glob` would
    otherwise interpret as a character class instead of literal text.
    """
    if not issues_dir.is_dir():
        return None
    for entry in issues_dir.iterdir():
        if entry.is_file() and entry.name.endswith(suffix):
            return entry
    return None


def materialize_epic(project_root: Path, request: MaterializeRequest) -> MaterializeOutcome:
    """Writes `request.files` under `project_root/docs/issues/`, allocating

    (or reusing, on republish) every `NNN`. Raises `MaterializeError` on any
    refusal; every write is preceded by `ensure_within_root`, the same
    traversal guard `resolve_issue_text` applies on the read side.
    """
    docs_issues = project_root / "docs" / "issues"
    docs_issues.mkdir(parents=True, exist_ok=True)

    cursor = max(list_used_issue_numbers(project_root), default=0) + 1

    republish = request.existing_path is not None
    if republish:
        epic_dir = (project_root / request.existing_path).resolve()
        try:
            ensure_within_root(str(project_root), str(epic_dir))
        except ValueError as exc:
            raise MaterializeError("existing_path_invalid") from exc
        if not epic_dir.is_dir():
            raise MaterializeError("existing_path_not_found")
    else:
        cursor, epic_dir = _allocate_dir(docs_issues, cursor, request.slug)
        ensure_within_root(str(project_root), str(epic_dir))

    issues_dir = epic_dir / "issues"
    issues_dir.mkdir(parents=True, exist_ok=True)

    written_paths: dict[str, str] = {}
    for key, content in request.files.items():
        split = _split_issue_key(key)
        if split is None:
            # README.md / epic.md -- written directly under the epic's own
            # directory. `key` here is one of exactly those two literals
            # (`issue_render.render_epic_markdown`'s own contract), never
            # caller-controlled, but this still runs through
            # `ensure_within_root` rather than being assumed safe.
            target = epic_dir / key
            ensure_within_root(str(project_root), str(target))
            target.write_text(content, encoding="utf-8")
            written_paths[key] = _relative(target, project_root)
            continue

        _issue_id, suffix = split
        existing = _find_existing_issue_file(issues_dir, suffix) if republish else None
        if existing is not None:
            target = existing
        else:
            cursor, target = _allocate_file(issues_dir, cursor, suffix)
        ensure_within_root(str(project_root), str(target))
        target.write_text(content, encoding="utf-8")
        written_paths[key] = _relative(target, project_root)

    return MaterializeOutcome(epic_path=_relative(epic_dir, project_root), written_paths=written_paths)


def _relative(path: Path, project_root: Path) -> str:
    return str(path.relative_to(project_root)).replace(os.sep, "/")
