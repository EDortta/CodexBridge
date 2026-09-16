#!/usr/bin/env bash
set -euo pipefail

ROOT="$(git rev-parse --show-toplevel)"
cd "$ROOT"

TS="$(date -u +%Y%m%d-%H%M%SZ)"
OUT="temp-tools/results/${TS}-verify-codexbridge-now.txt"
mkdir -p temp-tools/results

HOST="codexbridge.inovacaosistemas.com.br"
PUBLIC_8443="https://${HOST}:8443"
PUBLIC_443="https://${HOST}"
FRIDA_SSH_HOST="esteban@frida.inovacaosistemas.com.br"
FRIDA_SSH_PORT="2200"
AGENT_UNIT="codex-bridge-agent.service"
GATEWAY_UNIT="codex-bridge-gateway.service"

exec > >(tee "$OUT") 2>&1

printf '== CodexBridge live verification ==\n'
printf 'utc=%s\n' "$(date -u +%FT%TZ)"
printf 'host=%s\n' "$HOST"
printf '\n'

curl_probe() {
  local label="$1" url="$2"
  local body tmp code rc
  tmp="$(mktemp)"
  set +e
  code="$(curl -sS --connect-timeout 5 --max-time 10 -o "$tmp" -w '%{http_code}' "$url")"
  rc=$?
  set -e
  body="$(head -c 500 "$tmp" | tr '\n' ' ')"
  rm -f "$tmp"
  printf '%s rc=%s http=%s body=%s\n' "$label" "$rc" "${code:-000}" "$body"
  [[ "$rc" -eq 0 && "$code" =~ ^2 ]]
}

printf '== devel3 agent ==\n'
if sudo systemctl is-active --quiet "$AGENT_UNIT"; then
  echo 'agent=active'
else
  echo 'agent=inactive'
fi
sudo systemctl --no-pager --full status "$AGENT_UNIT" | sed -n '1,18p' || true
printf '\n'

printf '== Frida gateway ==\n'
ssh -p "$FRIDA_SSH_PORT" -o BatchMode=yes -o ConnectTimeout=8 "$FRIDA_SSH_HOST" \
  "systemctl is-active '$GATEWAY_UNIT'; curl -fsS --max-time 5 http://127.0.0.1:18080/health; echo" || true
printf '\n'

printf '== public edge probes from devel3 ==\n'
set +e
curl_probe 'public_8443_health' "$PUBLIC_8443/health"
R8443=$?
curl_probe 'public_443_health' "$PUBLIC_443/health"
R443=$?
set -e
printf '\n'

printf '== public 8443 MCP handshake ==\n'
INIT_BODY='{"jsonrpc":"2.0","id":"verify-init","method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"codexbridge-verify","version":"1"}}}'
TOOLS_BODY='{"jsonrpc":"2.0","id":"verify-tools","method":"tools/list","params":{}}'

mcp_call() {
  local label="$1" body="$2"
  local tmp code rc
  tmp="$(mktemp)"
  set +e
  code="$(curl -sS --connect-timeout 5 --max-time 12 \
    -H 'content-type: application/json' \
    -d "$body" \
    -o "$tmp" -w '%{http_code}' \
    "$PUBLIC_8443/mcp")"
  rc=$?
  set -e
  printf '%s rc=%s http=%s\n' "$label" "$rc" "${code:-000}"
  if [[ -s "$tmp" ]]; then
    head -c 1200 "$tmp"; echo
  fi
  if [[ "$label" == 'tools_list' && "$rc" -eq 0 && "$code" == "200" ]]; then
    python3 - "$tmp" <<'PY'
import json, sys
p=sys.argv[1]
try:
    data=json.load(open(p))
    tools=data.get('result',{}).get('tools',[])
    names=[t.get('name') for t in tools if isinstance(t,dict)]
    print('tool_count=', len(names), sep='')
    print('has_list_projects=', 'list_projects' in names, sep='')
    print('has_start_development_task=', 'start_development_task' in names, sep='')
except Exception as exc:
    print('tool_parse_error=', exc, sep='')
PY
  fi
  rm -f "$tmp"
  [[ "$rc" -eq 0 && "$code" == "200" ]]
}

set +e
mcp_call 'initialize' "$INIT_BODY"
RINIT=$?
mcp_call 'tools_list' "$TOOLS_BODY"
RTOOLS=$?
set -e
printf '\n'

printf '== verdict ==\n'
if [[ "$R8443" -eq 0 && "$RINIT" -eq 0 && "$RTOOLS" -eq 0 ]]; then
  echo 'CODEXBRIDGE_NOW_OK'
  echo 'The intended :8443 public path and MCP discovery are working from devel3.'
elif [[ "$R8443" -ne 0 && "$R443" -eq 0 ]]; then
  echo 'CODEXBRIDGE_8443_UNREACHABLE_FROM_DEVEL3'
  echo '443 works but 8443 does not from this LAN. This can be router/NAT/hairpin related; do not infer external 8443 is down from this test alone.'
else
  echo 'CODEXBRIDGE_NOW_NOT_OK'
fi

# Commit/push the result so ChatGPT can inspect it.
git add "$OUT"
if ! git diff --cached --quiet; then
  git commit -m "results: verify CodexBridge live state"
  git push origin development
fi
