#!/usr/bin/env bash
# Gateway MVP verification. Evidence publication is deliberately best-effort:
# it must never mask the actual verification exit code.
set -Eeuo pipefail
cd "$(dirname "$0")/.."
started="$(date +%s)"
verification_status="failed"
verification_detail="Gateway MVP integration verification failed"
checks="not_run"
finish() {
  local rc="$?"
  trap - EXIT
  local envelope
  envelope="$(mktemp)"
  python3 - "$envelope" "$rc" "$started" "$verification_status" "$verification_detail" "$checks" <<'PY'
import json
import secrets
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

path, rc, started, status, detail, checks = sys.argv[1:]
now = datetime.now(timezone.utc)
commit = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True, check=True).stdout.strip()
branch = subprocess.run(["git", "branch", "--show-current"], capture_output=True, text=True, check=True).stdout.strip()
run = now.strftime("%H%M%S") + "-" + secrets.token_hex(4)
envelope = {
    "relative_path": f"CodexBridge/mvp-gateway-communication/{branch.replace('/', '-')}/{now:%Y-%m-%d}/{run}/manifest.json",
    "report": {
        "schema": 1,
        "project": "CodexBridge",
        "feature": "mvp-gateway-communication",
        "branch": branch,
        "commit": commit,
        "timestamp_utc": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "phase": "verification",
        "status": status,
        "exit_code": int(rc),
        "duration_seconds": int(time.time()) - int(started),
        "error_category": "none" if int(rc) == 0 else "verification",
        "checks": {"gateway_mvp_integration": checks},
        "detail": detail,
    },
}
Path(path).write_text(json.dumps(envelope, ensure_ascii=False, indent=2) + "\n")
PY
  publisher="${DEVELOPMENT_EVIDENCES_ROOT:-$HOME/.local/state/development-evidences/repo}/publisher.py"
  if [[ -f "$publisher" ]]; then
    python3 "$publisher" enqueue --file "$envelope" || true
    python3 "$publisher" flush || true
  else
    printf 'Evidence publisher unavailable: %s\n' "$publisher" >&2
  fi
  rm -f "$envelope"
  exit "$rc"
}
trap finish EXIT

python3 -m pytest -q \
  tests/integration/test_agent_hub.py \
  tests/integration/test_agent_ack_handling.py \
  tests/integration/test_agent_ws_handshake.py \
  tests/integration/test_agent_ws_identity.py \
  tests/integration/test_reconnect_replay_resolves.py \
  tests/integration/test_store_and_mcp.py \
  tests/integration/test_smoke.py
checks="passed"
verification_status="success"
verification_detail="Gateway MVP integration test selection passed"
