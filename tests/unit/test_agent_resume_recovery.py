"""Agent deployment recovery acceptance, with no live service mutation."""
from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys

import pytest

from scripts import deploy_agent as deploy
from scripts import verify_agent_deploy_resume as checker


ID = "ag-20261127T181509Z-52d0af5a"


def test_recovery_from_detached_worker_receipt_without_second_start(tmp_path, monkeypatch):
    """Client vanished with a pending job; detached worker finishes independently."""
    monkeypatch.setattr(deploy, "JOBS", tmp_path / "jobs")
    monkeypatch.setattr(deploy, "STAGES", tmp_path / "stages")
    stage = deploy.STAGES / ID
    stage.mkdir(parents=True)
    job = {
        "id": ID, "state": "running", "evidence": "pending",
        "source_commit": "a" * 40, "baseline_commit": "b" * 40, "hashes": [],
    }
    deploy.save(job)
    # External process survives caller and writes the worker's immutable receipt.
    writer = subprocess.Popen(
        [sys.executable, "-c",
         "import json,sys,time;from pathlib import Path;"
         "time.sleep(0.10);"
         "Path(sys.argv[1]).write_text(json.dumps({"
         "'id':sys.argv[2],'status':'deployed','reason':'none',"
         "'rollback':'not_needed','service_active':True,'ws_verified':False"
         "}))",
         str(stage / "result.json"), ID],
        start_new_session=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    monkeypatch.setattr(deploy, "start", lambda *_args: pytest.fail("second start forbidden"))
    monkeypatch.setattr(deploy, "publish", lambda *_args: True)
    assert deploy.reconcile(job) == 3
    assert deploy.load(ID)["state"] == "pending"
    assert writer.wait(timeout=5) == 0
    assert deploy.main(["--resume", ID]) == 0
    assert deploy.load(ID)["state"] == "success"
    assert deploy.load(ID)["evidence"] == "published"
    assert deploy.main(["--resume", ID]) == 0


def test_recovery_checker_rejects_unpublished_job(tmp_path, monkeypatch):
    monkeypatch.setattr(deploy, "JOBS", tmp_path)
    deploy.save({"id": ID, "state": "pending", "evidence": "pending"})
    with pytest.raises(checker.RecoveryError, match="deployment_not_published_success"):
        checker.snapshot(ID)


def test_recovery_checker_does_not_mutate_live_state(monkeypatch):
    before = {
        "pid": 100, "commit": "a" * 40, "hashes": {"a": "b"},
        "receipt_sha256": "c", "job_sha256": "d",
    }
    monkeypatch.setattr(checker, "snapshot", lambda _id: before.copy())
    monkeypatch.setattr(deploy, "path_for", lambda _id: Path("/tmp/not-used"))
    monkeypatch.setattr(checker.subprocess, "run",
                        lambda *_a, **_kw: subprocess.CompletedProcess([], 0, "", ""))
    checker.verify(ID)


def test_recovery_checker_detects_changed_pid(monkeypatch):
    first = {"pid": 100, "commit": "a", "hashes": {}, "receipt_sha256": "x", "job_sha256": "y"}
    second = dict(first, pid=101)
    states = iter([first, second])
    monkeypatch.setattr(checker, "snapshot", lambda _id: next(states))
    monkeypatch.setattr(checker.subprocess, "run",
                        lambda *_a, **_kw: subprocess.CompletedProcess([], 0, "", ""))
    with pytest.raises(checker.RecoveryError, match="resume_modified_live_state"):
        checker.verify(ID)
