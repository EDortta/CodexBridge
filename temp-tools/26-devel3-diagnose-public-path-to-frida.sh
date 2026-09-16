#!/usr/bin/env bash
set -euo pipefail

ROOT="$(git rev-parse --show-toplevel)"
cd "$ROOT"
OUT="temp-tools/results/$(date -u +%Y%m%d-%H%M%SZ)-public-path-frida.txt"
mkdir -p temp-tools/results
HOST="codexbridge.inovacaosistemas.com.br"
FRIDA="esteban@frida.inovacaosistemas.com.br"
SSH_PORT=2200

{
  echo "== devel3 DNS =="
  getent ahosts "$HOST" || true
  echo
  echo "== devel3 public curl verbose =="
  curl -vk --connect-timeout 8 --max-time 15 "https://${HOST}:8443/health" -o /tmp/cb-health.out 2>&1 || true
  echo "body=$(cat /tmp/cb-health.out 2>/dev/null | head -c 300 || true)"
  echo
  echo "== Frida local runtime/listeners/nginx =="
  ssh -p "$SSH_PORT" "$FRIDA" 'bash -s' <<'REMOTE'
set -u
printf '%s\n' '-- hostname/address --'
hostname -f 2>/dev/null || hostname
getent ahosts codexbridge.inovacaosistemas.com.br || true
printf '%s\n' '-- listeners --'
sudo ss -ltnp | grep -E ':(443|8443|18080)\b' || true
printf '%s\n' '-- gateway direct --'
curl -sS -D - --max-time 5 http://127.0.0.1:18080/health -o /tmp/cb-direct.out || true
cat /tmp/cb-direct.out 2>/dev/null || true
printf '\n%s\n' '-- nginx local TLS with Host --'
curl -skS -D - --resolve codexbridge.inovacaosistemas.com.br:443:127.0.0.1 --max-time 8 https://codexbridge.inovacaosistemas.com.br/health -o /tmp/cb-nginx.out || true
cat /tmp/cb-nginx.out 2>/dev/null || true
printf '\n%s\n' '-- nginx relevant config --'
sudo nginx -T 2>&1 | grep -E -C 3 'codexbridge|listen 443|proxy_pass.*18080' || true
REMOTE
} | tee "$OUT"

git add "$OUT"
git commit -m "results: diagnose public path to Frida MCP" || true
git push origin development

echo "Wrote $OUT"