#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(git rev-parse --show-toplevel)"
cd "$REPO_ROOT"

STAMP="$(date -u +%Y%m%d-%H%M%SZ)"
RESULT="temp-tools/results/${STAMP}-legacy-443-plugin-source.txt"
mkdir -p temp-tools/results
exec > >(tee "$RESULT") 2>&1

HOST="codexbridge.inovacaosistemas.com.br"
LEGACY="https://${HOST}"
CURRENT="https://${HOST}:8443"
FRIDA_SSH=(ssh -p 2200 esteban@frida.inovacaosistemas.com.br)
MARKER="cbtrace-${STAMP}-$$"

cat <<EOF
== Trace legacy bare-443 CodexBridge plugin source ==
utc=$(date -u +%FT%TZ)
marker=$MARKER
legacy=$LEGACY
current=$CURRENT

Purpose:
- determine whether bare 443 and :8443 reach the same CodexBridge backend;
- determine whether bare 443 traverses Frida or another ingress (for example T610);
- check whether a legacy plugin manifest/source is still publicly served on bare 443;
- establish whether the old ChatGPT plugin can be updated entirely from our infrastructure side.
EOF

printf '\n== DNS ==\n'
getent ahosts "$HOST" || true

probe_headers() {
  local base="$1"
  printf '\n-- HEAD-ish probe %s --\n' "$base"
  curl -ksS -D - -o /dev/null --max-time 12 "$base/health" || true
}
probe_headers "$LEGACY"
probe_headers "$CURRENT"

printf '\n== MCP initialize on both public origins ==\n'
for base in "$LEGACY" "$CURRENT"; do
  echo "-- $base/mcp --"
  body="$(curl -ksS --max-time 15 \
    -H 'content-type: application/json' \
    -H 'accept: application/json, text/event-stream' \
    -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"codexbridge-legacy-trace","version":"1"}}}' \
    "$base/mcp" || true)"
  printf '%s\n' "$body"
  python3 - "$body" <<'PY' || true
import json,sys
raw=sys.argv[1].strip()
try:
    d=json.loads(raw)
    si=(d.get('result') or {}).get('serverInfo') or {}
    print('server_name=',si.get('name'))
    print('server_version=',si.get('version'))
except Exception as e:
    print('parse_error=',repr(e))
PY
done

printf '\n== OAuth metadata on both public origins ==\n'
for base in "$LEGACY" "$CURRENT"; do
  for path in '/.well-known/oauth-protected-resource/mcp' '/.well-known/oauth-protected-resource' '/.well-known/oauth-authorization-server' '/.well-known/openid-configuration'; do
    echo "-- $base$path --"
    body="$(curl -ksS --max-time 12 "$base$path" || true)"
    printf '%s\n' "$body"
    python3 - "$body" <<'PY' || true
import json,sys
try:
 d=json.loads(sys.argv[1])
 for k in ('resource','issuer','authorization_servers','authorization_endpoint','token_endpoint','code_challenge_methods_supported'):
  if k in d: print(f'{k}={d[k]}')
except Exception as e:
 print('parse_error=',repr(e))
PY
  done
done

printf '\n== Probe common legacy plugin definition paths ==\n'
# We do not assume the old registration used ai-plugin.json; these probes merely
# establish whether a source-driven legacy definition is still hosted by us.
for base in "$LEGACY" "$CURRENT"; do
  echo "## origin=$base"
  for path in \
    '/.well-known/ai-plugin.json' \
    '/ai-plugin.json' \
    '/openapi.json' \
    '/openapi.yaml' \
    '/openapi.yml' \
    '/.well-known/openapi.json' \
    '/.well-known/openapi.yaml'
  do
    tmp="$(mktemp)"
    code="$(curl -ksS --max-time 10 -o "$tmp" -w '%{http_code}' "$base$path" || printf '000')"
    ctype="$(curl -ksSI --max-time 10 "$base$path" 2>/dev/null | awk 'BEGIN{IGNORECASE=1}/^content-type:/{sub(/\r$/,"",$0); print substr($0,index($0,$2)); exit}' || true)"
    size="$(wc -c < "$tmp" | tr -d ' ')"
    echo "$path status=$code bytes=$size content_type=${ctype:-unknown}"
    if [[ "$code" == "200" && "$size" -gt 0 ]]; then
      head -c 2000 "$tmp"; echo
    fi
    rm -f "$tmp"
  done
done

printf '\n== Send unique trace requests to each ingress ==\n'
# Query string survives normal reverse-proxying and lets us ask Frida's nginx
# access log which public ingress actually traversed it.
curl -ksS --max-time 10 -o /dev/null "${LEGACY}/health?cbtrace=${MARKER}-legacy" || true
sleep 1
curl -ksS --max-time 10 -o /dev/null "${CURRENT}/health?cbtrace=${MARKER}-8443" || true
sleep 2

printf '\n== Inspect Frida for trace marker and ingress configuration ==\n'
"${FRIDA_SSH[@]}" "MARKER='$MARKER' bash -s" <<'REMOTE'
set -u
echo '-- Frida hostname / addresses --'
hostname || true
hostname -I || true

echo '-- listeners relevant to CodexBridge --'
sudo ss -ltnp 2>/dev/null | grep -E ':(443|8443|18080)\b' || true

echo '-- trace hits in nginx logs --'
FOUND=0
for f in /var/log/nginx/access.log /var/log/nginx/*access*.log; do
  [[ -f "$f" ]] || continue
  hits="$(sudo grep -F "$MARKER" "$f" 2>/dev/null || true)"
  if [[ -n "$hits" ]]; then
    echo "### $f"
    printf '%s\n' "$hits"
    FOUND=1
  fi
done
[[ "$FOUND" -eq 1 ]] || echo 'frida_trace_hits=none'

echo '-- effective nginx CodexBridge server blocks/upstreams --'
sudo nginx -T 2>/dev/null | grep -nE -C 3 'server_name[[:space:]]+codexbridge\.inovacaosistemas\.com\.br|listen[[:space:]].*(443|8443)|proxy_pass.*18080|codexbridge-v[23]' || true

echo '-- local gateway identity --'
curl -fsS --max-time 5 http://127.0.0.1:18080/health || true; echo
curl -fsS --max-time 8 \
  -H 'content-type: application/json' \
  -H 'accept: application/json, text/event-stream' \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"frida-local-trace","version":"1"}}}' \
  http://127.0.0.1:18080/mcp || true; echo

echo '-- names that may identify the work-hours/T610 path (diagnostic only) --'
for name in t610 T610 dom1; do
  printf '%s: ' "$name"
  getent hosts "$name" 2>/dev/null || echo unresolved
done
REMOTE

printf '\n== Automated comparison ==\n'
python3 - "$LEGACY" "$CURRENT" <<'PY'
import json, subprocess, sys
legacy,current=sys.argv[1:]
def init(base):
    p=subprocess.run([
      'curl','-ksS','--max-time','12','-H','content-type: application/json',
      '-H','accept: application/json, text/event-stream',
      '-d','{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"compare","version":"1"}}}',
      base+'/mcp'],capture_output=True,text=True)
    try:
      d=json.loads(p.stdout); return (d.get('result') or {}).get('serverInfo') or {}
    except Exception: return {}
a=init(legacy); b=init(current)
print('legacy_serverInfo=',a)
print('current_serverInfo=',b)
print('same_server_identity=', bool(a and b and a==b))
PY

cat <<'EOF'

== How to interpret ==
1) If bare 443 and :8443 both announce codex-bridge 0.2.0, the old URL is already
   reaching the new application code; the question becomes ingress/OAuth metadata,
   not application deployment.
2) If only the :8443 trace appears in Frida nginx logs, bare 443 is taking another
   ingress path. That is strong evidence we can update that path ourselves once we
   identify its proxy (potentially the T610/work-hours path).
3) If both traces appear in Frida logs, bare 443 ultimately traverses Frida too,
   even if another proxy exists before it.
4) A 200 ai-plugin/openapi probe would support the 'directory refreshes from source'
   hypothesis. 404s do NOT prove the ChatGPT registration cannot be updated from our
   side; this CodexBridge integration was registered as an MCP app, so its durable
   definition may live in ChatGPT rather than in a legacy ai-plugin manifest.
5) Do not modify routing yet. This script is read-only apart from writing its result.

CODEXBRIDGE_LEGACY_443_TRACE_COMPLETE
EOF

git add "$RESULT"
if ! git diff --cached --quiet; then
  git commit -m "results: trace legacy bare-443 CodexBridge source"
  git push origin development
fi
