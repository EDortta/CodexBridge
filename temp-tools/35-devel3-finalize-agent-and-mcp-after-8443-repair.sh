#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(git rev-parse --show-toplevel)"
cd "$REPO_ROOT"

BASE="https://codexbridge.inovacaosistemas.com.br:8443"
MCP="${BASE}/mcp"
OUT="temp-tools/results/$(date -u +%Y%m%d-%H%M%SZ)-finalize-agent-mcp.txt"
mkdir -p temp-tools/results
exec > >(tee "$OUT") 2>&1

echo "== CodexBridge finalization after 8443 repair =="
echo "utc=$(date -u +%Y-%m-%dT%H:%M:%SZ)"

echo "== public health =="
curl -fsS --connect-timeout 8 "${BASE}/health"
echo

echo "== restart devel3 agent =="
sudo systemctl restart codex-bridge-agent.service
sleep 4
sudo systemctl is-active codex-bridge-agent.service

echo "== agent logs =="
sudo journalctl -u codex-bridge-agent.service --since '-2 minutes' --no-pager | tail -n 80 || true

echo "== MCP initialize =="
INIT_RESP="$(curl -fsS --connect-timeout 8 -H 'content-type: application/json' -H 'accept: application/json, text/event-stream' \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"devel3-finalizer","version":"1"}}}' \
  "$MCP")"
printf '%s\n' "$INIT_RESP"

echo "== MCP tools/list =="
TOOLS_RESP="$(curl -fsS --connect-timeout 8 -H 'content-type: application/json' -H 'accept: application/json, text/event-stream' \
  -d '{"jsonrpc":"2.0","id":2,"method":"tools/list","params":{}}' \
  "$MCP")"
printf '%s\n' "$TOOLS_RESP"

ok_agent=0
if sudo journalctl -u codex-bridge-agent.service --since '-2 minutes' --no-pager | grep -Eqi 'connected|registered|connection_established|hello.*accepted|websocket.*open'; then
  ok_agent=1
fi

ok_tools=0
if printf '%s' "$TOOLS_RESP" | grep -q 'list_projects' && printf '%s' "$TOOLS_RESP" | grep -q 'start_development_task'; then
  ok_tools=1
fi

if [[ "$ok_agent" -eq 1 && "$ok_tools" -eq 1 ]]; then
  echo "CODEXBRIDGE_OPERATIONAL"
else
  echo "CODEXBRIDGE_NOT_FULLY_OPERATIONAL agent=$ok_agent tools=$ok_tools"
  exit_code=2
fi

git add "$OUT"
git commit -m "results: finalize CodexBridge after 8443 repair" || true
git push origin development
exit "${exit_code:-0}"
