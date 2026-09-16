#!/usr/bin/env bash
set -euo pipefail

REPO="/home/esteban/Sync/Projects/AI/CodexBridge"
HOST="codexbridge.inovacaosistemas.com.br"
FRIDA="esteban@frida.inovacaosistemas.com.br"
PORT=2200
STAMP="$(date -u +%Y%m%d-%H%M%SZ)"
OUT="$REPO/temp-tools/results/${STAMP}-public-mcp-after-443-fix.txt"
mkdir -p "$REPO/temp-tools/results"
exec > >(tee "$OUT") 2>&1

cd "$REPO"

echo "== validate public MCP after 443 fix =="
echo "host=$HOST"

echo
 echo "== wait for Frida gateway direct health =="
for i in $(seq 1 30); do
  if ssh -p "$PORT" "$FRIDA" "curl -fsS --max-time 2 http://127.0.0.1:18080/health >/dev/null"; then
    echo "gateway_direct=ready attempt=$i"
    break
  fi
  if [ "$i" -eq 30 ]; then
    echo "ERROR: gateway direct health did not recover"
    exit 1
  fi
  sleep 2
done

echo
 echo "== wait for public 443 health =="
for i in $(seq 1 30); do
  code=$(curl -ksS --max-time 3 -o /tmp/cb-health.$$ -w '%{http_code}' "https://$HOST/health" || true)
  if [ "$code" = "200" ]; then
    echo "public_health=200 attempt=$i"
    cat /tmp/cb-health.$$
    rm -f /tmp/cb-health.$$
    break
  fi
  echo "attempt=$i public_health=$code"
  if [ "$i" -eq 30 ]; then
    rm -f /tmp/cb-health.$$
    echo "ERROR: public 443 health did not recover"
    exit 1
  fi
  sleep 2
done

echo
 echo "== OAuth metadata =="
for path in '/.well-known/oauth-authorization-server' '/.well-known/oauth-protected-resource'; do
  echo "-- $path --"
  curl -ksS --max-time 5 -D - "https://$HOST$path" -o /tmp/cb-meta.$$ | sed -n '1,12p'
  cat /tmp/cb-meta.$$
  rm -f /tmp/cb-meta.$$
done

echo
 echo "== MCP initialize unauthenticated =="
INIT='{"jsonrpc":"2.0","id":"diag-init","method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"diagnostic","version":"1"}}}'
curl -ksS --max-time 8 -D /tmp/cb-init-h.$$ -H 'content-type: application/json' --data "$INIT" "https://$HOST/mcp" -o /tmp/cb-init-b.$$ || true
head -20 /tmp/cb-init-h.$$
cat /tmp/cb-init-b.$$
rm -f /tmp/cb-init-h.$$ /tmp/cb-init-b.$$

echo
 echo "== MCP tools/list unauthenticated =="
TOOLS='{"jsonrpc":"2.0","id":"diag-tools","method":"tools/list","params":{}}'
curl -ksS --max-time 8 -D /tmp/cb-tools-h.$$ -H 'content-type: application/json' --data "$TOOLS" "https://$HOST/mcp" -o /tmp/cb-tools-b.$$ || true
head -20 /tmp/cb-tools-h.$$
python3 - <<'PY' /tmp/cb-tools-b.$$
import json,sys
p=sys.argv[1]
raw=open(p,'r',encoding='utf-8',errors='replace').read()
print(raw[:12000])
try:
    obj=json.loads(raw)
    tools=((obj.get('result') or {}).get('tools') or [])
    print(f"tool_count={len(tools)}")
    print("tool_names=" + ",".join(t.get('name','?') for t in tools[:50]))
except Exception as e:
    print(f"tool_parse_error={e}")
PY
rm -f /tmp/cb-tools-h.$$ /tmp/cb-tools-b.$$

echo
 echo "== runtime public base/auth mode =="
ssh -p "$PORT" "$FRIDA" "grep -E '^(CODEX_BRIDGE_PUBLIC_BASE_URL|CODEX_BRIDGE_MCP_AUTH_MODE|CODEX_BRIDGE_OAUTH_ALLOW_UNAUTHENTICATED_DISCOVERY)=' /etc/codex-bridge/env || true"

echo
 echo "RESULT_FILE=$OUT"

git add "$OUT"
git commit -m "results: validate public MCP after 443 fix" || true
git push origin development
