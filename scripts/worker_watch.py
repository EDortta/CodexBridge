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
import stat
import subprocess
import re
import sys
import time
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlsplit
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


def git_ssh_control(repository: str, branch: str, project: str) -> tuple[dict, dict]:
    """Read private or public control branch with SSH Git (no GitHub API token).

    Fetch a single control ref into a bare, worker-owned repository; never
    check out request content or execute any repository-supplied commands.
    """
    if not re.fullmatch(r"[A-Za-z0-9._-]+/[A-Za-z0-9._-]+", repository):
        raise ValueError("invalid GitHub repository")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._/-]{0,127}", branch):
        raise ValueError("invalid control branch")
    if branch in {"main", "master", "development"}:
        raise ValueError("code branch is not a control branch")
    store = Path(os.environ.get("CODEXBRIDGE_GIT_CACHE", str(Path(os.environ.get("XDG_STATE_HOME", str(Path.home() / ".local/state"))) / "codexbridge-worker/git-cache")))
    store.mkdir(mode=0o700, parents=True, exist_ok=True)
    cache = store / (repository.replace("/", "--") + ".git")
    if not cache.exists():
        subprocess.run(["git", "init", "--bare", "--quiet", str(cache)], check=True, timeout=20,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    def git(*args):
        result = subprocess.run(["git", "--git-dir", str(cache), *args], check=True,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=30)
        return result.stdout
    remote = "git@github.com:" + repository + ".git"
    git("-c", "core.sshCommand=ssh -o BatchMode=yes", "fetch", "--no-tags",
        "--depth=1", remote, "+refs/heads/" + branch + ":refs/codexbridge/control")
    requests = []
    envelopes = {}
    tree = git("ls-tree", "-r", "-z", "refs/codexbridge/control", "--", ".codexbridge/requests/")
    for item in tree.split(b"\\0"):
        if not item:
            continue
        meta, filename = item.split(b"\\t", 1)
        mode, kind, sha = meta.split(b" ")
        if kind != b"blob":
            continue
        name = filename.decode("utf-8").split("/")[-1]
        if not name.endswith(".json"):
            continue
        if "/" in filename.decode("utf-8")[len(".codexbridge/requests/"):]:
            raise ValueError("nested control request")
        body = git("cat-file", "blob", sha.decode())
        if len(body) > MAX_BODY:
            raise ValueError("request exceeds size limit")
        try:
            envelope = validate_envelope(json.loads(body), activated_project=project)
        except (ValueError, UnicodeDecodeError, InvalidControlRequest) as exc:
            raise ValueError("invalid control request") from exc
        if name != envelope["requestId"] + ".json":
            raise ValueError("request filename mismatch")
        requests.append({"name": name, "sha": sha.decode()})
        envelopes[sha.decode()] = envelope
    observation = {"project": project, "repository": repository, "branch": branch,
                   "request_count": len(requests), "requests": sorted(requests, key=lambda r: r["name"])}
    return observation, envelopes


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


def read_validated_requests(observation: dict, token: str | None, *, include_envelope: bool = False) -> list[dict]:
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
        entry = {"requestId": envelope["requestId"], "blobSha": sha}
        if include_envelope:
            entry["envelope"] = envelope
        accepted.append(entry)
    return accepted


def gateway_intake(gateway_url: str, worker_token: str, observation: dict,
                   envelope: dict) -> dict:
    """Forward data to Gateway for admission, never execute a local command."""
    parts = urlsplit(gateway_url)
    if (parts.scheme != "https" or not parts.hostname or parts.username
            or parts.password or parts.query or parts.fragment
            or parts.path not in {"", "/"}):
        raise ValueError("Gateway must be a bare HTTPS origin without userinfo")
    if not worker_token or len(worker_token) < 32:
        raise ValueError("missing Worker credential")
    payload = json.dumps({
        "repository": observation["repository"],
        "controlBranch": observation["branch"], "envelope": envelope,
    }, separators=(",", ":")).encode("utf-8")
    if len(payload) > MAX_BODY:
        raise ValueError("intake payload exceeds limit")
    url = gateway_url.rstrip("/") + "/control/worker-intake/requests"
    request = Request(url, data=payload, method="POST", headers={
        "Content-Type": "application/json",
        "Accept": "application/json",
        "X-Worker-Token": worker_token,
        "User-Agent": "codexbridge-worker/0",
    })
    with urlopen(request, timeout=15) as response:
        if response.status != 202:
            raise ValueError("unexpected Gateway intake status")
        result = response.read(MAX_BODY + 1)
    if len(result) > MAX_BODY:
        raise ValueError("Gateway response too large")
    value = json.loads(result)
    if (not isinstance(value, dict)
            or value.get("requestId") != envelope["requestId"]
            or value.get("projectId") != envelope["project"]
            or value.get("state") != "admitted"
            or type(value.get("created")) is not bool):
        raise ValueError("unexpected Gateway intake acknowledgement")
    return {"requestId": value["requestId"], "state": value["state"],
            "created": value["created"]}


def poll_once(state_file: Path, token: str | None) -> list[dict]:
    return [observe(project, repo, branch, token)
            for project, repo, branch in active_projects(state_file)]


def credential_env(name: str) -> str | None:
    """Prefer a root-provisioned credential file, never print its contents."""
    path = os.environ.get(name + "_FILE")
    if path:
        credential = Path(path)
        if not credential.is_file():
            raise ValueError("credential file missing")
        info = credential.stat()
        mode = stat.S_IMODE(info.st_mode)
        if (mode & 0o007) or (mode & 0o020) or (mode & 0o040 and info.st_gid != os.getegid()):
            raise ValueError("credential permissions must be owner-only or group-readable by worker")
        return credential.read_text(encoding="utf-8").strip()
    return os.environ.get(name)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state-file", type=Path, default=default_state_file())
    parser.add_argument("--interval", type=int, default=60)
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--forward-gateway", action="store_true", help="Submit validated requests to Gateway for admission only")
    parser.add_argument("--validate-requests", action="store_true", help="Read and validate blob content; never dispatch")
    args = parser.parse_args(argv)
    if not 15 <= args.interval <= 3600:
        parser.error("--interval must be between 15 and 3600 seconds")
    signal.signal(signal.SIGINT, _stop)
    signal.signal(signal.SIGTERM, _stop)
    try:
        token = None
        worker_token = credential_env("CODEXBRIDGE_WORKER_TOKEN") or ""
    except (OSError, ValueError) as exc:
        print(json.dumps({"status": "configuration_error", "error_type": type(exc).__name__}), file=sys.stderr)
        return 1
    gateway_url = os.environ.get("CODEXBRIDGE_GATEWAY_URL", "")
    if args.forward_gateway and (not gateway_url or len(worker_token) < 32):
        parser.error("Gateway HTTPS URL and Worker token must be configured in environment")
    try:
        while not STOP:
            try:
                for project, repository, branch in active_projects(args.state_file):
                    item, blobs = git_ssh_control(repository, branch, project)
                    # Only count/commit metadata. Never print request content or credentials.
                    if args.forward_gateway:
                        envelopes = [{"envelope": blobs[entry["sha"]]} for entry in item["requests"]]
                        item["gateway_admissions"] = [
                            gateway_intake(gateway_url, worker_token, item, request["envelope"])
                            for request in envelopes
                        ]
                    elif args.validate_requests:
                        item["validated_requests"] = [{"requestId": blobs[entry["sha"]]["requestId"], "blobSha": entry["sha"]} for entry in item["requests"]]
                    print(json.dumps(item, sort_keys=True), flush=True)
            except (WorkerctlError, HTTPError, URLError, ValueError, OSError, subprocess.SubprocessError) as exc:
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
