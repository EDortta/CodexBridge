#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(git rev-parse --show-toplevel)"
cd "$REPO_ROOT"

FRIDA_HOST="frida.inovacaosistemas.com.br"
FRIDA_USER="esteban"
FRIDA_PORT=2200
BASE="https://codexbridge.inovacaosistemas.com.br:8443"
OUT="temp-tools/results/$(date -u +%Y%m%d-%H%M%SZ)-repair-oauth-502.txt"
mkdir -p temp-tools/results
exec > >(tee "$OUT") 2>&1

echo "== Repair Frida after OAuth discovery 502 =="
echo "utc=$(date -u +%Y-%m-%dT%H:%M:%SZ)"

ssh -p "$FRIDA_PORT" "$FRIDA_USER@$FRIDA_HOST" 'bash -s' <<'REMOTE'
set -euo pipefail

echo "== gateway state before repair =="
sudo systemctl status codex-bridge-gateway.service --no-pager -l | sed -n '1,35p' || true
sudo journalctl -u codex-bridge-gateway.service --since '-10 minutes' --no-pager | tail -n 120 || true

# Script 39 copied only main.py from a newer checkout. If Frida's deployment is
# at another commit that can make imports inconsistent and leave nginx with 502.
# Restore main.py to Frida's own checked-out deployment before doing anything else.
if sudo test -d /opt/codex-bridge/.git; then
  echo "== restore main.py from Frida deployment HEAD =="
  sudo git -C /opt/codex-bridge checkout -- gateway/app/main.py
else
  echo "ERROR: /opt/codex-bridge is not a git checkout; refusing blind overwrite"
  exit 3
fi

sudo systemctl restart codex-bridge-gateway.service
sleep 4
sudo systemctl is-active codex-bridge-gateway.service

echo "== local gateway health after restore =="
curl -fsS --connect-timeout 5 http://127.0.0.1:18080/health
echo

# Add compatibility at nginx instead of changing application code: ChatGPT may
# request RFC9728 metadata for the resource path /mcp. Serve the already-working
# protected-resource metadata at that derived URL.
VHOST=""
for f in /etc/nginx/sites-enabled/* /etc/nginx/conf.d/*.conf; do
  [ -f "$f" ] || continue
  if sudo grep -q 'server_name codexbridge.inovacaosistemas.com.br' "$f"; then
    VHOST="$f"
    break
  fi
done
if [ -z "$VHOST" ]; then
  echo "ERROR: CodexBridge nginx vhost not found"
  exit 4
fi

echo "vhost=$VHOST"
if ! sudo grep -q 'location = /.well-known/oauth-protected-resource/mcp' "$VHOST"; then
  sudo python3 - "$VHOST" <<'PY'
from pathlib import Path
import sys
p = Path(sys.argv[1])
s = p.read_text()
anchor = '    location /.well-known/oauth-protected-resource {\n'
block = '''    location = /.well-known/oauth-protected-resource/mcp {\n        proxy_pass http://127.0.0.1:18080/.well-known/oauth-protected-resource;\n        proxy_http_version 1.1;\n        proxy_set_header Host $host;\n        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;\n        proxy_set_header X-Forwarded-Proto https;\n    }\n\n'''
if anchor not in s:
    raise SystemExit('oauth protected-resource nginx anchor not found')
p.write_text(s.replace(anchor, block + anchor, 1))
PY
fi

sudo nginx -t
sudo systemctl reload nginx

echo "== local TLS metadata checks =="
for path in '/.well-known/oauth-protected-resource/mcp' '/.well-known/oauth-protected-resource' '/.well-known/oauth-authorization-server'; do
  echo "-- $path --"
  curl -ksS --fail --resolve codexbridge.inovacaosistemas.com.br:443:127.0.0.1 \
    "https://codexbridge.inovacaosistemas.com.br${path}"
  echo
done
REMOTE

echo "== public :8443 validation =="
for path in '/health' '/.well-known/oauth-protected-resource/mcp' '/.well-known/oauth-protected-resource' '/.well-known/oauth-authorization-server'; do
  echo "-- $path --"
  curl -fsS --connect-timeout 8 "$BASE$path"
  echo
done

echo "== MCP initialize =="
curl -fsS --connect-timeout 8 \
  -H 'content-type: application/json' \
  -H 'accept: application/json, text/event-stream' \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"oauth-repair-check","version":"1"}}}' \
  "$BASE/mcp" | grep -q 'codex-bridge'

echo "CHATGPT_OAUTH_EDGE_READY"

git add "$OUT"
git commit -m "results: repair OAuth discovery 502" || true
git push origin development
