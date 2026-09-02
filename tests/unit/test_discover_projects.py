"""`scripts/discover_projects.py` -- read-only repo discovery.

WK-20260830-chatgpt-entry-provider-and-delivery, Fase C. Every test builds
its own throwaway directory tree under `tmp_path`; nothing here touches the
real `~/Sync/Projects`.
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "discover_projects.py"

spec = importlib.util.spec_from_file_location("discover_projects", SCRIPT)
discover_projects = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = discover_projects  # dataclasses needs the module registered to resolve its own annotations
spec.loader.exec_module(discover_projects)


def _make_repo(root: Path, *parts: str) -> Path:
    repo = root.joinpath(*parts)
    (repo / ".git").mkdir(parents=True)
    return repo


def test_finds_a_top_level_repo(tmp_path: Path) -> None:
    _make_repo(tmp_path, "my-project")
    candidates = discover_projects.discover(tmp_path)
    assert [c.path for c in candidates] == [str(tmp_path / "my-project")]


def test_descends_past_a_repo_root_to_find_a_submodule(tmp_path: Path) -> None:
    """CLAUDE.md: "Vale monorepo e submódulos (web, api, etc.)" -- a nested
    `.git` (a submodule) must be discovered too, not just its parent repo."""
    parent = _make_repo(tmp_path, "monorepo")
    _make_repo(parent, "packages", "web")
    candidates = discover_projects.discover(tmp_path)
    paths = {c.path for c in candidates}
    assert str(parent) in paths
    assert str(parent / "packages" / "web") in paths


def test_never_descends_into_excluded_directory_names(tmp_path: Path) -> None:
    _make_repo(tmp_path, "real-project")
    # A repo accidentally vendored inside node_modules must not surface as
    # its own candidate -- these are almost always someone else's project.
    _make_repo(tmp_path, "real-project", "node_modules", "some-dependency")
    (tmp_path / "real-project" / ".venv").mkdir(parents=True)
    _make_repo(tmp_path / "real-project" / ".venv", "lib")
    candidates = discover_projects.discover(tmp_path)
    assert [c.path for c in candidates] == [str(tmp_path / "real-project")]


def test_max_depth_stops_descent(tmp_path: Path) -> None:
    _make_repo(tmp_path, "a", "b", "c", "deep-repo")
    candidates = discover_projects.discover(tmp_path, max_depth=2)
    assert candidates == []
    candidates = discover_projects.discover(tmp_path, max_depth=4)
    assert len(candidates) == 1


def test_suggested_project_ids_are_unique_on_a_name_collision(tmp_path: Path) -> None:
    """The first `api` seen keeps the plain name; only the later collision
    gets disambiguated with its parent folder -- ids must stay unique either
    way, which is the property this test actually guards."""
    _make_repo(tmp_path, "teamA", "api")
    _make_repo(tmp_path, "teamB", "api")
    candidates = discover_projects.discover(tmp_path)
    ids = [c.suggested_project_id for c in candidates]
    assert len(ids) == len(set(ids))
    assert "api" in ids
    assert "teamb-api" in ids


def test_flags_a_candidate_already_in_the_local_allowlist(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path, "known-project")
    allowed_file = tmp_path / "allowed-projects.json"
    allowed_file.write_text(
        json.dumps({"projects": [{"project_id": "known-project", "path": str(repo)}]}),
        encoding="utf-8",
    )
    candidates = discover_projects.discover(tmp_path, local_allowed_projects_file=allowed_file)
    assert candidates[0].already_in_local_executor_allowlist is True


def test_a_malformed_local_allowlist_is_treated_as_empty_not_a_crash(tmp_path: Path) -> None:
    _make_repo(tmp_path, "some-project")
    allowed_file = tmp_path / "allowed-projects.json"
    allowed_file.write_text("not valid json", encoding="utf-8")
    candidates = discover_projects.discover(tmp_path, local_allowed_projects_file=allowed_file)
    assert len(candidates) == 1
    assert candidates[0].already_in_local_executor_allowlist is False


def test_cli_writes_json_to_the_requested_output_file(tmp_path: Path) -> None:
    _make_repo(tmp_path, "cli-project")
    out_file = tmp_path / "out.json"
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--root", str(tmp_path), "--out", str(out_file)],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    payload = json.loads(out_file.read_text(encoding="utf-8"))
    assert len(payload) == 1
    assert payload[0]["path"] == str(tmp_path / "cli-project")


def test_cli_never_writes_anywhere_but_the_requested_output_file(tmp_path: Path) -> None:
    """Read-only by contract: the script's own docstring promises this."""
    _make_repo(tmp_path, "some-project")
    before = {p: p.stat().st_mtime for p in tmp_path.rglob("*")}
    subprocess.run(
        [sys.executable, str(SCRIPT), "--root", str(tmp_path), "--format", "table"],
        capture_output=True,
        text=True,
    )
    after = {p: p.stat().st_mtime for p in tmp_path.rglob("*")}
    assert before == after


def test_cli_rejects_a_root_that_is_not_a_directory(tmp_path: Path) -> None:
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--root", str(tmp_path / "does-not-exist")],
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
