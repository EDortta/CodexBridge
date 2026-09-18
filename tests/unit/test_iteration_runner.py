from __future__ import annotations

import datetime as dt
import importlib.util
import json
from pathlib import Path
import sys

MODULE_PATH = Path(__file__).resolve().parents[2] / "tools" / "iteration_runner.py"
SPEC = importlib.util.spec_from_file_location("iteration_runner", MODULE_PATH)
assert SPEC and SPEC.loader
runner = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = runner
SPEC.loader.exec_module(runner)


def write_manifest(tmp_path: Path, **overrides):
    data = {
        "enabled": True,
        "run_id": "oauth-login",
        "project": "CodexBridge",
        "round": 2,
        "max_rounds": 8,
        "deadline": "2026-09-19T03:00:00-03:00",
        "branch": "development",
        "script": "temp-tools/test.sh",
        "args": [],
        "timeout_seconds": 120,
        "status": "ready",
        "ready_revision": None,
    }
    data.update(overrides)
    path = tmp_path / "iteration.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def test_manifest_parses_timezone_and_round(tmp_path):
    manifest = runner.Manifest.load(write_manifest(tmp_path))
    assert manifest.run_id == "oauth-login"
    assert manifest.round == 2
    assert manifest.deadline.tzinfo is not None
    assert manifest.deadline.astimezone(dt.timezone.utc).hour == 6


def test_manifest_requires_timezone(tmp_path):
    path = write_manifest(tmp_path, deadline="2026-09-19T03:00:00")
    try:
        runner.Manifest.load(path)
    except runner.RunnerError as exc:
        assert "timezone" in str(exc)
    else:
        raise AssertionError("naive deadline must be refused")


def test_manifest_refuses_unsafe_run_id(tmp_path):
    path = write_manifest(tmp_path, run_id="../escape")
    try:
        runner.Manifest.load(path)
    except runner.RunnerError as exc:
        assert "unsafe" in str(exc)
    else:
        raise AssertionError("unsafe run_id must be refused")


def test_result_name_is_unique_by_run_and_round(tmp_path):
    manifest = runner.Manifest.load(write_manifest(tmp_path, round=7))
    path = runner.result_json_path(tmp_path, manifest)
    assert path == tmp_path / "iteration-results/oauth-login/round-007.json"


def test_safe_script_refuses_path_escape(tmp_path):
    outside = tmp_path.parent / "outside.sh"
    outside.write_text("#!/bin/sh\n", encoding="utf-8")
    try:
        runner.safe_script(tmp_path, "../outside.sh")
    except runner.RunnerError as exc:
        assert "escapes" in str(exc)
    else:
        raise AssertionError("path traversal must be refused")
