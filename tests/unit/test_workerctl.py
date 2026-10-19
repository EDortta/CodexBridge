"""Stage-one Worker activation tests: no GitHub or Gateway network traffic."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import subprocess
import sys

import pytest

from scripts import workerctl as wc

NOW = datetime(2026, 10, 19, 12, 0, tzinfo=timezone.utc)


def _registered(count=4):
    state = wc._empty_state()
    for n in range(count):
        wc.register(state, f"p{n}", f"example/repo{n}")
    return state


def test_three_projects_allowed_but_fourth_refused():
    state = _registered()
    for n in range(3):
        assert wc.enable(state, f"p{n}", NOW) == "enabled"
    with pytest.raises(wc.WorkerctlError, match="three projects"):
        wc.enable(state, "p3", NOW)
    assert len([row for row in wc.list_projects(state, NOW) if row["status"] == "active"]) == 3


def test_exact_eight_hours_with_utc_and_local_offset():
    state = _registered(1)
    offset_time = NOW.astimezone(timezone(timedelta(hours=-3)))
    wc.enable(state, "p0", offset_time)
    assert state["activations"]["p0"]["expires_at"] == "2026-10-19T20:00:00Z"
    assert wc.list_projects(state, NOW + timedelta(hours=7, minutes=59))[0]["status"] == "active"
    assert wc.list_projects(state, NOW + timedelta(hours=8))[0]["status"] == "expired"
    assert wc.list_projects(state, NOW + timedelta(days=1))[0]["status"] == "expired"


def test_repeated_enable_does_not_renew_and_explicit_reactivation_does():
    state = _registered(1)
    wc.enable(state, "p0", NOW)
    assert wc.enable(state, "p0", NOW + timedelta(hours=7)) == "already active (expiry unchanged)"
    assert wc.list_projects(state, NOW)[0]["expires_at"] == "2026-10-19T20:00:00Z"
    assert wc.enable(state, "p0", NOW + timedelta(hours=8)) == "enabled"
    assert wc.list_projects(state, NOW + timedelta(hours=8))[0]["expires_at"] == "2026-10-20T04:00:00Z"


def test_disable_frees_slot_without_removing_other_registration():
    state = _registered()
    for n in range(3):
        wc.enable(state, f"p{n}", NOW)
    assert wc.disable(state, "p0", NOW + timedelta(minutes=3)) == "disabled"
    assert wc.disable(state, "p0", NOW + timedelta(minutes=4)) == "already disabled/inactive"
    assert wc.enable(state, "p3", NOW + timedelta(minutes=4)) == "enabled"
    assert wc.list_projects(state, NOW + timedelta(minutes=5))[0]["status"] == "disabled"


def test_expired_slot_is_reusable():
    state = _registered()
    for n in range(3):
        wc.enable(state, f"p{n}", NOW)
    assert wc.enable(state, "p3", NOW + timedelta(hours=8)) == "enabled"


def test_registration_is_idempotent_and_cannot_be_retarged_while_active():
    state = _registered(1)
    assert wc.register(state, "p0", "example/repo0") == "unchanged"
    wc.enable(state, "p0", NOW)
    with pytest.raises(wc.WorkerctlError, match="disable"):
        wc.register(state, "p0", "example/another", now=NOW)
    wc.disable(state, "p0", NOW)
    assert wc.register(state, "p0", "example/another", now=NOW) == "registered"


@pytest.mark.parametrize("project,repo,branch", [
    ("../a", "good/repo", "codexbridge-control"),
    ("good", "https://github.com/acme/repo", "codexbridge-control"),
    ("good", "acme/repo", "../../evil"),
    ("good", "acme/repo", "name.lock"),
    ("good", "acme/repo", "a//b"),
])
def test_bad_identifiers_refused(project, repo, branch):
    with pytest.raises(wc.WorkerctlError):
        wc.register(wc._empty_state(), project, repo, branch)


def test_same_repo_cannot_consume_multiple_alias_slots():
    state = _registered(1)
    with pytest.raises(wc.WorkerctlError, match="already registered"):
        wc.register(state, "another", "EXAMPLE/repo0")


def test_naive_time_or_clock_rewind_is_not_active():
    state = _registered(1)
    with pytest.raises(wc.WorkerctlError, match="timezone"):
        wc.enable(state, "p0", datetime(2026, 10, 19, 12))
    wc.enable(state, "p0", NOW)
    assert wc.list_projects(state, NOW - timedelta(minutes=1))[0]["status"] == "clock_error"
    with pytest.raises(wc.WorkerctlError, match="clock"):
        wc.enable(state, "p0", NOW - timedelta(minutes=1))


def test_state_file_errors_fail_closed_without_reset(tmp_path):
    state_path = tmp_path / "state.json"
    state_path.write_text("{corrupted", encoding="utf-8")
    assert wc.main(["--state-file", str(state_path), "register", "--project", "x", "--repository", "org/repo"]) == 1
    assert state_path.read_text(encoding="utf-8") == "{corrupted"


def test_invalid_window_duration_in_state_is_refused():
    state = _registered(1)
    wc.enable(state, "p0", NOW)
    state["activations"]["p0"]["expires_at"] = "2026-10-20T04:00:00Z"
    with pytest.raises(wc.WorkerctlError, match="eight hours"):
        wc._validate_state(state)


def test_state_file_symlink_is_not_followed(tmp_path):
    state_path = tmp_path / "state.json"
    target = tmp_path / "target.json"
    target.write_text("secret", encoding="utf-8")
    try:
        state_path.symlink_to(target)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks not supported")
    assert wc.main(["--state-file", str(state_path), "list"]) == 1
    assert target.read_text(encoding="utf-8") == "secret"


def test_cli_register_enable_list_disable_and_persist(tmp_path, capsys):
    state_path = tmp_path / "workerctl.json"
    head = ["--state-file", str(state_path)]
    assert wc.main(head + ["register", "--project", "p0", "--repository", "org/repo"]) == 0
    assert wc.main(head + ["enable", "--project", "p0"]) == 0
    assert wc.main(head + ["list", "--json"]) == 0
    output = capsys.readouterr().out
    rows = json.loads(output[output.index("[\n"):])
    assert rows[0]["status"] == "active"
    assert rows[0]["control_branch"] == wc.CONTROL_BRANCH
    assert wc.main(head + ["disable", "--project", "p0"]) == 0
    assert wc._read_state(state_path)["activations"]["p0"].get("disabled_at")


def test_two_competing_cli_processes_cannot_admit_four_projects(tmp_path):
    path = tmp_path / "state.json"
    initial = _registered(4)
    wc._write_state(path, initial)
    script = Path(wc.__file__).resolve()
    def run(n):
        return subprocess.run([sys.executable, str(script), "--state-file", str(path),
                               "enable", "--project", f"p{n}"], capture_output=True, text=True)
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(run, range(4)))
    assert sorted(result.returncode for result in results) == [0, 0, 0, 1]
    assert sum(row["status"] == "active" for row in wc.list_projects(wc._read_state(path), wc._utc_now())) == 3


def test_new_state_is_not_implicitly_approved(tmp_path):
    missing = tmp_path / "no-state.json"
    assert wc.main(["--state-file", str(missing), "list"]) == 0
    assert not missing.exists()


def test_path_default_is_platform_appropriate(monkeypatch, tmp_path):
    monkeypatch.setenv("CODEXBRIDGE_WORKERCTL_STATE", str(tmp_path / "worker.json"))
    assert wc.default_state_file() == tmp_path / "worker.json"


def test_clock_rewind_in_another_project_blocks_new_activations():
    state = _registered(2)
    wc.enable(state, "p0", NOW)
    with pytest.raises(wc.WorkerctlError, match="clock rollback"):
        wc.enable(state, "p1", NOW - timedelta(minutes=1))
