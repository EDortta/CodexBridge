#!/usr/bin/env python3
"""Read-only GitHub control-branch observer for explicitly activated projects.

Stage 2 transport probe: no dispatch, shell, worktree checkout or result writes.
A GitHub JSON request is untrusted input, never an authorization grant.
"""
from __future__ import annotations

import argparse
import base64
import binascii
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import signal
import sys
import time
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

from worker_request import InvalidControlRequest, validate_envelope
from workerctl import (
    WorkerctlError, _locked_file, _read_state, _status, default_state_file,
)

MAX_BODY = 64 * 1024
STOP = False


def _stop(*_args: object) -> None:
    global STOP
    STOP = True


def github_json(path: str, token: str | None) -> object:
    headers = {"Accept": "application/vnd.github+json", "User-Agent": "codexbridge-worker/0"}
    if token:
        headers["Authorization"] = "Bearer " + token
    request = Request("https://api.github.com/" + path, headers=headers)
    with urlopen(request, timeout=15) as response:
        data = response.read(MAX_BODY + 1)
    if len(data) > MAX_BODY:
        raise ValueError("GitHub response too large")
    return json.loads(data)


def active_projects(state_file: Path) -> list[tuple[str, str, str]]:
    with _locked_file(state_file):
        state = _read_state(state_file)
    now = datetime.now(timezone.utc)
    result = []
    for project, entry in state["projects"].items():
        if _status(state["activations"].get(project), now) == "active":
            result.append((project, entry["repository"], entry["control_branch"]))
    return result


def observe(project: str, repository: str, branch: str, token: str | None) -> dict:
    owner, repo = repository.split("/")
    # A dedicated control branch, not the development branch.
    if branch in {"main", "master", "development"}:
        raise ValueError("refusing to observe a code branch as control branch")
    base = "repos/" + quote(owner, safe="") + "/" + quote(repo, safe="")
    path = ".codexbridge/requests"
    listing = github_json(base + "/contents/" + path + "?ref=" + quote(branch, safe=""), token)
    if not isinstance(listing, list):
        raise ValueError("control requests folder is not a directory")
    requests = []
    for item in listing:
        if not isinstance(item, dict):
            raise ValueError("unexpected GitHub directory entry")
        name, typ, sha, size = item.get("name"), item.get("type"), item.get("sha"), item.get("size")
        if typ != "file" or not isinstance(name, str) or not name.endswith(".json"):
            continue
        if not isinstance(sha, str) or len(sha) != 40 or not isinstance(size, int) or size > MAX_BODY:
            raise ValueError("unsafe request metadata")
        requests.append({"name": name, "sha": sha})
    return {"project": project, "repository": repository, "branch": branch,
            "request_count": len(requests), "requests": sorted(requests, key=lambda r: r["name"])}


def read_validated_requests(observation: dict, token: str | None) -> list[dict]:
    """Read blobs by immutable Git SHA, never by a moving branch reference.

    Returns only safe IDs and hashes for diagnostic output, not request bodies.
    Nothing is submitted or executed here. A future Gateway submitter must
    authenticate independently and supply the verified envelope.
    """
    repository = observation["repository"]
    project = observation["project"]
    owner, repo = repository.split("/")
    prefix = "repos/" + quote(owner, safe="") + "/" + quote(repo, safe="")
    accepted = []
    for item in observation["requests"]:
        name, sha = item["name"], item["sha"]
        if not isinstance(name, str) or not isinstance(sha, str):
            raise ValueError("unexpected request metadata")
        blob = github_json(prefix + "/git/blobs/" + quote(sha, safe=""), token)
        if not isinstance(blob, dict) or blob.get("encoding") != "base64":
            raise ValueError("invalid GitHub blob response")
        encoded = blob.get("content")
        if not isinstance(encoded, str):
            raise ValueError("missing blob content")
        try:
            body = base64.b64decode(encoded, validate=False)
        except (ValueError, binascii.Error) as exc:
            raise ValueError("malformed GitHub blob") from exc
        if len(body) > MAX_BODY:
            raise ValueError("request blob exceeds size limit")
        try:
            envelope = validate_envelope(json.loads(body), activated_project=project)
        except (UnicodeDecodeError, json.JSONDecodeError, InvalidControlRequest) as exc:
            raise ValueError("invalid control request") from exc
        if name != envelope["requestId"] + ".json":
            raise ValueError("request filename does not match immutable ID")
        accepted.append({"requestId": envelope["requestId"], "blobSha": sha})
    return accepted


def poll_once(state_file: Path, token: str | None) -> list[dict]:
    return [observe(project, repo, branch, token)
            for project, repo, branch in active_projects(state_file)]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state-file", type=Path, default=default_state_file())
    parser.add_argument("--interval", type=int, default=60)
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--validate-requests", action="store_true", help="Read and validate blob content; never dispatch")
    args = parser.parse_args(argv)
    if not 15 <= args.interval <= 3600:
        parser.error("--interval must be between 15 and 3600 seconds")
    signal.signal(signal.SIGINT, _stop)
    signal.signal(signal.SIGTERM, _stop)
    token = os.environ.get("CODEXBRIDGE_GITHUB_TOKEN")
    try:
        while not STOP:
            try:
                for item in poll_once(args.state_file, token):
                    # Only count/commit metadata. Never print request content or credentials.
                    if args.validate_requests:
                        item["validated_requests"] = read_validated_requests(item, token)
                    print(json.dumps(item, sort_keys=True), flush=True)
            except (WorkerctlError, HTTPError, URLError, ValueError, OSError) as exc:
                print(json.dumps({"status": "poll_error", "error_type": type(exc).__name__}),
                      file=sys.stderr, flush=True)
                if args.once:
                    return 1
            if args.once:
                break
            for _ in range(args.interval):
                if STOP:
                    break
                time.sleep(1)
        return 0
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
