#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(git rev-parse --show-toplevel)"
cd "$REPO_ROOT"

STAMP="$(date -u +%Y%m%d-%H%M%SZ)"
RESULT="temp-tools/results/${STAMP}-fresh-pkce-oauth-alias.txt"
mkdir -p temp-tools/results
exec > >(tee "$RESULT") 2>&1

FRIDA_SSH=(ssh -p 2200 esteban@frida.inovacaosistemas.com.br)
PUBLIC_ORIGIN="https://codexbridge.inovacaosistemas.com.br:8443"
ISSUER_PATH="codexbridge-v2"
FRESH_ISSUER="${PUBLIC_ORIGIN}/${ISSUER_PATH}"
VHOST="/etc/nginx/sites-enabled/codexbridge-https"

cat <<EOF
== Publish fresh ChatGPT PKCE OAuth discovery alias ==
utc=$(date -u +%FT%TZ)
fresh_issuer=${FRESH_ISSUER}
EOF

META=$(python3 - <<'PY'
import json
origin='https://codexbridge.inovacaosistemas.com.br:8443'
issuer=origin+'/codexbridge-v2'
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
)

META_B64=$(printf '%s' "$META" | base64 -w0)

"${FRIDA_SSH[@]}" "META_B64='$META_B64' VHOST='$VHOST' ISSUER_PATH='$ISSUER_PATH' bash -s" <<'REMOTE'
set -euo pipefail
META="$(printf '%s' "$META_B64" | base64 -d)"
BACKUP="/var/backups/codex-bridge/nginx-pkce-$(date -u +%Y%m%d-%H%M%SZ)"
sudo mkdir -p "$BACKUP"
sudo cp -a "$VHOST" "$BACKUP/"
echo "backup=$BACKUP"

TMP="$(mktemp)"
sudo cp "$VHOST" "$TMP"
sudo chown "$(id -u):$(id -g)" "$TMP"

python3 - "$TMP" "$META" "$ISSUER_PATH" <<'PY'
from pathlib import Path
import sys
p=Path(sys.argv[1])
meta=sys.argv[2]
path=sys.argv[3]
text=p.read_text()
marker='# CODEXBRIDGE_CHATGPT_PKCE_ALIAS_V2'
if marker in text:
    print('nginx_alias=already_present')
    raise SystemExit(0)

# Insert in the TLS server block just before its final closing brace.
# This vhost is dedicated to codexbridge-https, so the last non-whitespace
# closing brace belongs to the server block.
pos=text.rfind('}')
if pos < 0:
    raise SystemExit('cannot locate server closing brace')

paths=[
    f'/.well-known/oauth-authorization-server/{path}',
    f'/{path}/.well-known/oauth-authorization-server',
    f'/{path}/.well-known/openid-configuration',
    f'/.well-known/openid-configuration/{path}',
]
block='\n    '+marker+'\n'
for route in paths:
    block += f'''    location = {route} {{\n        default_type application/json;\n        add_header Cache-Control "no-store, no-cache, must-revalidate, max-age=0" always;\n        add_header Pragma "no-cache" always;\n        add_header Expires "0" always;\n        return 200 '{meta}';\n    }}\n\n'''
text=text[:pos]+block+text[pos:]
p.write_text(text)
print('nginx_alias=installed')
PY

sudo cp "$TMP" "$VHOST"
rm -f "$TMP"
sudo nginx -t
sudo systemctl reload nginx
REMOTE

echo "== validate fresh discovery paths =="
for path in \
  "/.well-known/oauth-authorization-server/${ISSUER_PATH}" \
  "/${ISSUER_PATH}/.well-known/oauth-authorization-server" \
  "/${ISSUER_PATH}/.well-known/openid-configuration" \
  "/.well-known/openid-configuration/${ISSUER_PATH}"
do
  echo "-- $path --"
  body="$(curl -fsS -H 'Cache-Control: no-cache' "${PUBLIC_ORIGIN}${path}")"
  printf '%s\n' "$body"
  python3 - "$body" "$FRESH_ISSUER" <<'PY'
import json,sys
obj=json.loads(sys.argv[1])
expected=sys.argv[2]
assert obj.get('issuer') == expected, obj
assert 'S256' in obj.get('code_challenge_methods_supported', []), obj
assert obj.get('authorization_endpoint','').endswith('/oauth/authorize'), obj
assert obj.get('token_endpoint','').endswith('/oauth/token'), obj
print('metadata_ok=yes')
PY
done

echo "== verify original MCP and OAuth remain healthy =="
curl -fsS "${PUBLIC_ORIGIN}/health"
echo
curl -fsS "${PUBLIC_ORIGIN}/.well-known/oauth-authorization-server" | python3 -c 'import json,sys; d=json.load(sys.stdin); assert "S256" in d.get("code_challenge_methods_supported",[]); print("original_oauth_ok=yes")'

cat <<EOF
CHATGPT_PKCE_FRESH_ALIAS_READY
Use these ChatGPT manual OAuth values:
Authorization server base: ${FRESH_ISSUER}
Auth URL: ${PUBLIC_ORIGIN}/oauth/authorize
Token URL: ${PUBLIC_ORIGIN}/oauth/token
Resource: ${PUBLIC_ORIGIN}/mcp
Client ID: chatgpt-codexbridge
Token endpoint auth method: none
EOF

git add "$RESULT"
if ! git diff --cached --quiet; then
  git commit -m "results: publish fresh ChatGPT PKCE OAuth alias"
  git push origin development
fi
