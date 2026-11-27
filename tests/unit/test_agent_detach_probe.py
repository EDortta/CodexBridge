"""No-systemd regressions for the safe detached Agent worker drill."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts import probe_agent_detached_worker as probe


def test_private_probe_worker_writes_receipt(tmp_path, monkeypatch):
    monkeypatch.setattr(probe, "ROOT", tmp_path)
    stage = tmp_path / "probe-test"
    stage.mkdir(mode=0o700)
    monkeypatch.setattr(probe.time, "sleep", lambda *_a: None)
    probe.probe_worker(stage)
    receipt = json.loads((stage / "worker-receipt.json").read_text())
    assert receipt == {"schema": 1, "id": "probe-test",
                       "result": "detached_completed"}


def test_worker_refuses_repeated_receipt(tmp_path, monkeypatch):
    monkeypatch.setattr(probe, "ROOT", tmp_path)
    stage = tmp_path / "probe-test"
    stage.mkdir(mode=0o700)
    (stage / "worker-receipt.json").write_text("{}")
    with pytest.raises(probe.ProbeError, match="receipt_already_exists"):
        probe.probe_worker(stage)


def test_worker_refuses_arbitrary_stage(tmp_path, monkeypatch):
    monkeypatch.setattr(probe, "ROOT", tmp_path / "state")
    outside = tmp_path / "other"
    outside.mkdir(mode=0o700)
    with pytest.raises(probe.ProbeError, match="unexpected_stage"):
        probe.probe_worker(outside)


def test_client_start_failure_does_not_ack(tmp_path, monkeypatch):
    monkeypatch.setattr(probe, "ROOT", tmp_path)
    stage = tmp_path / "probe-test"
    stage.mkdir(mode=0o700)
    class Failure:
        returncode = 1
    monkeypatch.setattr(probe.subprocess, "run", lambda *_a, **_kw: Failure())
    with pytest.raises(probe.ProbeError, match="systemd_run_failed"):
        probe.probe_client(stage)
    assert not (stage / "client-started.json").exists()
