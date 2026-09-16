#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(git rev-parse --show-toplevel)"
cd "$REPO_ROOT"

FRIDA_HOST="frida.inovacaosistemas.com.br"
FRIDA_USER="esteban"
FRIDA_PORT=2200
HOST="codexbridge.inovacaosistemas.com.br"
BASE_8443="https://${HOST}:8443"
BASE_443="https://${HOST}"
OUT="temp-tools/results/$(date -u +%Y%m%d-%H%M%SZ)-chatgpt-pkce-discovery.txt"
mkdir -p temp-tools/results
exec > >(tee "$OUT") 2>&1

echo "== Diagnose ChatGPT PKCE OAuth discovery =="
echo "utc=$(date -u +%Y-%m-%dT%H:%M:%SZ)"

probe() {
  local base="$1" path="$2"
  local body headers
  body="$(mktemp)"
  headers="$(mktemp)"
  echo "-- ${base}${path} --"
  if curl -ksS --max-time 12 -D "$headers" -o "$body" "${base}${path}"; then
    sed -n '1,20p' "$headers"
    cat "$body"; echo
    python3 - "$body" <<'PY'
import json, sys
p=sys.argv[1]
try:
    d=json.load(open(p))
except Exception as e:
    print(f"json_parse_error={e}")
    raise SystemExit(0)
print("issuer=", d.get("issuer"))
print("authorization_endpoint=", d.get("authorization_endpoint"))
print("token_endpoint=", d.get("token_endpoint"))
print("code_challenge_methods_supported=", d.get("code_challenge_methods_supported"))
print("resource=", d.get("resource"))
print("authorization_servers=", d.get("authorization_servers"))
PY
  else
    echo "curl_failed=$?"
  fi
  rm -f "$body" "$headers"
}

echo "== public metadata on permanent :8443 endpoint =="
for path in \
  '/.well-known/oauth-authorization-server' \
  '/.well-known/openid-configuration' \
  '/.well-known/oauth-protected-resource' \
  '/.well-known/oauth-protected-resource/mcp'; do
  probe "$BASE_8443" "$path"
done

echo "== compare legacy bare-443 endpoint =="
for path in \
  '/.well-known/oauth-authorization-server' \
  '/.well-known/openid-configuration' \
  '/.well-known/oauth-protected-resource' \
  '/.well-known/oauth-protected-resource/mcp'; do
  probe "$BASE_443" "$path"
done

echo "== assert PKCE S256 on :8443 authorization metadata =="
for path in '/.well-known/oauth-authorization-server' '/.well-known/openid-configuration'; do
  json="$(curl -ksS --fail --max-time 12 "$BASE_8443$path")"
  python3 - "$path" "$json" <<'PY'
import json, sys
path, raw = sys.argv[1], sys.argv[2]
d=json.loads(raw)
methods=d.get('code_challenge_methods_supported')
print(f"{path}: methods={methods}")
if not isinstance(methods, list) or 'S256' not in methods:
    raise SystemExit(f"PKCE_S256_MISSING:{path}")
PY
done
echo "pkce_s256_public_8443=ok"

echo "== inspect live Frida metadata and recent ChatGPT/OpenAI OAuth requests =="
ssh -p "$FRIDA_PORT" "$FRIDA_USER@$FRIDA_HOST" 'bash -s' <<'REMOTE'
set -euo pipefail

echo "-- direct gateway authorization metadata --"
curl -fsS --max-time 5 http://127.0.0.1:18080/.well-known/oauth-authorization-server; echo

echo "-- direct gateway OIDC metadata --"
curl -fsS --max-time 5 http://127.0.0.1:18080/.well-known/openid-configuration; echo

echo "-- nginx routes related to oauth/well-known --"
sudo nginx -T 2>/dev/null | grep -nE 'well-known|oauth/(authorize|token)|server_name codexbridge' | tail -n 120 || true

echo "-- recent nginx requests touching OAuth discovery --"
sudo sh -c '
for f in /var/log/nginx/*access*.log /var/log/nginx/access.log; do
  [ -f "$f" ] || continue
  echo "### $f"
  tail -n 2500 "$f" | grep -Ei "well-known|oauth/authorize|oauth/token|codexbridge" | tail -n 250 || true
done
'

echo "-- recent gateway OAuth requests --"
sudo journalctl -u codex-bridge-gateway.service --since '-45 minutes' --no-pager \
  | grep -Ei 'well-known|oauth/authorize|oauth/token|mcp' | tail -n 250 || true
REMOTE

echo "== interpretation marker =="
echo "If :8443 metadata above contains code_challenge_methods_supported=[S256] but ChatGPT still rejects PKCE, compare the recent nginx request paths/host/port. That tells us which discovery URL ChatGPT actually fetched."
echo "CHATGPT_PKCE_DISCOVERY_DIAGNOSTIC_COMPLETE"

git add "$OUT"
git commit -m "results: diagnose ChatGPT PKCE discovery" || true
git push origin development
