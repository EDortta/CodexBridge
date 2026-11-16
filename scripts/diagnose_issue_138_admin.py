#!/usr/bin/env python3
"""Issue #138: instrument administrative sign-in and /me without leaking tokens.

The existing admin shell helper uses one sign-in and one /me call. Reproduce
those stages with the same credentials, reporting only status and timings.
No token/password is printed, persisted, or transmitted to the evidence repo.
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
import sys
from time import monotonic
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

DEFAULT_BASE = "https://codexbridge.inovacaosistemas.com.br"
TIMEOUT_SECONDS = 25


def read_credentials(path: Path) -> tuple[str, str]:
    if not path.is_file():
        raise ValueError("credentials_file_missing")
    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.lstrip().startswith(("#", ";")):
            key, value = line.split("=", 1)
            values[key.strip()] = value.strip()
    username = values.get("CODEXBRIDGE_USER") or "esteban"
    password = values.get("CODEXBRIDGE_PASSWORD") or values.get("PASSWORD")
    if not password:
        raise ValueError("password_missing")
    return username, password


def request(url: str, *, body: bytes | None = None, token: str | None = None) -> tuple[int, dict, float, str]:
    headers = {"Accept": "application/json"}
    if body is not None:
        headers["Content-Type"] = "application/json"
    if token is not None:
        headers["Authorization"] = "Bearer " + token
    started = monotonic()
    req = Request(url, data=body, headers=headers, method="POST" if body is not None else "GET")
    try:
        with urlopen(req, timeout=TIMEOUT_SECONDS) as response:
            status = response.status
            server_timing = response.headers.get("Server-Timing", "")
            payload = response.read(1024 * 1024)
    except HTTPError as exc:
        status = exc.code
        server_timing = exc.headers.get("Server-Timing", "")
        payload = exc.read(1024 * 1024)
    elapsed = round(monotonic() - started, 3)
    try:
        document = json.loads(payload)
        if not isinstance(document, dict):
            document = {}
    except (ValueError, UnicodeDecodeError):
        document = {}
    return status, document, elapsed, server_timing


def diagnose(base: str, credential_file: Path) -> dict:
    username, password = read_credentials(credential_file)
    try:
        status, response, seconds, timings = request(
            base + "/api/v1/auth/sign-in",
            body=json.dumps({"username": username, "password": password}).encode("utf-8"),
        )
    finally:
        del password
    report: dict = {"sign_in": {"http_status": status, "duration_seconds": seconds}}
    # Whitelist numeric durations only. Unknown or malformed timing headers
    # are discarded instead of being published or logged.
    measured = {}
    for phase in ("password_verify", "grant_persist"):
        match = re.search(r"(?:^|,)\\s*" + phase + r";dur=([0-9]+(?:\\.[0-9]+)?)\\s*(?:,|$)", timings)
        if match:
            measured[phase + "_ms"] = float(match.group(1))
    if measured:
        report["sign_in"]["server_timing"] = measured
    token = response.get("accessToken")
    if status != 200 or not isinstance(token, str) or not token:
        report["me"] = {"status": "not_attempted"}
        report["status"] = "failed"
        return report
    try:
        me_status, _, me_seconds, _ = request(base + "/api/v1/auth/me", token=token)
    finally:
        del token, response
    report["me"] = {"http_status": me_status, "duration_seconds": me_seconds}
    report["status"] = "pass" if me_status == 200 else "failed"
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--credentials", required=True, type=Path)
    parser.add_argument("--base-url", default=DEFAULT_BASE)
    args = parser.parse_args()
    if not args.base_url.startswith("https://") or any(x in args.base_url for x in ("?", "#", "\n", " ")):
        parser.error("base-url must be HTTPS without query")
    try:
        report = diagnose(args.base_url.rstrip("/"), args.credentials)
    except (ValueError, OSError, URLError, TimeoutError):
        report = {"status": "failed", "error_category": "credential_or_transport"}
    print(json.dumps(report, sort_keys=True))
    return 0 if report["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
