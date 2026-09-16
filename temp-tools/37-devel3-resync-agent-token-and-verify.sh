#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(git rev-parse --show-toplevel)"
cd "$REPO_ROOT"

FRIDA="esteban@frida.inovacaosistemas.com.br"
FRIDA_PORT=2200
ENV_FILE="/etc/codex-bridge-agent/env"
OUT="temp-tools/results/$(date -u +%Y%m%d-%H%M%SZ)-resync-agent-token.txt"
mkdir -p temp-tools/results
exec > >(tee "$OUT") 2>&1

echo "== CodexBridge agent credential resync =="
echo "utc=$(date -u +%Y-%m-%dT%H:%M:%SZ)"

EXECUTOR_ID="$(sudo awk -F= '$1=="CODEX_BRIDGE_AGENT_EXECUTOR_ID"{print substr($0,index($0,"=")+1)}' "$ENV_FILE" | tail -n1)"
TOKEN="$(sudo awk -F= '$1=="CODEX_BRIDGE_AGENT_MACHINE_TOKEN"{print substr($0,index($0,"=")+1)}' "$ENV_FILE" | tail -n1)"
WS_URL="$(sudo awk -F= '$1=="CODEX_BRIDGE_AGENT_GATEWAY_WS_URL"{print substr($0,index($0,"=")+1)}' "$ENV_FILE" | tail -n1)"

if [[ -z "$EXECUTOR_ID" || -z "$TOKEN" || -z "$WS_URL" ]]; then
  echo "ERROR: missing executor id, machine token, or websocket URL in $ENV_FILE"
  exit 2
fi

echo "executor_id=$EXECUTOR_ID"
echo "ws_url=$WS_URL"
echo "token_present=yes"

echo "== compute current token hash locally =="
TOKEN_HASH="$(printf '%s' "$TOKEN" | PYTHONPATH="$REPO_ROOT" python3 -c 'import sys; from shared.security import hash_token; print(hash_token(sys.stdin.read()))')"
unset TOKEN
if [[ -z "$TOKEN_HASH" ]]; then
  echo "ERROR: failed to hash machine token"
  exit 2
fi

echo "token_hash_present=yes"

echo "== resync gateway hash with the agent's current machine token =="
REMOTE_EXECUTOR_ID="$(printf '%q' "$EXECUTOR_ID")"
REMOTE_TOKEN_HASH="$(printf '%q' "$TOKEN_HASH")"
ssh -p "$FRIDA_PORT" "$FRIDA" "EXECUTOR_ID=$REMOTE_EXECUTOR_ID TOKEN_HASH=$REMOTE_TOKEN_HASH sudo -u codexbridge /bin/sh -c 'set -a; . /etc/codex-bridge/env; set +a; exec /opt/codex-bridge/.venv/bin/python -'" <<'PY'
import asyncio
import os
import sys

sys.path.insert(0, "/opt/codex-bridge")
from gateway.app.db.session import SessionLocal
from gateway.app.models.entities import ExecutorModel

async def main():
    async with SessionLocal() as session:
        executor_id = os.environ["EXECUTOR_ID"]
        token_hash = os.environ["TOKEN_HASH"]
        executor = await session.get(ExecutorModel, executor_id)
        if executor is None:
            raise SystemExit("executor_not_found")
        executor.machine_token_hash = token_hash
        await session.commit()
        print("gateway_token_hash_updated=yes")

asyncio.run(main())
PY
unset TOKEN_HASH

echo "== restart agent =="
sudo systemctl restart codex-bridge-agent.service
sleep 3
sudo systemctl is-active codex-bridge-agent.service

echo "== wait for agent connection =="
ok=0
for i in {1..18}; do
  logs="$(sudo journalctl -u codex-bridge-agent.service --since '-2 minutes' --no-pager | tail -n 120)"
  if echo "$logs" | grep -Eqi 'connected|registered|connection_established|hello.*accepted|websocket.*open|hello_ack'; then
    ok=1
    break
  fi
  sleep 2
done
sudo journalctl -u codex-bridge-agent.service --since '-2 minutes' --no-pager | tail -n 80 || true

echo "== ask gateway for executor state through MCP =="
MCP="https://codexbridge.inovacaosistemas.com.br:8443/mcp"
RESP="$(curl -fsS --connect-timeout 8 -H 'content-type: application/json' -H 'accept: application/json, text/event-stream' \
  -d '{"jsonrpc":"2.0","id":3,"method":"tools/call","params":{"name":"executor_status","arguments":{"executor_id":"'"$EXECUTOR_ID"'"}}}' \
  "$MCP" || true)"
printf '%s\n' "$RESP"

if [[ "$ok" -eq 1 ]] || printf '%s' "$RESP" | grep -Eqi '"connected"[[:space:]]*:[[:space:]]*true|"online"[[:space:]]*:[[:space:]]*true'; then
  echo "CODEXBRIDGE_AGENT_CONNECTED"
  rc=0
else
  echo "CODEXBRIDGE_AGENT_STILL_NOT_CONNECTED"
  rc=2
fi

git add "$OUT"
git commit -m "results: resync devel3 agent credential" || true
git push origin development
exit "$rc"
