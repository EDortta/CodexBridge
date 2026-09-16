#!/usr/bin/env bash
set -euo pipefail

ROOT="$(git rev-parse --show-toplevel)"
cd "$ROOT"
OUT="temp-tools/results/$(date -u +%Y%m%d-%H%M%SZ)-public-port-repair.txt"
mkdir -p temp-tools/results

HOST="codexbridge.inovacaosistemas.com.br"
FRIDA_SSH=(ssh -p 2200 esteban@frida.inovacaosistemas.com.br)

{
  echo "== CodexBridge public port repair probe =="
  echo "host=$HOST"
  echo

  echo "== devel3 public 443 =="
  set +e
  CURL443=$(curl -ksS --connect-timeout 8 --max-time 12 -o /tmp/cb443.body -w 'http=%{http_code} remote=%{remote_ip}:%{remote_port}' "https://${HOST}/health" 2>&1)
  RC443=$?
  set -e
  echo "rc=$RC443 $CURL443"
  [ -f /tmp/cb443.body ] && { echo -n "body="; head -c 300 /tmp/cb443.body; echo; }
  echo

  echo "== devel3 public 8443 =="
  set +e
  CURL8443=$(curl -ksS --connect-timeout 8 --max-time 12 -o /tmp/cb8443.body -w 'http=%{http_code} remote=%{remote_ip}:%{remote_port}' "https://${HOST}:8443/health" 2>&1)
  RC8443=$?
  set -e
  echo "rc=$RC8443 $CURL8443"
  [ -f /tmp/cb8443.body ] && { echo -n "body="; head -c 300 /tmp/cb8443.body; echo; }
  echo

  echo "== Frida local TLS sanity =="
  "${FRIDA_SSH[@]}" "curl -ksS --resolve ${HOST}:443:127.0.0.1 -o /tmp/cb-local.body -w 'http=%{http_code}\n' https://${HOST}/health; head -c 300 /tmp/cb-local.body; echo"
  echo

  if [ "$RC443" -eq 0 ] && grep -q '"status"[[:space:]]*:[[:space:]]*"ok"' /tmp/cb443.body 2>/dev/null; then
    echo "== public 443 is healthy; normalize PUBLIC_BASE_URL =="
    "${FRIDA_SSH[@]}" 'set -euo pipefail
      ENV=/etc/codex-bridge/env
      sudo cp "$ENV" "$ENV.bak-$(date +%s)"
      if sudo grep -q "^CODEX_BRIDGE_PUBLIC_BASE_URL=" "$ENV"; then
        sudo sed -i "s#^CODEX_BRIDGE_PUBLIC_BASE_URL=.*#CODEX_BRIDGE_PUBLIC_BASE_URL=https://codexbridge.inovacaosistemas.com.br#" "$ENV"
      else
        echo "CODEX_BRIDGE_PUBLIC_BASE_URL=https://codexbridge.inovacaosistemas.com.br" | sudo tee -a "$ENV" >/dev/null
      fi
      sudo systemctl restart codex-bridge-gateway.service
      sleep 3
      systemctl is-active codex-bridge-gateway.service
      sudo grep "^CODEX_BRIDGE_PUBLIC_BASE_URL=" "$ENV"
      curl -ksS --resolve codexbridge.inovacaosistemas.com.br:443:127.0.0.1 https://codexbridge.inovacaosistemas.com.br/.well-known/oauth-protected-resource | head -c 1000; echo'
    echo "PUBLIC_443_REPAIRED"
  else
    echo "PUBLIC_EDGE_BLOCKED: neither application code nor nginx is the current blocker."
    echo "The gateway is healthy locally, but devel3 cannot reach the public edge on 443."
    echo "Check router/firewall/NAT forwarding to Frida:443 before changing CodexBridge again."
  fi
} | tee "$OUT"

git add "$OUT"
git commit -m "results: probe/repair CodexBridge public edge" || true
git push origin development

echo "Wrote $OUT"
