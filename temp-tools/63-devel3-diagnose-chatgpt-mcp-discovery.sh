#!/usr/bin/env bash
set -uo pipefail

REPO_ROOT="$(git rev-parse --show-toplevel)"
cd "$REPO_ROOT"

STAMP="$(date -u +%Y%m%d-%H%M%SZ)"
OUT="temp-tools/results/${STAMP}-chatgpt-mcp-discovery.txt"
mkdir -p temp-tools/results

if [ -f temp-tools/lib/result-publisher.sh ]; then
  source temp-tools/lib/result-publisher.sh
fi

exec > >(tee "$OUT") 2>&1

HOST="codexbridge.inovacaosistemas.com.br"
MCP="https://${HOST}/mcp"

finish_fallback() {
  rc=$?
  trap - EXIT
  set +e
  if [ -f "$OUT" ]; then
    {
      echo
      echo "== script exit =="
      echo "exit_code=$rc"
      echo "utc=$(date -u +%FT%TZ)"
    } >>"$OUT"
    git add "$OUT" >/dev/null 2>&1 || true
    if ! git diff --cached --quiet -- "$OUT" 2>/dev/null; then
      git commit -m "results: ${STAMP}-chatgpt-mcp-discovery" >/dev/null 2>&1 || true
      git push origin development >/dev/null 2>&1 || true
    fi
  fi
  exit "$rc"
}
trap finish_fallback EXIT

INIT='{"jsonrpc":"2.0","id":"cb63-init","method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"devel3-chatgpt-discovery","version":"1"}}}'
TOOLS='{"jsonrpc":"2.0","id":"cb63-tools","method":"tools/list","params":{}}'

call_mcp() {
  local label="$1"
  local body="$2"
  local hdr bodyfile status ctype
  hdr="$(mktemp)"
  bodyfile="$(mktemp)"
  echo "== $label =="
  curl -sS --http1.1 --connect-timeout 8 --max-time 20     -D "$hdr"     -o "$bodyfile"     -H 'content-type: application/json'     -H 'accept: application/json, text/event-stream'     --data "$body"     "$MCP" || true
  status="$(awk 'BEGIN{IGNORECASE=1} /^HTTP\//{code=$2} END{print code}' "$hdr")"
  ctype="$(awk 'BEGIN{IGNORECASE=1} /^content-type:/{sub(/\r$/,""); print substr($0,index($0,":")+2)}' "$hdr" | tail -1)"
  echo "status=${status:-unknown}"
  echo "content_type=${ctype:-unknown}"
  echo "-- headers --"
  cat "$hdr"
  echo "-- body --"
  cat "$bodyfile"
  echo
  echo
  rm -f "$hdr" "$bodyfile"
}

echo "== CodexBridge ChatGPT MCP discovery diagnostic =="
echo "utc=$(date -u +%FT%TZ)"
echo "client=devel3 external"
echo "mcp=$MCP"
echo

echo "== health =="
curl -sS -D- --connect-timeout 8 --max-time 20 "https://${HOST}/health" || true
echo

echo "== OAuth authorization metadata =="
curl -sS --connect-timeout 8 --max-time 20 "https://${HOST}/.well-known/oauth-authorization-server" | python3 -m json.tool || true
echo

echo "== OAuth protected-resource metadata =="
curl -sS --connect-timeout 8 --max-time 20 "https://${HOST}/.well-known/oauth-protected-resource/mcp" | python3 -m json.tool || true
echo

call_mcp "MCP initialize unauthenticated" "$INIT"
call_mcp "MCP tools/list unauthenticated" "$TOOLS"

echo "== semantic validation =="
INIT_RESP="$(curl -sS --connect-timeout 8 --max-time 20   -H 'content-type: application/json'   -H 'accept: application/json, text/event-stream'   --data "$INIT" "$MCP" || true)"
TOOLS_RESP="$(curl -sS --connect-timeout 8 --max-time 20   -H 'content-type: application/json'   -H 'accept: application/json, text/event-stream'   --data "$TOOLS" "$MCP" || true)"

python3 - "$INIT_RESP" "$TOOLS_RESP" <<'PY'
import json, sys

ok = True
try:
    init = json.loads(sys.argv[1])
except Exception as exc:
    print(f"initialize_json=invalid:{type(exc).__name__}")
    ok = False
    init = {}

try:
    tools = json.loads(sys.argv[2])
except Exception as exc:
    print(f"tools_json=invalid:{type(exc).__name__}")
    ok = False
    tools = {}

result = init.get("result") or {}
print("protocolVersion=" + str(result.get("protocolVersion")))
server = result.get("serverInfo") or {}
print("server_name=" + str(server.get("name")))
print("server_version=" + str(server.get("version")))

tool_items = ((tools.get("result") or {}).get("tools") or [])
print(f"tool_count={len(tool_items)}")
names = [item.get("name") for item in tool_items if isinstance(item, dict)]
for expected in ("list_projects", "start_development_task", "list_executors"):
    present = expected in names
    print(f"tool_{expected}={'present' if present else 'missing'}")
    ok = ok and present

ok = ok and result.get("protocolVersion") == "2025-06-18"
ok = ok and server.get("name") == "codex-bridge"
ok = ok and len(tool_items) > 0

print("mcp_discovery_semantic=" + ("ok" if ok else "failed"))
raise SystemExit(0 if ok else 1)
PY
SEM_RC=$?

echo
echo "== conclusion =="
if [ "$SEM_RC" -eq 0 ]; then
  echo "MCP initialize and tools/list are externally discoverable from devel3."
  echo "If ChatGPT still exposes no CodexBridge actions, the remaining fault is registration/plugin-side rather than MCP tool discovery."
  echo "CODEXBRIDGE_EXTERNAL_MCP_DISCOVERY_READY"
else
  echo "External MCP discovery is not valid yet."
  echo "CODEXBRIDGE_EXTERNAL_MCP_DISCOVERY_FAILED"
  exit "$SEM_RC"
fi
