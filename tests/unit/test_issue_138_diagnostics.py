"""Issue #138 — deterministic administrative latency diagnostic contract."""
from __future__ import annotations

import importlib.util
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "diagnose_issue_138_admin.py"
spec = importlib.util.spec_from_file_location("issue138_admin_diagnostic", SCRIPT)
assert spec and spec.loader
diagnostic = importlib.util.module_from_spec(spec)
spec.loader.exec_module(diagnostic)


def test_credentials_use_existing_admin_ini_without_exposing_password(tmp_path: Path) -> None:
    ini = tmp_path / "credentials.ini"
    ini.write_text("CODEXBRIDGE_USER=operator\nPASSWORD=secret-value\n")
    assert diagnostic.read_credentials(ini) == ("operator", "secret-value")


def test_report_has_only_status_and_per_stage_timings(monkeypatch, tmp_path: Path) -> None:
    ini = tmp_path / "credentials.ini"
    ini.write_text("CODEXBRIDGE_USER=operator\nPASSWORD=secret-value\n")
    calls = []

    def fake_request(url, *, body=None, token=None):
        calls.append((url, body, token))
        if url.endswith("/sign-in"):
            return 200, {"accessToken": "secret-access", "refreshToken": "secret-refresh"}, 10.125, "password_verify;dur=9898.2, grant_persist;dur=122.3", "password_verify;dur=9000.0, grant_persist;dur=300.0"
        return 200, {"email": "sensitive@example.com"}, 0.221, "", ""

    monkeypatch.setattr(diagnostic, "request", fake_request)
    report = diagnostic.diagnose("https://gateway.example", ini)
    assert report == {
        "status": "pass",
        "sign_in": {"http_status": 200, "duration_seconds": 10.125, "server_timing": {"password_verify_ms": 9000.0, "grant_persist_ms": 300.0}},
        "me": {"http_status": 200, "duration_seconds": 0.221},
    }
    assert calls[1][2] == "secret-access"
    assert "secret-access" not in repr(report)
    assert "secret-refresh" not in repr(report)
    assert "sensitive@example.com" not in repr(report)
    assert "secret-value" not in repr(report)


def test_rejected_login_does_not_call_me(monkeypatch, tmp_path: Path) -> None:
    ini = tmp_path / "credentials.ini"
    ini.write_text("PASSWORD=secret\n")
    calls = []

    def reject(url, *, body=None, token=None):
        calls.append(url)
        return 401, {"detail": "invalid_credentials"}, 0.1, "", ""

    monkeypatch.setattr(diagnostic, "request", reject)
    report = diagnostic.diagnose("https://gateway.example", ini)
    assert report["status"] == "failed"
    assert report["me"]["status"] == "not_attempted"
    assert len(calls) == 1
