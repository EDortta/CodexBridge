"""Deployment validation evidence must fail closed and never publish raw logs."""
from pathlib import Path
from unittest.mock import patch
import importlib.util
import subprocess

SCRIPT = Path(__file__).resolve().parents[2] / "scripts/run_deploy_test_with_evidence.py"
spec = importlib.util.spec_from_file_location("deploy_evidence", SCRIPT)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def test_successful_local_validation_requires_publication(tmp_path):
    log = tmp_path / "test.log"
    code, duration = module.run_validation(
        ["python3", "-c", "print('local log only')"], log_path=log
    )
    assert code == 0 and duration >= 0
    assert "local log only" in log.read_text()
    assert log.stat().st_mode & 0o077 == 0


def test_failure_is_not_turned_into_success(tmp_path):
    code, _ = module.run_validation(
        ["python3", "-c", "raise SystemExit(7)"], log_path=tmp_path / "err.log"
    )
    assert code == 7


def test_publisher_absence_blocks(tmp_path):
    assert not module.publish({"status": "pass"}, "x/manifest.json",
                              publisher=tmp_path / "missing.py")


def test_publisher_requires_remote_ack(tmp_path):
    publisher = tmp_path / "publisher.py"
    publisher.write_text("pass")
    with patch.object(module.subprocess, "run", side_effect=[
        subprocess.CompletedProcess([], 0, "queued=1\n", ""),
        subprocess.CompletedProcess([], 0, "processed=0\n", ""),
    ]):
        assert not module.publish({"status": "pass"}, "x/manifest.json",
                                  publisher=publisher)


def test_publisher_accepts_exact_remote_ack(tmp_path):
    publisher = tmp_path / "publisher.py"
    publisher.write_text("pass")
    with patch.object(module.subprocess, "run", side_effect=[
        subprocess.CompletedProcess([], 0, "queued=1\n", ""),
        subprocess.CompletedProcess([], 0, "published=x/manifest.json\nprocessed=1\n", ""),
    ]):
        assert module.publish({"status": "pass"}, "x/manifest.json",
                              publisher=publisher)


def test_publisher_rejects_push_failure(tmp_path):
    publisher = tmp_path / "publisher.py"
    publisher.write_text("pass")
    with patch.object(module.subprocess, "run", side_effect=[
        subprocess.CompletedProcess([], 0, "queued=1\n", ""),
        subprocess.CompletedProcess([], 1, "", "push rejected"),
    ]):
        assert not module.publish({"status": "pass"}, "x/manifest.json",
                                  publisher=publisher)
