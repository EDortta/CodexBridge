#!/usr/bin/env bash
set -euo pipefail

FRIDA_HOST="frida.inovacaosistemas.com.br"
FRIDA_USER="esteban"
FRIDA_PORT="2200"
PUBLIC_BASE="https://codexbridge.inovacaosistemas.com.br:8443"
RESULT_DIR="temp-tools/results"
TS="$(date -u +%Y%m%d-%H%M%SZ)"
RESULT_FILE="$RESULT_DIR/${TS}-restore-public-8443.txt"
mkdir -p "$RESULT_DIR"

exec > >(tee "$RESULT_FILE") 2>&1

echo "== restore CodexBridge public edge to 8443 =="
echo "public_base=$PUBLIC_BASE"

echo "== update Frida gateway env =="
ssh -p "$FRIDA_PORT" "$FRIDA_USER@$FRIDA_HOST" "sudo python3 - <<'PY'
from pathlib import Path
p=Path('/etc/codex-bridge/env')
text=p.read_text()
key='CODEX_BRIDGE_PUBLIC_BASE_URL='
lines=text.splitlines()
out=[]
found=False
for line in lines:
    if line.startswith(key):
        out.append(key+'https://codexbridge.inovacaosistemas.com.br:8443')
        found=True
    else:
        out.append(line)
if not found:
    out.append(key+'https://codexbridge.inovacaosistemas.com.br:8443')
p.write_text('\n'.join(out)+'\n')
PY
sudo systemctl restart codex-bridge-gateway.service
for i in \$(seq 1 30); do
  if curl -fsS http://127.0.0.1:18080/health >/dev/null 2>&1; then break; fi
  sleep 1
done
sudo systemctl is-active codex-bridge-gateway.service
grep '^CODEX_BRIDGE_PUBLIC_BASE_URL=' /etc/codex-bridge/env
"

echo "== validate metadata through Frida local TLS, preserving external :8443 identity =="
ssh -p "$FRIDA_PORT" "$FRIDA_USER@$FRIDA_HOST" "curl -sk --resolve codexbridge.inovacaosistemas.com.br:443:127.0.0.1 https://codexbridge.inovacaosistemas.com.br/.well-known/oauth-authorization-server"
echo
ssh -p "$FRIDA_PORT" "$FRIDA_USER@$FRIDA_HOST" "curl -sk --resolve codexbridge.inovacaosistemas.com.br:443:127.0.0.1 https://codexbridge.inovacaosistemas.com.br/.well-known/oauth-protected-resource"
echo

echo "NOTE: devel3-to-public-8443 timeout is not authoritative for external reachability when the router lacks NAT loopback/hairpin."
echo "EXPECTED_CHATGPT_MCP_URL=$PUBLIC_BASE/mcp"
echo "RESTORE_8443_OK"

git add "$RESULT_FILE"
git commit -m "results: restore CodexBridge public edge to 8443" || true
git push origin development
