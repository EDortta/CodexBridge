#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(git rev-parse --show-toplevel)"
cd "$REPO_ROOT"

PUBLIC_HOST="codexbridge.inovacaosistemas.com.br"
FRIDA="esteban@frida.inovacaosistemas.com.br"
FRIDA_SSH_PORT="2200"
OUT="temp-tools/results/$(date -u +%Y%m%d-%H%M%SZ)-check-frida-public-8443.txt"
mkdir -p temp-tools/results
exec > >(tee "$OUT") 2>&1

echo "== CodexBridge public 8443 check =="
echo "utc=$(date -u +%FT%TZ)"
echo "source=$(hostname)"

echo
echo "== DNS =="
getent ahosts "$PUBLIC_HOST" || true

echo
echo "== devel3 -> public 443 =="
set +e
curl -skS --connect-timeout 5 --max-time 8 -w '\nhttp=%{http_code} remote=%{remote_ip}:%{remote_port}\n' "https://${PUBLIC_HOST}/health"
RC443=$?
set -e
echo "rc443=$RC443"

echo
echo "== devel3 -> public 8443 =="
set +e
curl -skS --connect-timeout 8 --max-time 12 -w '\nhttp=%{http_code} remote=%{remote_ip}:%{remote_port}\n' "https://${PUBLIC_HOST}:8443/health"
RC8443=$?
set -e
echo "rc8443=$RC8443"

echo
echo "== Frida local health and listeners =="
ssh -p "$FRIDA_SSH_PORT" "$FRIDA" '
  echo "host=$(hostname)"
  echo "ips=$(hostname -I)"
  echo "-- listeners --"
  sudo ss -lntp | grep -E ":(443|8443|18080)\b" || true
  echo "-- gateway direct --"
  curl -fsS --connect-timeout 3 http://127.0.0.1:18080/health || true
  echo
  echo "-- nginx local TLS --"
  curl -ksS --resolve codexbridge.inovacaosistemas.com.br:443:127.0.0.1 https://codexbridge.inovacaosistemas.com.br/health || true
  echo
  echo "-- default route --"
  ip route | sed -n "1,5p"
' || true

echo
echo "== devel3 agent state =="
sudo systemctl is-active codex-bridge-agent.service || true
sudo journalctl -u codex-bridge-agent.service -n 20 --no-pager || true

echo
echo "== Result =="
if [[ "$RC443" -eq 0 && "$RC8443" -ne 0 ]]; then
  echo "PUBLIC_443_OK_PUBLIC_8443_FAIL"
  echo "Frida is healthy locally, but :8443 is not reachable from devel3. Check router/NAT forwarding at the Frida site: public TCP 8443 should reach Frida HTTPS (normally local 443)."
elif [[ "$RC8443" -eq 0 ]]; then
  echo "PUBLIC_8443_OK"
  echo "The always-on Frida edge is reachable. Next step is MCP initialize/tools-list and agent connectivity."
else
  echo "PUBLIC_EDGE_UNHEALTHY"
  echo "Both public paths failed or returned connection errors."
fi

git add "$OUT"
git commit -m "results: check Frida public 8443 path" || true
git push origin development
