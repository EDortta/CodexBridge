#!/usr/bin/env bash
set -euo pipefail

ROOT="$(git rev-parse --show-toplevel)"
cd "$ROOT"

OUT="temp-tools/results/$(date -u +%Y%m%d-%H%M%SZ)-public-mcp-handshake.txt"
mkdir -p temp-tools/results

PUBLIC_BASE="https://codexbridge.inovacaosistemas.com.br:8443"
MCP_URL="$PUBLIC_BASE/mcp"
FRIDA_SSH=(ssh -p 2200 esteban@frida.inovacaosistemas.com.br)

post_json() {
  local name="$1"
  local payload="$2"
  local extra_auth="${3:-}"
  local hdr body status
  hdr="$(mktemp)"
  body="$(mktemp)"
  if [[ -n "$extra_auth" ]]; then
    status="$(curl -sS --connect-timeout 10 --max-time 20 -D "$hdr" -o "$body" -w '%{http_code}' \
      -H 'content-type: application/json' -H "$extra_auth" --data "$payload" "$MCP_URL" || true)"
  else
    status="$(curl -sS --connect-timeout 10 --max-time 20 -D "$hdr" -o "$body" -w '%{http_code}' \
      -H 'content-type: application/json' --data "$payload" "$MCP_URL" || true)"
  fi
  echo "-- $name --"
  echo "status=$status"
  awk 'BEGIN{IGNORECASE=1} /^content-type:|^www-authenticate:|^mcp-|^server:|^location:/ {gsub(/\r/,""); print}' "$hdr" || true
  python3 - "$body" <<'PY'
import json,sys,re
p=sys.argv[1]
raw=open(p,'r',encoding='utf-8',errors='replace').read()
# Never persist bearer-like material if an upstream error reflects headers/body.
raw=re.sub(r'Bearer\s+[A-Za-z0-9._~+/=-]+','Bearer [REDACTED]',raw,flags=re.I)
try:
    obj=json.loads(raw)
    if isinstance(obj,dict) and isinstance(obj.get('result'),dict) and isinstance(obj['result'].get('tools'),list):
        tools=obj['result']['tools']
        print('tool_count='+str(len(tools)))
        print('tool_names='+','.join(str(x.get('name')) for x in tools if isinstance(x,dict)))
    else:
        print(json.dumps(obj,ensure_ascii=False)[:4000])
except Exception:
    print(raw[:4000])
PY
  rm -f "$hdr" "$body"
}

{
  echo "== public MCP handshake diagnostic =="
  echo "public_base=$PUBLIC_BASE"
  echo

  echo "== public reachability =="
  curl -sS --connect-timeout 10 --max-time 20 -o /dev/null -w 'health_http=%{http_code}\n' "$PUBLIC_BASE/health" || true
  curl -sS --connect-timeout 10 --max-time 20 -D - -o /dev/null "$PUBLIC_BASE/.well-known/oauth-protected-resource" 2>/dev/null \
    | awk 'BEGIN{IGNORECASE=1} /^HTTP\// || /^content-type:|^location:/ {gsub(/\r/,""); print}' || true
  echo

  post_json "initialize unauthenticated" '{"jsonrpc":"2.0","id":"diag-init","method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"codexbridge-diag","version":"1"}}}'
  echo
  post_json "tools/list unauthenticated" '{"jsonrpc":"2.0","id":"diag-tools","method":"tools/list","params":{}}'
  echo

  echo "== runtime auth mode on Frida (no secrets) =="
  "${FRIDA_SSH[@]}" 'set -e; sudo systemctl show codex-bridge-gateway.service -p EnvironmentFiles --no-pager; sudo sh -c '\''for f in /etc/codex-bridge/env /etc/codex-bridge/*.env; do [ -f "$f" ] || continue; grep -E "^(CODEX_BRIDGE_MCP_AUTH_MODE|CODEX_BRIDGE_OAUTH_ALLOW_UNAUTHENTICATED_DISCOVERY|CODEX_BRIDGE_PUBLIC_BASE_URL|CODEX_BRIDGE_OAUTH_ISSUER)=" "$f" || true; done'\''' || true
  echo

  echo "== gateway status/journal tail =="
  "${FRIDA_SSH[@]}" 'sudo systemctl is-active codex-bridge-gateway.service; sudo journalctl -u codex-bridge-gateway.service -n 40 --no-pager | sed -E "s/(Bearer )[A-Za-z0-9._~+\/=:-]+/\1[REDACTED]/g"' || true
  echo

  echo "== interpretation hints =="
  echo "If unauthenticated tools/list is 200 with tool_count>0, public MCP schema is healthy and ChatGPT is likely using cached/old app metadata or a different app endpoint/auth session."
  echo "If tools/list is 401 with OAuth discovery disabled, ChatGPT must complete OAuth before tool discovery, or the server should allow unauthenticated initialize/tools-list discovery."
  echo "If public health works but MCP returns proxy/html/404, inspect nginx/public route rather than project onboarding."
} | tee "$OUT"

git add "$OUT"
git commit -m "results: diagnose public MCP handshake for #104" || true
git push origin development

echo "Wrote $OUT"
