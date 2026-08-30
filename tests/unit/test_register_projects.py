"""`scripts/register_projects.py` -- diff-only, never applies anything.

WK-20260830-chatgpt-entry-provider-and-delivery, Fase C. Every assertion
that a target file is "unchanged" reads its bytes before and after the
call -- the strongest guarantee this script's central promise (it never
writes to any file it reads) actually holds.
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "register_projects.py"

spec = importlib.util.spec_from_file_location("register_projects", SCRIPT)
register_projects = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = register_projects  # dataclasses needs the module registered to resolve its own annotations
spec.loader.exec_module(register_projects)

Approved = register_projects.ApprovedProject


def _write_json(path: Path, payload: object) -> None:
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_registry_diff_adds_only_the_missing_projects(tmp_path: Path) -> None:
    registry_file = tmp_path / "registry.json"
    _write_json(
        registry_file,
        {"executors": [], "projects": [{"project_id": "existing", "name": "Existing", "path": "/srv/existing"}]},
    )
    approved = [
        Approved(project_id="existing", name="Existing", path="/srv/existing"),
        Approved(project_id="brand-new", name="Brand New", path="/srv/brand-new"),
    ]
    additions, notes = register_projects.diff_registry_projects(approved, registry_file)
    assert [a["project_id"] for a in additions] == ["brand-new"]
    assert notes == []


def test_registry_diff_flags_a_path_collision_instead_of_silently_skipping(tmp_path: Path) -> None:
    registry_file = tmp_path / "registry.json"
    _write_json(
        registry_file,
        {"executors": [], "projects": [{"project_id": "dup", "name": "Dup", "path": "/srv/old-path"}]},
    )
    approved = [Approved(project_id="dup", name="Dup", path="/srv/new-path")]
    additions, notes = register_projects.diff_registry_projects(approved, registry_file)
    assert additions == []
    assert len(notes) == 1
    assert "/srv/old-path" in notes[0]
    assert "/srv/new-path" in notes[0]


def test_registry_diff_treats_a_missing_file_as_an_empty_registry(tmp_path: Path) -> None:
    registry_file = tmp_path / "does-not-exist.json"
    approved = [Approved(project_id="p1", name="P1", path="/srv/p1")]
    additions, notes = register_projects.diff_registry_projects(approved, registry_file)
    assert [a["project_id"] for a in additions] == ["p1"]
    assert notes == []
    assert not registry_file.exists()  # never created by the diff step


def test_executor_diff_adds_only_ids_not_already_allowed(tmp_path: Path) -> None:
    registry_file = tmp_path / "registry.json"
    _write_json(
        registry_file,
        {
            "executors": [{"executor_id": "E1", "allowed_projects": ["already-allowed"]}],
            "projects": [],
        },
    )
    approved = [
        Approved(project_id="already-allowed", name="A", path="/srv/a"),
        Approved(project_id="new-one", name="B", path="/srv/b"),
    ]
    additions, notes = register_projects.diff_executor_allowed_projects(approved, registry_file, "E1")
    assert additions == ["new-one"]
    assert notes == []


def test_executor_diff_notes_an_unknown_executor_id(tmp_path: Path) -> None:
    registry_file = tmp_path / "registry.json"
    _write_json(registry_file, {"executors": [], "projects": []})
    additions, notes = register_projects.diff_executor_allowed_projects(
        [Approved(project_id="p1", name="P1", path="/srv/p1")], registry_file, "GHOST"
    )
    assert additions == []
    assert "GHOST" in notes[0]


def test_local_allowed_projects_diff_matches_registry_diff_shape(tmp_path: Path) -> None:
    allowed_file = tmp_path / "allowed-projects.json"
    _write_json(allowed_file, {"projects": [{"project_id": "existing", "path": "/srv/existing"}]})
    approved = [
        Approved(project_id="existing", name="Existing", path="/srv/existing"),
        Approved(project_id="new-one", name="New", path="/srv/new"),
    ]
    additions, notes = register_projects.diff_local_allowed_projects(approved, allowed_file)
    assert [a["project_id"] for a in additions] == ["new-one"]
    assert notes == []


def test_user_diff_adds_only_ids_not_already_allowed(tmp_path: Path) -> None:
    user_file = tmp_path / "users.json"
    _write_json(
        user_file,
        {"users": [{"user_id": "u1", "email": "u1@example.com", "allowed_projects": ["already-allowed"]}]},
    )
    approved = [
        Approved(project_id="already-allowed", name="A", path="/srv/a"),
        Approved(project_id="new-one", name="B", path="/srv/b"),
    ]
    additions, notes = register_projects.diff_user_allowed_projects(approved, user_file, "u1")
    assert additions == ["new-one"]
    assert notes == []


def test_user_diff_matches_by_email_case_insensitively(tmp_path: Path) -> None:
    user_file = tmp_path / "users.json"
    _write_json(user_file, {"users": [{"user_id": "u1", "email": "Someone@Example.com", "allowed_projects": []}]})
    additions, notes = register_projects.diff_user_allowed_projects(
        [Approved(project_id="p1", name="P1", path="/srv/p1")], user_file, "someone@example.com"
    )
    assert additions == ["p1"]
    assert notes == []


def test_duplicate_project_id_in_the_approved_list_is_rejected(tmp_path: Path) -> None:
    approved_file = tmp_path / "approved.json"
    _write_json(
        approved_file,
        [
            {"project_id": "dup", "name": "A", "path": "/srv/a"},
            {"project_id": "dup", "name": "B", "path": "/srv/b"},
        ],
    )
    try:
        register_projects._load_approved(approved_file)
        assert False, "expected ValueError"
    except ValueError as exc:
        assert "dup" in str(exc)


def test_cli_never_writes_to_any_file_it_reads(tmp_path: Path) -> None:
    registry_file = tmp_path / "registry.json"
    _write_json(registry_file, {"executors": [], "projects": []})
    allowed_file = tmp_path / "allowed-projects.json"
    _write_json(allowed_file, {"projects": []})
    approved_file = tmp_path / "approved.json"
    _write_json(approved_file, [{"project_id": "p1", "name": "P1", "path": "/srv/p1"}])

    registry_before = registry_file.read_bytes()
    allowed_before = allowed_file.read_bytes()

    result = subprocess.run(
        [
            sys.executable, str(SCRIPT),
            "--from", str(approved_file),
            "--registry-file", str(registry_file),
            "--local-allowed-projects-file", str(allowed_file),
        ],
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    assert registry_file.read_bytes() == registry_before
    assert allowed_file.read_bytes() == allowed_before
    assert "p1" in result.stdout


def test_cli_writes_only_the_report_when_out_is_given(tmp_path: Path) -> None:
    approved_file = tmp_path / "approved.json"
    _write_json(approved_file, [{"project_id": "p1", "name": "P1", "path": "/srv/p1"}])
    registry_file = tmp_path / "registry.json"
    _write_json(registry_file, {"executors": [], "projects": []})
    out_file = tmp_path / "report.md"

    result = subprocess.run(
        [
            sys.executable, str(SCRIPT),
            "--from", str(approved_file),
            "--registry-file", str(registry_file),
            "--out", str(out_file),
        ],
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    assert result.stdout.strip() == ""
    assert "p1" in out_file.read_text(encoding="utf-8")


def test_cli_requires_at_least_one_target_file(tmp_path: Path) -> None:
    approved_file = tmp_path / "approved.json"
    _write_json(approved_file, [])
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--from", str(approved_file)],
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0


def test_cli_rejects_user_id_without_user_registry_file(tmp_path: Path) -> None:
    approved_file = tmp_path / "approved.json"
    _write_json(approved_file, [])
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--from", str(approved_file), "--user-id", "u1"],
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
