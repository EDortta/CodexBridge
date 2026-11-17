"""Issue #138: fail closed on incomplete or malformed remote baseline reports."""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

PATH = Path(__file__).resolve().parents[2] / "scripts/run_issue_138_baseline_evidence.py"
spec = importlib.util.spec_from_file_location("issue138_baseline_evidence", PATH)
assert spec and spec.loader
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def report() -> str:
    sha = "a" * 64
    lines = ["REMOTE_BASELINE_DIAGNOSTIC=read_only"]
    for name in module.EXPECTED:
        lines.extend([
            f"FILE={name}",
            f"REMOTE_SHA256={sha}",
            f"DEVELOPMENT_SHA256={sha}",
            f"PATCH_SHA256={sha}",
            "STATUS=matches_development",
            "",
        ])
    lines.append("LIVE_FILES_UNCHANGED=1")
    return "\n".join(lines)


def test_complete_report_parses_only_known_fields() -> None:
    parsed = module.parse_diagnostic(report())
    assert set(parsed) == set(module.EXPECTED)
    for item in parsed.values():
        assert item["classification"] == "matches_development"
        assert item["remote_sha256"] == "a" * 64


def test_diagnostic_missing_file_is_rejected() -> None:
    text = report().replace(
        "FILE=gateway/app/main.py", "FILE=invalid.py"
    )
    with pytest.raises(ValueError):
        module.parse_diagnostic(text)


def test_incomplete_or_invalid_hash_is_rejected() -> None:
    with pytest.raises(ValueError):
        module.parse_diagnostic(report().replace("REMOTE_SHA256=" + "a" * 64, "REMOTE_SHA256=bad", 1))
    with pytest.raises(ValueError):
        module.parse_diagnostic(report().replace("LIVE_FILES_UNCHANGED=1", ""))


def test_historical_version_requires_commit_id() -> None:
    text = report().replace("STATUS=matches_development", "STATUS=historical_git_version", 1)
    with pytest.raises(ValueError):
        module.parse_diagnostic(text)
    text = text.replace("STATUS=historical_git_version", "STATUS=historical_git_version\nMATCHED_COMMIT=" + "b" * 40)
    assert module.parse_diagnostic(text)["gateway/app/main.py"]["matched_commit"] == "b" * 40
