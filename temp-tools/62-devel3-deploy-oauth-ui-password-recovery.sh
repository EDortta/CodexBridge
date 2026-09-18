#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(git rev-parse --show-toplevel)"
cd "$REPO_ROOT"

STAMP="$(date -u +%Y%m%d-%H%M%SZ)"
OUT="temp-tools/results/${STAMP}-deploy-oauth-ui-password-recovery.txt"
mkdir -p temp-tools/results
exec > >(tee "$OUT") 2>&1
source temp-tools/lib/result-publisher.sh

HOST="codexbridge.inovacaosistemas.com.br"
FRIDA=(ssh -p 2200 -o StrictHostKeyChecking=accept-new esteban@frida.inovacaosistemas.com.br)
SCP=(scp -P 2200 -o StrictHostKeyChecking=accept-new)

echo "== Deploy CodexBridge OAuth UI + password recovery =="
echo "utc=$(date -u +%FT%TZ)"

echo "== local source sanity =="
python3 -m py_compile \
  gateway/app/main.py \
  gateway/app/core/users.py \
  gateway/app/api/routes/password_recovery.py
grep -q 'Forgot password?' gateway/app/main.py
grep -q 'set_user_password' gateway/app/core/users.py
grep -q '/oauth/password/forgot' gateway/app/api/routes/password_recovery.py
echo "source_sanity=ok"

echo "== upload staged files to Frida =="
"${SCP[@]}" gateway/app/main.py esteban@frida.inovacaosistemas.com.br:/tmp/codexbridge-main.py
"${SCP[@]}" gateway/app/core/users.py esteban@frida.inovacaosistemas.com.br:/tmp/codexbridge-users.py
"${SCP[@]}" gateway/app/api/routes/password_recovery.py esteban@frida.inovacaosistemas.com.br:/tmp/codexbridge-password-recovery.py

echo "== backup + install + restart gateway =="
"${FRIDA[@]}" 'bash -s' <<'REMOTE'
set -euo pipefail
STAMP="$(date -u +%Y%m%d-%H%M%SZ)"
BACKUP="/var/backups/codex-bridge/oauth-ui-${STAMP}"
sudo mkdir -p "$BACKUP"
sudo cp -a /opt/codex-bridge/gateway/app/main.py "$BACKUP/main.py"
sudo cp -a /opt/codex-bridge/gateway/app/core/users.py "$BACKUP/users.py"
if sudo test -f /opt/codex-bridge/gateway/app/api/routes/password_recovery.py; then
  sudo cp -a /opt/codex-bridge/gateway/app/api/routes/password_recovery.py "$BACKUP/password_recovery.py"
fi
sudo install -o codexbridge -g codexbridge -m 0644 /tmp/codexbridge-main.py /opt/codex-bridge/gateway/app/main.py
sudo install -o codexbridge -g codexbridge -m 0644 /tmp/codexbridge-users.py /opt/codex-bridge/gateway/app/core/users.py
sudo install -o codexbridge -g codexbridge -m 0644 /tmp/codexbridge-password-recovery.py /opt/codex-bridge/gateway/app/api/routes/password_recovery.py
rm -f /tmp/codexbridge-main.py /tmp/codexbridge-users.py /tmp/codexbridge-password-recovery.py
sudo -u codexbridge /opt/codex-bridge/.venv/bin/python3 -m py_compile \
  /opt/codex-bridge/gateway/app/main.py \
  /opt/codex-bridge/gateway/app/core/users.py \
  /opt/codex-bridge/gateway/app/api/routes/password_recovery.py
sudo systemctl restart codex-bridge-gateway.service
sleep 3
sudo systemctl is-active codex-bridge-gateway.service
echo "backup=$BACKUP"
REMOTE

echo "== external health from devel3 =="
curl -fsS --connect-timeout 8 --max-time 20 "https://${HOST}/health"
echo

echo "== external OAuth form from devel3 =="
AUTH_HTML="$(curl -fsS --get --connect-timeout 8 --max-time 20 \
  --data-urlencode 'response_type=code' \
  --data-urlencode 'client_id=chatgpt-codexbridge' \
  --data-urlencode 'redirect_uri=https://chatgpt.com/callback' \
  --data-urlencode 'scope=codexbridge.read' \
  --data-urlencode 'state=cb62' \
  --data-urlencode 'code_challenge=E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM' \
  --data-urlencode 'code_challenge_method=S256' \
  "https://${HOST}/oauth/authorize")"
printf '%s' "$AUTH_HTML" | grep -q 'Authorize ChatGPT'
printf '%s' "$AUTH_HTML" | grep -q 'Forgot password?'
printf '%s' "$AUTH_HTML" | grep -q 'Continue to ChatGPT'
printf '%s' "$AUTH_HTML" | grep -q 'Secure OAuth authorization'
echo "oauth_ui_external=ok"

echo "== external password recovery form =="
FORGOT_HTML="$(curl -fsS --connect-timeout 8 --max-time 20 "https://${HOST}/oauth/password/forgot")"
printf '%s' "$FORGOT_HTML" | grep -q 'Recover your password'
printf '%s' "$FORGOT_HTML" | grep -q 'Send recovery link'
echo "password_recovery_form_external=ok"

echo "== legacy 8443 compatibility still serves new UI =="
AUTH_8443="$(curl -fsS --get --connect-timeout 8 --max-time 20 \
  --data-urlencode 'response_type=code' \
  --data-urlencode 'client_id=chatgpt-codexbridge' \
  --data-urlencode 'redirect_uri=https://chatgpt.com/callback' \
  --data-urlencode 'scope=codexbridge.read' \
  --data-urlencode 'state=cb62legacy' \
  --data-urlencode 'code_challenge=E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM' \
  --data-urlencode 'code_challenge_method=S256' \
  "https://${HOST}:8443/oauth/authorize")"
printf '%s' "$AUTH_8443" | grep -q 'Authorize ChatGPT'
echo "legacy_8443_ui=ok"

echo "CODEXBRIDGE_OAUTH_UI_PASSWORD_RECOVERY_DEPLOYED"
