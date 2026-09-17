#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(git rev-parse --show-toplevel)"
cd "$REPO_ROOT"

STAMP="$(date -u +%Y%m%d-%H%M%SZ)"
RESULT="temp-tools/results/${STAMP}-pkce-oauth-alias-v3.txt"
mkdir -p temp-tools/results
exec > >(tee "$RESULT") 2>&1

FRIDA_SSH=(ssh -p 2200 esteban@frida.inovacaosistemas.com.br)
PUBLIC_ORIGIN="https://codexbridge.inovacaosistemas.com.br:8443"
ISSUER_PATH="codexbridge-v3"
FRESH_ISSUER="${PUBLIC_ORIGIN}/${ISSUER_PATH}"
VHOST="/etc/nginx/sites-enabled/codexbridge-https"
DISCOVERY="/.well-known/oauth-authorization-server/${ISSUER_PATH}"

cat <<EOF
== Publish ChatGPT PKCE OAuth alias v3 ==
utc=$(date -u +%FT%TZ)
fresh_issuer=${FRESH_ISSUER}
discovery=${DISCOVERY}
EOF

META="$(python3 - <<'PY'
import json
origin='https://codexbridge.inovacaosistemas.com.br:8443'
issuer=origin+'/codexbridge-v3'
print(json.dumps({
  'issuer': issuer,
  'authorization_endpoint': origin+'/oauth/authorize',
  'token_endpoint': origin+'/oauth/token',
  'scopes_supported': ['codexbridge.read','codexbridge.task.cancel','codexbridge.task.submit'],
  'response_types_supported': ['code'],
  'grant_types_supported': ['authorization_code'],
  'token_endpoint_auth_methods_supported': ['none'],
  'code_challenge_methods_supported': ['S256'],
}, separators=(',',':')))
PY
)"
META_B64="$(printf '%s' "$META" | base64 -w0)"

"${FRIDA_SSH[@]}" "META_B64='$META_B64' VHOST='$VHOST' ISSUER_PATH='$ISSUER_PATH' bash -s" <<'REMOTE'
set -euo pipefail
META="$(printf '%s' "$META_B64" | base64 -d)"
DISCOVERY="/.well-known/oauth-authorization-server/${ISSUER_PATH}"
BACKUP="/var/backups/codex-bridge/nginx-pkce-v3-$(date -u +%Y%m%d-%H%M%SZ)"
sudo mkdir -p "$BACKUP"
sudo cp -a "$VHOST" "$BACKUP/"
echo "backup=$BACKUP"

TMP="$(mktemp)"
sudo cp "$VHOST" "$TMP"
sudo chown "$(id -u):$(id -g)" "$TMP"

python3 - "$TMP" "$META" "$DISCOVERY" <<'PY'
from pathlib import Path
import sys
p=Path(sys.argv[1])
meta=sys.argv[2]
discovery=sys.argv[3]
text=p.read_text()
marker='# CODEXBRIDGE_CHATGPT_PKCE_ALIAS_V3'
if marker in text:
    print('nginx_alias_v3=already_present')
    raise SystemExit(0)

# Put the exact-match route immediately before the already-proven OAuth
# authorization-server location in the same TLS server block.  Do not infer
# the server block from the last brace (the v2 attempt did that and the route
# was not served on the public path).
anchor='    location /.well-known/oauth-authorization-server {'
pos=text.find(anchor)
if pos < 0:
    raise SystemExit('oauth authorization-server anchor not found in TLS vhost')
block=f'''    {marker}\n    location = {discovery} {{\n        default_type application/json;\n        add_header Cache-Control "no-store, no-cache, must-revalidate, max-age=0" always;\n        add_header Pragma "no-cache" always;\n        add_header Expires "0" always;\n        return 200 '{meta}';\n    }}\n\n'''
text=text[:pos]+block+text[pos:]
p.write_text(text)
print('nginx_alias_v3=installed')
PY

sudo cp "$TMP" "$VHOST"
rm -f "$TMP"
sudo nginx -t
sudo systemctl reload nginx

# Prove nginx loaded this exact location in the effective config.
sudo nginx -T 2>/dev/null | grep -F "location = $DISCOVERY" >/dev/null
echo "effective_nginx_route=present"

# Prove the local TLS vhost itself serves it before testing public NAT.
LOCAL="$(curl -kfsS --resolve codexbridge.inovacaosistemas.com.br:443:127.0.0.1 \
  "https://codexbridge.inovacaosistemas.com.br${DISCOVERY}")"
printf '%s\n' "$LOCAL"
python3 - "$LOCAL" <<'PY'
import json,sys
obj=json.loads(sys.argv[1])
assert obj.get('issuer','').endswith('/codexbridge-v3'), obj
assert 'S256' in obj.get('code_challenge_methods_supported', []), obj
print('local_tls_alias=ok')
PY
REMOTE

echo "== validate public fresh discovery =="
BODY="$(curl -fsS -H 'Cache-Control: no-cache' "${PUBLIC_ORIGIN}${DISCOVERY}")"
printf '%s\n' "$BODY"
python3 - "$BODY" "$FRESH_ISSUER" <<'PY'
import json,sys
obj=json.loads(sys.argv[1]); expected=sys.argv[2]
assert obj.get('issuer') == expected, obj
assert 'S256' in obj.get('code_challenge_methods_supported', []), obj
assert obj.get('authorization_endpoint','').endswith('/oauth/authorize'), obj
assert obj.get('token_endpoint','').endswith('/oauth/token'), obj
print('public_pkce_alias_v3=ok')
PY

echo "== verify original surfaces remain healthy =="
curl -fsS "${PUBLIC_ORIGIN}/health"; echo
curl -fsS "${PUBLIC_ORIGIN}/.well-known/oauth-authorization-server" | \
  python3 -c 'import json,sys; d=json.load(sys.stdin); assert "S256" in d.get("code_challenge_methods_supported",[]); print("original_oauth=ok")'

cat <<EOF
CHATGPT_PKCE_ALIAS_V3_READY
Use in ChatGPT:
Authorization server base: ${FRESH_ISSUER}
Auth URL: ${PUBLIC_ORIGIN}/oauth/authorize
Token URL: ${PUBLIC_ORIGIN}/oauth/token
Resource: ${PUBLIC_ORIGIN}/mcp
Client ID: chatgpt-codexbridge
Token endpoint auth method: none
EOF

git add "$RESULT"
if ! git diff --cached --quiet; then
  git commit -m "results: publish ChatGPT PKCE OAuth alias v3"
  git push origin development
fi
