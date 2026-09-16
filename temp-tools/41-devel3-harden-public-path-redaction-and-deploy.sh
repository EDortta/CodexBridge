#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(git rev-parse --show-toplevel)"
cd "$REPO_ROOT"

FRIDA_HOST="frida.inovacaosistemas.com.br"
FRIDA_USER="esteban"
FRIDA_PORT=2200
BASE="https://codexbridge.inovacaosistemas.com.br:8443"
OUT="temp-tools/results/$(date -u +%Y%m%d-%H%M%SZ)-public-path-redaction.txt"
mkdir -p temp-tools/results
exec > >(tee "$OUT") 2>&1

echo "== Harden CodexBridge public path redaction =="
echo "utc=$(date -u +%Y-%m-%dT%H:%M:%SZ)"

echo "== local regression tests =="
python3 -m pytest -q tests/unit/test_security.py

echo "== verify canonical MCP boundary uses redact_sensitive_text =="
grep -q '"line": redact_sensitive_text(item.line)' gateway/app/mcp/server.py
grep -q 'projected\[key\] = redact_sensitive_text(value)' gateway/app/mcp/server.py
echo "mcp_boundary_redaction=present"

echo "== stage deployment files =="
scp -P "$FRIDA_PORT" shared/security.py "$FRIDA_USER@$FRIDA_HOST:/tmp/cb-security.py"
scp -P "$FRIDA_PORT" gateway/app/mcp/server.py "$FRIDA_USER@$FRIDA_HOST:/tmp/cb-mcp-server.py"

ssh -p "$FRIDA_PORT" "$FRIDA_USER@$FRIDA_HOST" 'bash -s' <<'REMOTE'
set -euo pipefail
STAMP="$(date -u +%Y%m%d-%H%M%SZ)"

echo "== backup live files =="
sudo cp /opt/codex-bridge/shared/security.py "/opt/codex-bridge/shared/security.py.bak-$STAMP"
sudo cp /opt/codex-bridge/gateway/app/mcp/server.py "/opt/codex-bridge/gateway/app/mcp/server.py.bak-$STAMP"

echo "== install canonical redaction boundary =="
sudo install -o codexbridge -g codexbridge -m 0644 /tmp/cb-security.py /opt/codex-bridge/shared/security.py
sudo install -o codexbridge -g codexbridge -m 0644 /tmp/cb-mcp-server.py /opt/codex-bridge/gateway/app/mcp/server.py
rm -f /tmp/cb-security.py /tmp/cb-mcp-server.py

echo "== compile before restart =="
cd /tmp
sudo -u codexbridge PYTHONPATH=/opt/codex-bridge /opt/codex-bridge/.venv/bin/python -m py_compile \
  /opt/codex-bridge/shared/security.py \
  /opt/codex-bridge/gateway/app/mcp/server.py

echo "== direct redaction proof on Frida =="
sudo -u codexbridge PYTHONPATH=/opt/codex-bridge /opt/codex-bridge/.venv/bin/python - <<'PY'
from shared.security import redact_sensitive_text
samples = [
    '/home/esteban/Sync/Projects/AI/CodexBridge',
    '/srv/projects/CodexBridge',
]
for value in samples:
    result = redact_sensitive_text(value)
    print(result)
    if result != '[PATH]':
        raise SystemExit(f'path_redaction_failed:{value!r}->{result!r}')
print('frida_path_redaction=ok')
PY

echo "== restart gateway =="
sudo systemctl restart codex-bridge-gateway.service
for i in $(seq 1 30); do
  if curl -fsS --connect-timeout 2 http://127.0.0.1:18080/health >/tmp/cb-health.$$ 2>/dev/null; then
    cat /tmp/cb-health.$$
    echo
    rm -f /tmp/cb-health.$$
    break
  fi
  sleep 1
  if [ "$i" -eq 30 ]; then
    sudo journalctl -u codex-bridge-gateway.service --since '-3 minutes' --no-pager | tail -n 120
    exit 5
  fi
done

echo "== wait for devel3 reconnect =="
for i in $(seq 1 30); do
  if sudo journalctl -u codex-bridge-gateway.service --since '-2 minutes' --no-pager | grep -q 'WebSocket /agent/ws?executor_id=devel3.*accepted'; then
    echo "devel3_websocket=accepted"
    break
  fi
  sleep 1
  if [ "$i" -eq 30 ]; then
    echo "ERROR: devel3 websocket did not reconnect"
    sudo journalctl -u codex-bridge-gateway.service --since '-3 minutes' --no-pager | tail -n 120
    exit 6
  fi
done
REMOTE

echo "== public MCP still healthy =="
curl -fsS --connect-timeout 8 "$BASE/health"
echo
INIT="$(curl -fsS --connect-timeout 8 \
  -H 'content-type: application/json' \
  -H 'accept: application/json, text/event-stream' \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"path-redaction-check","version":"1"}}}' \
  "$BASE/mcp")"
printf '%s\n' "$INIT" | grep -q 'codex-bridge'
echo "mcp_initialize=ok"

echo "== OAuth discovery remains healthy =="
curl -fsS --connect-timeout 8 "$BASE/.well-known/oauth-protected-resource/mcp" | grep -q 'authorization_servers'
echo "oauth_discovery=ok"

echo "CODEXBRIDGE_PUBLIC_PATH_REDACTION_READY"

git add "$OUT"
git commit -m "results: verify public path redaction" || true
git push origin development
