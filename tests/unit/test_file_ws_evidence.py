"""Evidence harness must preserve failures and retain provenance even on errors."""
import json
import sys

from scripts.run_file_ws_evidence import run_evidenced


def test_failure_retains_manifest_and_original_exit_code(tmp_path):
    rc, report, folder = run_evidenced(
        [sys.executable, "-c", "print('FAILED tests/unit/test_dummy.py::test_failure'); raise SystemExit(7)"],
        feature="file-instruction-ws-bridge", timeout=5,
        state_root=tmp_path, publisher=None,
    )
    assert rc == 7
    assert report["status"] == "failed"
    assert report["exit_code"] == 7
    assert report["checks"]["failed_test_ids"] == ["tests/unit/test_dummy.py::test_failure"]
    assert (folder / "execution.log").is_file()
    assert json.loads((folder / "manifest.json").read_text())["exit_code"] == 7
    assert json.loads((folder / "publisher-envelope.json").read_text())["report"]["status"] == "failed"


def test_success_also_retains_manifest(tmp_path):
    rc, report, folder = run_evidenced(
        [sys.executable, "-c", "print('1 passed'); raise SystemExit(0)"],
        feature="file-instruction-ws-bridge", timeout=5,
        state_root=tmp_path, publisher=None,
    )
    assert rc == 0
    assert report["status"] == "success"
    assert report["checks"]["counts"]["passed"] == 1
    assert (folder / "publication.json").is_file()


def test_timeout_records_failure_evidence(tmp_path):
    rc, report, folder = run_evidenced(
        [sys.executable, "-c", "import time;time.sleep(10)"],
        feature="file-instruction-ws-bridge", timeout=1,
        state_root=tmp_path, publisher=None,
    )
    assert rc == 124
    assert report["error_category"] == "timeout"
    assert json.loads((folder / "manifest.json").read_text())["status"] == "failed"
