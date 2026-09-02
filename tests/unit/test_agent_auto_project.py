"""`agent.codex_bridge_agent.config.resolve_auto_project` -- the opt-in
fallback that lets an executor serve any real git repo under one directory
tree without a per-project entry in `allowed_projects_file`.

WK-20260830-chatgpt-entry-provider-and-delivery. Every test builds its own
throwaway directory tree under `tmp_path`; nothing here touches a real
project directory.
"""

from __future__ import annotations

from pathlib import Path

from agent.codex_bridge_agent.config import resolve_auto_project


def _make_repo(root: Path, *parts: str) -> Path:
    repo = root.joinpath(*parts)
    (repo / ".git").mkdir(parents=True)
    return repo


def test_resolves_a_real_repo_by_its_suggested_id(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path, "hub")
    project = resolve_auto_project("hub", str(tmp_path))
    assert project is not None
    assert project.project_id == "hub"
    assert project.path == str(repo)
    assert project.name == "hub"


def test_resolves_a_nested_submodule(tmp_path: Path) -> None:
    """The same reasoning `discover_projects.py` bakes in: monorepo
    submodules are separate projects too."""
    _make_repo(tmp_path, "monorepo")
    web = _make_repo(tmp_path, "monorepo", "packages", "web")
    project = resolve_auto_project("web", str(tmp_path))
    assert project is not None
    assert project.path == str(web)


def test_no_match_returns_none(tmp_path: Path) -> None:
    _make_repo(tmp_path, "hub")
    assert resolve_auto_project("does-not-exist", str(tmp_path)) is None


def test_a_root_that_is_not_a_directory_returns_none(tmp_path: Path) -> None:
    assert resolve_auto_project("hub", str(tmp_path / "does-not-exist")) is None


def test_a_directory_without_git_is_never_matched(tmp_path: Path) -> None:
    (tmp_path / "not-a-repo").mkdir()
    assert resolve_auto_project("not-a-repo", str(tmp_path)) is None


def test_a_symlinked_directory_outside_root_is_never_followed(tmp_path: Path) -> None:
    """`walk_for_git_repos` never follows a symlink -- this proves the
    fallback inherits that guarantee rather than re-opening it by resolving
    paths some other way."""
    outside = tmp_path.parent / f"{tmp_path.name}-outside"
    outside.mkdir()
    (outside / ".git").mkdir()
    root = tmp_path / "root"
    root.mkdir()
    (root / "escape-hatch").symlink_to(outside, target_is_directory=True)
    assert resolve_auto_project("escape-hatch", str(root)) is None


def test_the_resolved_id_matches_what_discover_projects_would_suggest(tmp_path: Path) -> None:
    """Consistency property this module's own docstring promises: an id a
    human read from `discover_projects.py`'s output must be the same id
    this fallback accepts later."""
    from shared.project_discovery import build_project_id_index

    _make_repo(tmp_path, "teamA", "api")
    _make_repo(tmp_path, "teamB", "api")
    index = build_project_id_index(tmp_path, max_depth=6)
    for suggested_id, expected_path in index.items():
        project = resolve_auto_project(suggested_id, str(tmp_path))
        assert project is not None
        assert project.path == str(expected_path)
