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

echo "== resync gateway hash with the agent's current machine token =="
printf '%s' "$TOKEN" | ssh -p "$FRIDA_PORT" "$FRIDA" "EXECUTOR_ID='$EXECUTOR_ID' python3 -c 'import asyncio,sys; sys.path.insert(0,\"/opt/codex-bridge\"); from gateway.app.db.session import SessionLocal; from gateway.app.models.entities import ExecutorModel; from shared.security import hash_token; async def main():\n async with SessionLocal() as s:\n  e=await s.get(ExecutorModel, \"'$EXECUTOR_ID'\")\n  assert e is not None, \"executor_not_found\"\n  token=sys.stdin.read()\n  e.machine_token_hash=hash_token(token)\n  await s.commit()\n  print(\"gateway_token_hash_updated=yes\")\nasyncio.run(main())'" 2>/dev/null

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
