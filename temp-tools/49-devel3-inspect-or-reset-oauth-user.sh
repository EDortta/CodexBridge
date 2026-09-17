#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(git rev-parse --show-toplevel)"
cd "$REPO_ROOT"

STAMP="$(date -u +%Y%m%d-%H%M%SZ)"
RESULT="temp-tools/results/${STAMP}-oauth-user-inspect.txt"
mkdir -p temp-tools/results
exec > >(tee "$RESULT") 2>&1

HOST="codexbridge.inovacaosistemas.com.br"

cat <<'EOF'
== Inspect CodexBridge OAuth login account ==
This script never prints password hashes or secrets.
It checks both likely ingress hosts:
  - T610 via public SSH :22
  - Frida via public SSH :2200
It identifies where the active gateway/user registry lives, lists only user_id/email/enabled/roles,
and optionally lets you reset one password interactively without writing the password to GitHub.
EOF

echo "utc=$(date -u +%FT%TZ)"

echo "== public OAuth/MCP identity =="
for url in \
  "https://${HOST}/.well-known/oauth-authorization-server" \
  "https://${HOST}/.well-known/oauth-protected-resource/mcp"
do
  echo "-- $url --"
  curl -fsS "$url" | python3 -m json.tool || true
done

probe_remote() {
  local label="$1" port="$2"
  echo "== probe ${label} (:${port}) =="
  ssh -o BatchMode=yes -o StrictHostKeyChecking=accept-new -o ConnectTimeout=8 -p "$port" "esteban@${HOST}" 'bash -s' <<'REMOTE' || return 1
set -euo pipefail
printf 'hostname='; hostname
if systemctl cat codex-bridge-gateway.service >/dev/null 2>&1; then
  echo 'gateway_unit=present'
  printf 'gateway_active='; systemctl is-active codex-bridge-gateway.service 2>/dev/null || true
else
  echo 'gateway_unit=absent'
fi
ENV=/etc/codex-bridge/env
if [ -r "$ENV" ] || sudo test -r "$ENV" 2>/dev/null; then
  echo 'env_file=present'
  PUB=$(sudo sed -n 's/^CODEX_BRIDGE_PUBLIC_BASE_URL=//p' "$ENV" | head -1)
  REG=$(sudo sed -n 's/^CODEX_BRIDGE_USER_REGISTRY_FILE=//p' "$ENV" | head -1)
  [ -n "$REG" ] || REG=/etc/codex-bridge/users.json
  echo "public_base_url=${PUB:-<unset>}"
  echo "user_registry_file=$REG"
  if sudo test -r "$REG" 2>/dev/null; then
    echo 'user_registry=readable'
    sudo python3 - "$REG" <<'PY'
import json,sys
p=sys.argv[1]
data=json.load(open(p))
users=data.get('users', data if isinstance(data,list) else [])
for u in users:
    print(json.dumps({
      'user_id': u.get('user_id'),
      'email': u.get('email'),
      'enabled': u.get('enabled', True),
      'roles': u.get('roles', []),
    }, ensure_ascii=False))
PY
  else
    echo 'user_registry=missing_or_unreadable'
  fi
else
  echo 'env_file=missing'
fi
REMOTE
}

T610_OK=0
FRIDA_OK=0
probe_remote T610 22 && T610_OK=1 || true
probe_remote Frida 2200 && FRIDA_OK=1 || true

echo "== choose active gateway host =="
TARGET_PORT=""
if [ "$T610_OK" = 1 ]; then
  if ssh -o BatchMode=yes -o StrictHostKeyChecking=accept-new -o ConnectTimeout=8 -p 22 "esteban@${HOST}" "systemctl is-active --quiet codex-bridge-gateway.service" 2>/dev/null; then
    TARGET_PORT=22
    echo 'target=T610'
  fi
fi
if [ -z "$TARGET_PORT" ] && [ "$FRIDA_OK" = 1 ]; then
  if ssh -o BatchMode=yes -o StrictHostKeyChecking=accept-new -o ConnectTimeout=8 -p 2200 "esteban@${HOST}" "systemctl is-active --quiet codex-bridge-gateway.service" 2>/dev/null; then
    TARGET_PORT=2200
    echo 'target=Frida'
  fi
fi

if [ -z "$TARGET_PORT" ]; then
  echo 'target=undetermined'
  echo 'No active codex-bridge-gateway.service was detected on either host.'
  echo 'CODEXBRIDGE_OAUTH_USER_INSPECT_COMPLETE'
  exit 0
fi

if [ ! -t 0 ]; then
  echo 'interactive_reset=skipped_non_tty'
  echo 'CODEXBRIDGE_OAUTH_USER_INSPECT_COMPLETE'
  exit 0
fi

printf '\nReset a password now? [y/N] '
read -r ANSWER
case "$ANSWER" in y|Y|yes|YES) ;; *)
  echo 'password_reset=skipped'
  echo 'CODEXBRIDGE_OAUTH_USER_INSPECT_COMPLETE'
  git add "$RESULT"
  if ! git diff --cached --quiet; then
    git commit -m "results: inspect CodexBridge OAuth users"
    git push origin development
  fi
  exit 0
esac

printf 'User ID or email to reset: '
read -r USER_KEY
read -r -s -p 'New password: ' NEW_PASS; echo
read -r -s -p 'Confirm new password: ' NEW_PASS2; echo
if [ "$NEW_PASS" != "$NEW_PASS2" ]; then
  echo 'password_reset=aborted_mismatch'
  exit 2
fi
if [ ${#NEW_PASS} -lt 12 ]; then
  echo 'password_reset=aborted_too_short_min_12'
  exit 2
fi

PASS_B64=$(printf '%s' "$NEW_PASS" | base64 -w0)
unset NEW_PASS NEW_PASS2

ssh -o StrictHostKeyChecking=accept-new -p "$TARGET_PORT" "esteban@${HOST}" \
  "USER_KEY=$(printf %q "$USER_KEY") PASS_B64=$(printf %q "$PASS_B64") bash -s" <<'REMOTE'
set -euo pipefail
ENV=/etc/codex-bridge/env
REG=$(sudo sed -n 's/^CODEX_BRIDGE_USER_REGISTRY_FILE=//p' "$ENV" | head -1)
[ -n "$REG" ] || REG=/etc/codex-bridge/users.json
BACKUP="${REG}.bak-$(date -u +%Y%m%d-%H%M%SZ)"
sudo cp "$REG" "$BACKUP"
TMP=$(mktemp)
sudo cp "$REG" "$TMP"
sudo chown "$(id -u):$(id -g)" "$TMP"
python3 - "$TMP" "$USER_KEY" "$PASS_B64" <<'PY'
import base64, hashlib, json, os, sys
p,key,p64=sys.argv[1:]
password=base64.b64decode(p64).decode()
data=json.load(open(p))
users=data.get('users', data if isinstance(data,list) else None)
if users is None:
    raise SystemExit('Unsupported users.json shape')
match=None
for u in users:
    if u.get('user_id')==key or u.get('email')==key:
        match=u; break
if match is None:
    raise SystemExit('User not found')
# Match CodexBridge PBKDF2 format used by gateway users.py/tests.
iterations=310000
salt=os.urandom(16)
digest=hashlib.pbkdf2_hmac('sha256', password.encode(), salt, iterations)
match['password_hash']=f'pbkdf2_sha256${iterations}${base64.b64encode(salt).decode()}${base64.b64encode(digest).decode()}'
with open(p,'w') as f:
    json.dump(data,f,indent=2)
    f.write('\n')
print('password_hash_updated=yes')
print('user_id='+str(match.get('user_id')))
print('email='+str(match.get('email')))
PY
sudo install -m 600 -o root -g root "$TMP" "$REG"
rm -f "$TMP"
sudo systemctl restart codex-bridge-gateway.service
sudo systemctl is-active --quiet codex-bridge-gateway.service
echo "backup=$BACKUP"
echo 'gateway_restart=ok'
REMOTE

echo 'password_reset=ok'
echo 'CODEXBRIDGE_OAUTH_USER_INSPECT_COMPLETE'

# Result file contains only metadata, never the password/hash.
git add "$RESULT"
if ! git diff --cached --quiet; then
  git commit -m "results: inspect CodexBridge OAuth users"
  git push origin development
fi
