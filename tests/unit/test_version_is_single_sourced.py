"""Every statement of the application version must be the same statement.

There were four independent copies — `pyproject.toml`, the settings default,
`FastAPI(version=...)` and the MCP `serverInfo` — and `new-tag.sh` updated none
of them. `GET /api/version` exists so a client can tell what the server is; four
hand-maintained copies mean the field naming the build reports whatever was typed
last, and no release had yet exercised it.
"""

from __future__ import annotations

import re
from pathlib import Path

from gateway.app.core.config import settings
from gateway.app.main import app
from gateway.app.version import APP_VERSION


REPO_ROOT = Path(__file__).resolve().parents[2]


def _pyproject_version() -> str:
    text = (REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    match = re.search(r'^version\s*=\s*"([^"]+)"', text, re.MULTILINE)
    assert match, "pyproject.toml declares no version"
    return match.group(1)


def test_pyproject_and_code_agree() -> None:
    assert _pyproject_version() == APP_VERSION, (
        "pyproject.toml and gateway/app/version.py disagree; a release must move both"
    )


def test_settings_reports_the_single_source() -> None:
    assert settings.app_version == APP_VERSION


def test_fastapi_application_reports_the_single_source() -> None:
    assert app.version == APP_VERSION


def test_mcp_server_info_reports_the_single_source() -> None:
    """The MCP client sees this one; it drifted independently of the HTTP API."""
    source = (REPO_ROOT / "gateway" / "app" / "mcp" / "server.py").read_text(encoding="utf-8")
    assert '"version": APP_VERSION' in source
    assert '"version": "0.' not in source, "a literal version crept back into serverInfo"


def test_no_stray_version_literals_in_the_gateway() -> None:
    """A new hardcoded copy is how the previous four accumulated."""
    offenders = []
    for path in (REPO_ROOT / "gateway").rglob("*.py"):
        if path.name == "version.py" or "__pycache__" in str(path):
            continue
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if re.search(r'version\s*[=:]\s*["\']\d+\.\d+\.\d+["\']', line):
                offenders.append(f"{path.relative_to(REPO_ROOT)}:{number}: {line.strip()}")
    assert not offenders, (
        "hardcoded version literals — import APP_VERSION instead:\n" + "\n".join(offenders)
    )
