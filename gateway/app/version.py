"""The single statement of this application's version.

There were four independent copies — `pyproject.toml`, the settings default, the
`FastAPI(version=...)` argument and the MCP `serverInfo` — and `new-tag.sh`
updated none of them. `GET /api/version` exists so a client can tell what the
server is; with the copies drifting, the one field naming the build reports
whatever was hand-typed last.

`tests/unit/test_version_is_single_sourced.py` binds every copy to this constant
and to `pyproject.toml`, so a release that moves one and not the others is a red
test rather than a wrong answer to a client.

This is the *application* version. The API **contract** version is separate and
lives in `gateway/app/api/routes/probes.py:API_CONTRACT_VERSION`; the two move
for different reasons.
"""

from __future__ import annotations


APP_VERSION = "0.1.0"
