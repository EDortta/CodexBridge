"""Issue #138 staging evidence rejects incomplete or ambiguous stage output."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
from run_issue_138_stage_evidence import parse_stage_output


def test_stage_output_reports_single_release_and_commit() -> None:
    result = parse_stage_output(
        "STAGED_ONLY=issue138-20261117T120000Z\n"
        "SOURCE_COMMIT=" + "a" * 40 + "\n"
        "APPLY_NOT_EXECUTED=1\n"
    )
    assert result == ("issue138-20261117T120000Z", "a" * 40)


@pytest.mark.parametrize("text", [
    "",
    "STAGED_ONLY=issue138-20261117T120000Z\n",
    "STAGED_ONLY=issue138-20261117T120000Z\nSOURCE_COMMIT=" + "a" * 40,
    "STAGED_ONLY=issue138-20261117T120000Z\n"
    "STAGED_ONLY=issue138-20261117T120001Z\n"
    "SOURCE_COMMIT=" + "a" * 40 + "\nAPPLY_NOT_EXECUTED=1",
])
def test_stage_output_refuses_missing_or_multiple_provenance(text: str) -> None:
    with pytest.raises(ValueError):
        parse_stage_output(text)
