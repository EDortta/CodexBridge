#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(git rev-parse --show-toplevel)"
cd "$REPO_ROOT"

FRIDA_SSH_HOST="esteban@frida.inovacaosistemas.com.br"
FRIDA_SSH_PORT="2200"
AGENT_ENV="/etc/codex-bridge-agent/env"
HOSTS_FILE="/etc/hosts"
PUBLIC_HOST="codexbridge.inovacaosistemas.com.br"
OUT="temp-tools/results/$(date -u +%Y%m%d-%H%M%SZ)-agent-lan-route.txt"
mkdir -p temp-tools/results
exec > >(tee "$OUT") 2>&1

echo "== CodexBridge devel3 agent LAN-route repair =="
echo "public endpoint remains https://${PUBLIC_HOST}:8443/mcp"

echo "== discover Frida LAN address over existing SSH path =="
LAN_IP="$(ssh -p "$FRIDA_SSH_PORT" "$FRIDA_SSH_HOST" "hostname -I" | tr ' ' '\n' | awk '/^(10\.|192\.168\.|172\.(1[6-9]|2[0-9]|3[0-1])\.)/{print; exit}')"
if [[ -z "$LAN_IP" ]]; then
  echo "ERROR: no RFC1918 address discovered on Frida"
  exit 1
fi
echo "frida_lan_ip=$LAN_IP"

echo "== verify Frida HTTPS locally by LAN IP + SNI before changing anything =="
if ! curl -fsS --connect-timeout 5 --resolve "${PUBLIC_HOST}:443:${LAN_IP}" "https://${PUBLIC_HOST}/health"; then
  echo "ERROR: Frida LAN TLS path is not healthy; no changes made"
  exit 1
fi

echo
echo "== pin CodexBridge hostname to Frida only on devel3 =="
sudo cp "$HOSTS_FILE" "${HOSTS_FILE}.bak-codexbridge-$(date +%s)"
sudo sed -i "/[[:space:]]${PUBLIC_HOST//./\.}\([[:space:]]\|$\)/d" "$HOSTS_FILE"
echo "$LAN_IP $PUBLIC_HOST # CodexBridge internal route; public clients still use :8443" | sudo tee -a "$HOSTS_FILE" >/dev/null
getent hosts "$PUBLIC_HOST" || true

echo "== point devel3 agent to internal TLS port 443, not public NAT 8443 =="
if [[ ! -f "$AGENT_ENV" ]]; then
  echo "ERROR: $AGENT_ENV missing"
  exit 1
fi
sudo cp "$AGENT_ENV" "${AGENT_ENV}.bak-$(date +%s)"
if sudo grep -q '^CODEX_BRIDGE_AGENT_GATEWAY_WS_URL=' "$AGENT_ENV"; then
  sudo sed -i "s#^CODEX_BRIDGE_AGENT_GATEWAY_WS_URL=.*#CODEX_BRIDGE_AGENT_GATEWAY_WS_URL=wss://${PUBLIC_HOST}/agent/ws#" "$AGENT_ENV"
else
  echo "CODEX_BRIDGE_AGENT_GATEWAY_WS_URL=wss://${PUBLIC_HOST}/agent/ws" | sudo tee -a "$AGENT_ENV" >/dev/null
fi
sudo grep '^CODEX_BRIDGE_AGENT_GATEWAY_WS_URL=' "$AGENT_ENV"

echo "== restart agent and wait for successful connection =="
sudo systemctl restart codex-bridge-agent.service
sleep 3
sudo systemctl is-active codex-bridge-agent.service

ok=0
for i in {1..12}; do
  logs="$(sudo journalctl -u codex-bridge-agent.service --since '-2 minutes' --no-pager | tail -n 80)"
  if echo "$logs" | grep -Eqi 'connected|connection_established|websocket.*open|registered|hello.*accepted'; then
    ok=1
    break
  fi
  if echo "$logs" | grep -Eqi 'connection_failed|TimeoutError|certificate verify failed|SSL'; then
    :
  fi
  sleep 2
done

sudo journalctl -u codex-bridge-agent.service -n 40 --no-pager || true

if [[ "$ok" -ne 1 ]]; then
  echo "AGENT_CONNECTION_NOT_CONFIRMED"
  exit 2
fi

echo "== gateway health through internal pinned hostname =="
curl -fsS "https://${PUBLIC_HOST}/health"
echo

echo "AGENT_LAN_ROUTE_OK"

echo "== save result =="
git add "$OUT"
git commit -m "results: validate devel3 agent LAN route" || true
git push origin development
