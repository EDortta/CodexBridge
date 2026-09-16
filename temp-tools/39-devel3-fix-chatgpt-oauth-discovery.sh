#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(git rev-parse --show-toplevel)"
cd "$REPO_ROOT"

FRIDA_HOST="frida.inovacaosistemas.com.br"
FRIDA_USER="esteban"
FRIDA_PORT=2200
BASE="https://codexbridge.inovacaosistemas.com.br:8443"
OUT="temp-tools/results/$(date -u +%Y%m%d-%H%M%SZ)-chatgpt-oauth-discovery.txt"
mkdir -p temp-tools/results
exec > >(tee "$OUT") 2>&1

echo "== Fix ChatGPT OAuth discovery =="
echo "utc=$(date -u +%Y-%m-%dT%H:%M:%SZ)"

python3 - <<'PY'
from pathlib import Path
p = Path('gateway/app/main.py')
s = p.read_text()
old = '@app.get("/.well-known/oauth-protected-resource")\nasync def oauth_protected_resource() -> dict:'
new = '@app.get("/.well-known/oauth-protected-resource")\n@app.get("/.well-known/oauth-protected-resource/mcp")\nasync def oauth_protected_resource() -> dict:'
if new not in s:
    if old not in s:
        raise SystemExit('protected-resource route anchor not found')
    p.write_text(s.replace(old, new, 1))
    print('patched_main=yes')
else:
    print('patched_main=already')
PY

python3 -m py_compile gateway/app/main.py

echo "== commit canonical source change =="
git add gateway/app/main.py
git commit -m "fix: serve RFC9728 metadata for MCP resource path" || true
git push origin development

echo "== deploy gateway main.py to Frida =="
scp -P "$FRIDA_PORT" gateway/app/main.py "$FRIDA_USER@$FRIDA_HOST:/tmp/codexbridge-main.py"
ssh -p "$FRIDA_PORT" "$FRIDA_USER@$FRIDA_HOST" \
  "sudo install -o codexbridge -g codexbridge -m 0644 /tmp/codexbridge-main.py /opt/codex-bridge/gateway/app/main.py && rm -f /tmp/codexbridge-main.py && sudo systemctl restart codex-bridge-gateway.service && sleep 3 && sudo systemctl is-active codex-bridge-gateway.service"

echo "== validate OAuth metadata through permanent public endpoint =="
for path in '/.well-known/oauth-protected-resource/mcp' '/.well-known/oauth-protected-resource' '/.well-known/oauth-authorization-server'; do
  echo "-- $path --"
  curl -fsS --connect-timeout 8 "$BASE$path"
  echo
done

echo "== validate MCP discovery =="
curl -fsS --connect-timeout 8 \
  -H 'content-type: application/json' \
  -H 'accept: application/json, text/event-stream' \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"oauth-discovery-check","version":"1"}}}' \
  "$BASE/mcp" | grep -q 'codex-bridge'

echo "CHATGPT_OAUTH_DISCOVERY_READY"

git add "$OUT"
git commit -m "results: ChatGPT OAuth discovery fix" || true
git push origin development
