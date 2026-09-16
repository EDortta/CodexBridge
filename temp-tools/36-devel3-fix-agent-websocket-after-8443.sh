#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(git rev-parse --show-toplevel)"
cd "$REPO_ROOT"

HOST="codexbridge.inovacaosistemas.com.br"
BASE="https://${HOST}:8443"
WS="wss://${HOST}:8443/agent/ws"
AGENT_ENV="/etc/codex-bridge-agent/env"
OUT="temp-tools/results/$(date -u +%Y%m%d-%H%M%SZ)-fix-agent-websocket.txt"
mkdir -p temp-tools/results
exec > >(tee "$OUT") 2>&1

echo "== repair devel3 agent websocket after 8443 recovery =="
echo "utc=$(date -u +%Y-%m-%dT%H:%M:%SZ)"

echo "== verify HTTPS edge =="
curl -fsS --connect-timeout 8 "${BASE}/health"
echo

echo "== show agent websocket config =="
sudo grep '^CODEX_BRIDGE_AGENT_GATEWAY_WS_URL=' "$AGENT_ENV" || true

if sudo grep -q '^CODEX_BRIDGE_AGENT_GATEWAY_WS_URL=' "$AGENT_ENV"; then
  sudo sed -i "s#^CODEX_BRIDGE_AGENT_GATEWAY_WS_URL=.*#CODEX_BRIDGE_AGENT_GATEWAY_WS_URL=${WS}#" "$AGENT_ENV"
else
  echo "CODEX_BRIDGE_AGENT_GATEWAY_WS_URL=${WS}" | sudo tee -a "$AGENT_ENV" >/dev/null
fi
sudo grep '^CODEX_BRIDGE_AGENT_GATEWAY_WS_URL=' "$AGENT_ENV"

echo "== probe websocket upgrade through public 8443 =="
set +e
WS_PROBE="$(curl -skS -i --http1.1 --connect-timeout 8 --max-time 10 \
  -H 'Connection: Upgrade' \
  -H 'Upgrade: websocket' \
  -H 'Sec-WebSocket-Version: 13' \
  -H 'Sec-WebSocket-Key: dGhlIHNhbXBsZSBub25jZQ==' \
  "https://${HOST}:8443/agent/ws" 2>&1)"
WS_RC=$?
set -e
printf '%s\n' "$WS_PROBE" | head -n 40
echo "ws_probe_rc=$WS_RC"

echo "== restart agent =="
sudo systemctl restart codex-bridge-agent.service
sleep 2
sudo systemctl is-active codex-bridge-agent.service

echo "== wait up to 45s for definitive agent outcome =="
ok=0
for i in $(seq 1 15); do
  LOGS="$(sudo journalctl -u codex-bridge-agent.service --since '-2 minutes' --no-pager | tail -n 120)"
  if printf '%s\n' "$LOGS" | grep -Eqi 'connected|registered|connection_established|hello.*accepted|websocket.*open'; then
    ok=1
    break
  fi
  if printf '%s\n' "$LOGS" | grep -Eqi 'unauthorized|forbidden|machine token|token.*invalid|handshake.*fail|certificate verify failed|SSL'; then
    break
  fi
  sleep 3
done

sudo journalctl -u codex-bridge-agent.service --since '-3 minutes' --no-pager | tail -n 120 || true

if [[ "$ok" -eq 1 ]]; then
  echo "AGENT_CONNECTED_OK"
else
  echo "AGENT_STILL_NOT_CONNECTED"
  exit_code=2
fi

git add "$OUT"
git commit -m "results: repair devel3 agent websocket after 8443 recovery" || true
git push origin development
exit "${exit_code:-0}"
