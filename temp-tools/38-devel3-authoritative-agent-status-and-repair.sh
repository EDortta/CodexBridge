#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(git rev-parse --show-toplevel)"
cd "$REPO_ROOT"

FRIDA="esteban@frida.inovacaosistemas.com.br"
FRIDA_PORT=2200
ENV_FILE="/etc/codex-bridge-agent/env"
OUT="temp-tools/results/$(date -u +%Y%m%d-%H%M%SZ)-authoritative-agent-status.txt"
mkdir -p temp-tools/results
exec > >(tee "$OUT") 2>&1

EXECUTOR_ID="$(sudo awk -F= '$1=="CODEX_BRIDGE_AGENT_EXECUTOR_ID"{print substr($0,index($0,"=")+1)}' "$ENV_FILE" | tail -n1)"
if [[ -z "$EXECUTOR_ID" ]]; then
  echo "ERROR: missing executor id"
  exit 2
fi

echo "== CodexBridge authoritative agent verification =="
echo "utc=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
echo "executor_id=$EXECUTOR_ID"

echo "== local agent service =="
sudo systemctl is-active codex-bridge-agent.service
sudo journalctl -u codex-bridge-agent.service --since '-3 minutes' --no-pager | tail -n 80 || true

echo "== authoritative gateway DB state =="
REMOTE_EXECUTOR_ID="$(printf '%q' "$EXECUTOR_ID")"
STATUS="$({ ssh -p "$FRIDA_PORT" "$FRIDA" "EXECUTOR_ID=$REMOTE_EXECUTOR_ID sudo -u codexbridge env CODEX_BRIDGE_DATABASE_URL=\$(sudo awk -F= '\$1==\"CODEX_BRIDGE_DATABASE_URL\"{print substr(\$0,index(\$0,\"=\")+1)}' /etc/codex-bridge/env | tail -n1) /bin/sh -c 'cd /tmp && exec /opt/codex-bridge/.venv/bin/python -'" <<'PY'
import asyncio
import os
import sys
sys.path.insert(0, "/opt/codex-bridge")
from gateway.app.db.session import SessionLocal
from gateway.app.models.entities import ExecutorModel, NodeModel

async def main():
    async with SessionLocal() as s:
        eid = os.environ["EXECUTOR_ID"]
        e = await s.get(ExecutorModel, eid)
        if e is None:
            print("executor_exists=no")
            return
        print("executor_exists=yes")
        print(f"executor_enabled={str(bool(e.enabled)).lower()}")
        print(f"executor_connected={str(bool(e.connected)).lower()}")
        print(f"executor_last_seen_at={e.last_seen_at}")
        print(f"executor_node_id={e.node_id}")
        if e.node_id:
            n = await s.get(NodeModel, e.node_id)
            if n is not None:
                print(f"node_enabled={str(bool(n.enabled)).lower()}")
                print(f"node_admission_state={n.admission_state}")
                print(f"node_health_reason={n.health_reason}")
asyncio.run(main())
PY
} 2>&1)"
printf '%s\n' "$STATUS"

if printf '%s\n' "$STATUS" | grep -q '^executor_connected=true$'; then
  echo "CODEXBRIDGE_AGENT_CONNECTED"
  rc=0
else
  echo "== gateway logs for rejected/failed agent handshake =="
  ssh -p "$FRIDA_PORT" "$FRIDA" "sudo journalctl -u codex-bridge-gateway.service --since '-5 minutes' --no-pager | grep -Ei 'agent|websocket|4401|4403|4404|executor' | tail -n 120 || true"
  echo "CODEXBRIDGE_AGENT_NOT_CONNECTED"
  rc=2
fi

git add "$OUT"
git commit -m "results: authoritative devel3 agent status" || true
git push origin development
exit "$rc"
