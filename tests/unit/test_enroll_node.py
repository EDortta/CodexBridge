"""`scripts/enroll_node.py` -- one HTTP call, one file write, issue #76.

Loaded the same way `tests/unit/test_register_projects.py` loads its script:
`importlib` against the file directly, so this test exercises exactly the
same module `python3 scripts/enroll_node.py` runs, not a reimplementation of
it. `httpx.post` is monkeypatched rather than hitting a real server -- this
script's own job is the HTTP call and the file write, not re-testing the
gateway's `/api/v1/nodes/enroll` handler (that lives in
`tests/integration/test_enrollment.py`).
"""

from __future__ import annotations

import importlib.util
import json
import stat
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "enroll_node.py"

spec = importlib.util.spec_from_file_location("enroll_node", SCRIPT)
enroll_node = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = enroll_node
spec.loader.exec_module(enroll_node)


class _FakeResponse:
    def __init__(self, status_code: int, payload: dict):
        self.status_code = status_code
        self._payload = payload
        self.text = json.dumps(payload)

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            import httpx

            raise httpx.HTTPStatusError("error", request=None, response=self)

    def json(self) -> dict:
        return self._payload


def test_write_machine_token_creates_the_file_with_0600(tmp_path: Path) -> None:
    target = tmp_path / "nested" / "machine-token"

    enroll_node.write_machine_token(target, "the-raw-token")

    assert target.read_text(encoding="utf-8") == "the-raw-token"
    mode = target.stat().st_mode
    assert stat.S_IMODE(mode) == 0o600


def test_write_machine_token_overwrites_an_existing_file(tmp_path: Path) -> None:
    target = tmp_path / "machine-token"
    target.write_text("stale", encoding="utf-8")

    enroll_node.write_machine_token(target, "fresh")

    assert target.read_text(encoding="utf-8") == "fresh"


def test_main_enrolls_and_writes_the_token(tmp_path: Path, monkeypatch) -> None:
    captured = {}

    def fake_post(url, *, json, timeout):
        captured["url"] = url
        captured["json"] = json
        return _FakeResponse(201, {"nodeId": "n-123", "displayName": "devel3", "machineToken": "raw-machine-token"})

    monkeypatch.setattr(enroll_node.httpx, "post", fake_post)
    token_file = tmp_path / "machine-token"

    exit_code = enroll_node.main(
        [
            "--gateway-url", "https://gateway.example.com:8443",
            "--invite-token", "raw-invite-token",
            "--display-name", "devel3",
            "--machine-token-file", str(token_file),
        ]
    )

    assert exit_code == 0
    assert captured["url"] == "https://gateway.example.com:8443/api/v1/nodes/enroll"
    assert captured["json"] == {"inviteToken": "raw-invite-token", "displayName": "devel3"}
    assert token_file.read_text(encoding="utf-8") == "raw-machine-token"
    assert stat.S_IMODE(token_file.stat().st_mode) == 0o600


def test_main_reports_a_refused_invite_and_writes_nothing(tmp_path: Path, monkeypatch) -> None:
    def fake_post(url, *, json, timeout):
        return _FakeResponse(400, {"code": "validation_failed", "message": "This invite token is invalid, expired, or already used."})

    monkeypatch.setattr(enroll_node.httpx, "post", fake_post)
    token_file = tmp_path / "machine-token"

    exit_code = enroll_node.main(
        [
            "--gateway-url", "https://gateway.example.com:8443",
            "--invite-token", "bad-token",
            "--display-name", "devel3",
            "--machine-token-file", str(token_file),
        ]
    )

    assert exit_code == 1
    assert not token_file.exists()


def test_main_strips_a_trailing_slash_from_the_gateway_url(monkeypatch, tmp_path: Path) -> None:
    captured = {}

    def fake_post(url, *, json, timeout):
        captured["url"] = url
        return _FakeResponse(201, {"nodeId": "n-1", "displayName": "d", "machineToken": "t"})

    monkeypatch.setattr(enroll_node.httpx, "post", fake_post)

    enroll_node.main(
        [
            "--gateway-url", "https://gateway.example.com:8443/",
            "--invite-token", "x",
            "--display-name", "d",
            "--machine-token-file", str(tmp_path / "t"),
        ]
    )

    assert captured["url"] == "https://gateway.example.com:8443/api/v1/nodes/enroll"
