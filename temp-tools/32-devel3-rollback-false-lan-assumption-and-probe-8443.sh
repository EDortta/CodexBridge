#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(git rev-parse --show-toplevel)"
cd "$REPO_ROOT"

PUBLIC_HOST="codexbridge.inovacaosistemas.com.br"
AGENT_ENV="/etc/codex-bridge-agent/env"
HOSTS_FILE="/etc/hosts"
OUT="temp-tools/results/$(date -u +%Y%m%d-%H%M%SZ)-rollback-lan-probe-8443.txt"
mkdir -p temp-tools/results
exec > >(tee "$OUT") 2>&1

echo "== rollback false LAN assumption =="
echo "devel3 and Frida are NOT on the same connected LAN; identical RFC1918 ranges are unrelated"

echo "== remove only CodexBridge pin added by script 31 =="
sudo sed -i '/CodexBridge internal route; public clients still use :8443/d' "$HOSTS_FILE"
getent hosts "$PUBLIC_HOST" || true

echo "== restore agent public route =="
if [[ ! -f "$AGENT_ENV" ]]; then
  echo "ERROR: $AGENT_ENV missing"
  exit 1
fi
sudo cp "$AGENT_ENV" "${AGENT_ENV}.bak-rollback-$(date +%s)"
if sudo grep -q '^CODEX_BRIDGE_AGENT_GATEWAY_WS_URL=' "$AGENT_ENV"; then
  sudo sed -i "s#^CODEX_BRIDGE_AGENT_GATEWAY_WS_URL=.*#CODEX_BRIDGE_AGENT_GATEWAY_WS_URL=wss://${PUBLIC_HOST}:8443/agent/ws#" "$AGENT_ENV"
else
  echo "CODEX_BRIDGE_AGENT_GATEWAY_WS_URL=wss://${PUBLIC_HOST}:8443/agent/ws" | sudo tee -a "$AGENT_ENV" >/dev/null
fi
sudo grep '^CODEX_BRIDGE_AGENT_GATEWAY_WS_URL=' "$AGENT_ENV"

echo "== public route probes from devel3 =="
set +e
curl -sv --connect-timeout 6 "https://${PUBLIC_HOST}:8443/health" -o /tmp/cb8443.body 2>&1 | tail -n 30
rc8443=${PIPESTATUS[0]}
echo "curl_8443_rc=$rc8443"
cat /tmp/cb8443.body 2>/dev/null || true

echo
curl -sv --connect-timeout 6 "https://${PUBLIC_HOST}/health" -o /tmp/cb443.body 2>&1 | tail -n 20
rc443=${PIPESTATUS[0]}
echo "curl_443_rc=$rc443"
cat /tmp/cb443.body 2>/dev/null || true
set -e

echo "== restart agent on intended public 8443 route =="
sudo systemctl restart codex-bridge-agent.service
sleep 5
sudo systemctl is-active codex-bridge-agent.service || true
sudo journalctl -u codex-bridge-agent.service --since '-2 minutes' --no-pager | tail -n 60 || true

echo "== interpretation =="
if [[ "$rc8443" -eq 0 ]]; then
  echo "8443 is reachable from devel3; any remaining failure is above TCP/TLS."
else
  echo "8443 is NOT reachable from devel3. Because Frida is remote, this is NOT a hairpin/LAN issue. Inspect the public 8443 forwarding/firewall path at the Frida site."
fi

echo "ROLLBACK_COMPLETE"

git add "$OUT"
git commit -m "results: rollback false LAN route and probe 8443" || true
git push origin development
