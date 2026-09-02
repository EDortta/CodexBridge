#!/usr/bin/env python3
"""Redeem a node-enrollment invite and save the machine token locally.

Run explicitly, by whoever is standing up a new CodexBridge installation,
with the invite token an operator issued from the gateway's own admin
surface (`POST /api/v1/nodes/invite`) and handed over out of band:

    python3 scripts/enroll_node.py --gateway-url https://codexbridge.example.com:8443 \\
        --invite-token <colado do painel> --display-name devel3

Issue #76 (minimal cut): this is the other half of "adopt a new CodexBridge
server from the panel, without editing a file and without restarting
anything". Before it existed, admitting a machine meant hand-editing
`registry.json` with an invented clear-text token and restarting the
gateway. This script instead calls `POST /api/v1/nodes/enroll` -- gated by
the invite, not by any credential of its own, since the machine has none
yet -- and writes the `machineToken` the gateway mints straight to a local
file with `0600` permissions.

Nothing about `AgentSettings.machine_token` changes for an operator who does
not use this script: it stays the default fallback. Setting
`CODEX_BRIDGE_AGENT_MACHINE_TOKEN_FILE` to the file this script writes is
what makes the agent prefer it (`agent/codex_bridge_agent/config.py:
resolve_machine_token`).

This script makes exactly one network call and one file write. It does not
start the agent, does not touch `.env`, and does not restart anything --
the operator wires `--machine-token-file` (or its `CODEX_BRIDGE_AGENT_
MACHINE_TOKEN_FILE` equivalent) and the node's `executor_id` into the agent's
own configuration as a separate, deliberate step, and starts the agent
themselves.
"""

from __future__ import annotations

import argparse
import json
import os
import stat
import sys
from pathlib import Path

import httpx

DEFAULT_MACHINE_TOKEN_FILE = str(Path("~/.config/codex-bridge-agent/machine-token").expanduser())


def enroll(gateway_url: str, invite_token: str, display_name: str, *, timeout: float) -> dict:
    """Call `POST /api/v1/nodes/enroll`. Returns the parsed JSON body.

    Raises `httpx.HTTPStatusError` on a non-2xx response -- the invite may be
    unknown, already consumed, or expired, and the gateway reports all three
    identically (`400 validation_failed`) on purpose (see
    `gateway/app/api/routes/enrollment.py`), so this script does not try to
    tell them apart either.
    """
    url = gateway_url.rstrip("/") + "/api/v1/nodes/enroll"
    response = httpx.post(
        url,
        json={"inviteToken": invite_token, "displayName": display_name},
        timeout=timeout,
    )
    response.raise_for_status()
    return response.json()


def write_machine_token(path: Path, token: str) -> None:
    """Write `token` to `path` with `0600` permissions, creating parent dirs.

    Permissions are set BEFORE the content is written (`os.open` with the
    mode, not a `chmod` after `write_text`), so there is no window where the
    file exists world-readable. Same discipline
    `gateway/app/services/notify.py` requires of the files it reads, applied
    here on the writing side.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, stat.S_IRUSR | stat.S_IWUSR)
    # `os.fdopen` as a context manager closes `fd` on the way out, on the
    # success path and on any exception alike -- nothing further to clean up
    # here.
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        handle.write(token)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--gateway-url", required=True, help="Base URL of the gateway, e.g. https://host:8443")
    parser.add_argument("--invite-token", required=True, help="Bearer invite token issued by POST /api/v1/nodes/invite")
    parser.add_argument("--display-name", required=True, help="Human-readable label for this node")
    parser.add_argument(
        "--machine-token-file",
        default=DEFAULT_MACHINE_TOKEN_FILE,
        help=f"Where to write the machine token (default: {DEFAULT_MACHINE_TOKEN_FILE})",
    )
    parser.add_argument("--timeout", type=float, default=15.0, help="HTTP timeout in seconds (default: 15)")
    args = parser.parse_args(argv)

    try:
        result = enroll(args.gateway_url, args.invite_token, args.display_name, timeout=args.timeout)
    except httpx.HTTPStatusError as exc:
        detail = exc.response.text
        try:
            detail = json.loads(detail).get("message", detail)
        except (json.JSONDecodeError, AttributeError):
            pass
        print(f"error: enrollment refused ({exc.response.status_code}): {detail}", file=sys.stderr)
        return 1
    except httpx.HTTPError as exc:
        print(f"error: could not reach {args.gateway_url}: {exc}", file=sys.stderr)
        return 1

    machine_token = result["machineToken"]
    node_id = result["nodeId"]
    token_path = Path(args.machine_token_file).expanduser()
    write_machine_token(token_path, machine_token)

    print(f"Enrolled node {node_id!r} ({result.get('displayName', args.display_name)!r}).")
    print(f"Machine token written to {token_path} (0600).")
    print()
    print("Next: point the agent at this node. In its .env (or environment):")
    print(f"  CODEX_BRIDGE_AGENT_EXECUTOR_ID={node_id}")
    print(f"  CODEX_BRIDGE_AGENT_MACHINE_TOKEN_FILE={token_path}")
    print(f"  CODEX_BRIDGE_AGENT_GATEWAY_WS_URL=<wss:// form of {args.gateway_url}>/agent/ws")
    print("Nothing here starts the agent -- that remains a separate, deliberate step.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
