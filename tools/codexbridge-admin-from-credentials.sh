#!/usr/bin/env bash
set -euo pipefail

CREDENTIALS_FILE="${1:-.credentials/codex-bridge-initial-admin-password.ini}"
HOST="frida.inovacaosistemas.com.br"
PORT="2200"
REMOTE_USER="esteban"
REMOTE_SCRIPT="/tmp/codexbridge-user.py"
BASE_URL="https://codexbridge.inovacaosistemas.com.br:8443"

die() {
  echo "ERROR: $*" >&2
  exit 1
}

[[ -f "$CREDENTIALS_FILE" ]] || die "arquivo de credenciais não encontrado: $CREDENTIALS_FILE"
[[ "$(stat -c '%a' "$CREDENTIALS_FILE")" == "600" ]] || \
  die "o arquivo de credenciais precisa ter permissão 600"

ini_value() {
  local key="$1"
  awk -v key="$key" '
    $0 ~ "^[[:space:]]*" key "[[:space:]]*=" {
      sub("^[[:space:]]*" key "[[:space:]]*=([[:space:]]*)", "")
      print
      exit
    }
  ' "$CREDENTIALS_FILE"
}

USER_ID="$(ini_value CODEXBRIDGE_USER)"
EMAIL="$(ini_value CODEXBRIDGE_EMAIL)"
PASSWORD="$(ini_value CODEXBRIDGE_PASSWORD)"
[[ -n "$USER_ID" && -n "$EMAIL" && -n "$PASSWORD" ]] || \
  die "o arquivo precisa definir CODEXBRIDGE_USER, CODEXBRIDGE_EMAIL e CODEXBRIDGE_PASSWORD"

cleanup_remote() {
  ssh -T -p "$PORT" -o StrictHostKeyChecking=accept-new \
    "$REMOTE_USER@$HOST" "rm -f '$REMOTE_SCRIPT'" >/dev/null 2>&1 || true
}
trap cleanup_remote EXIT

echo "Copiando o helper para o Frida..."
scp -q -P "$PORT" -o StrictHostKeyChecking=accept-new \
  tools/codexbridge-user.py "$REMOTE_USER@$HOST:$REMOTE_SCRIPT"

REMOTE_REGISTRY=$(ssh -T -p "$PORT" -o StrictHostKeyChecking=accept-new \
  "$REMOTE_USER@$HOST" \
  "sudo awk -F= '/^CODEX_BRIDGE_USER_REGISTRY_FILE=/{print \$2; exit}' /etc/codex-bridge/env")
REMOTE_REGISTRY=${REMOTE_REGISTRY:-/etc/codex-bridge/users.json}

echo "Atualizando o usuário no registry efetivo..."
printf '%s\n%s\n' "$PASSWORD" "$PASSWORD" \
  | ssh -T -p "$PORT" -o StrictHostKeyChecking=accept-new \
      "$REMOTE_USER@$HOST" \
      "sudo python3 '$REMOTE_SCRIPT' --registry '$REMOTE_REGISTRY' --user '$USER_ID' --email '$EMAIL' --admin --password-stdin"

echo "Confirmando a conta sem exibir hash..."
ssh -T -p "$PORT" -o StrictHostKeyChecking=accept-new \
  "$REMOTE_USER@$HOST" "sudo python3 '$REMOTE_SCRIPT' --registry '$REMOTE_REGISTRY' --list"

echo "Testando o fluxo OAuth usado pelo ChatGPT..."
TMP_DIR="$(mktemp -d)"
trap 'rm -rf "$TMP_DIR"; cleanup_remote' EXIT
chmod 700 "$TMP_DIR"
printf '%s' "$PASSWORD" > "$TMP_DIR/password"
chmod 600 "$TMP_DIR/password"

read -r VERIFIER CHALLENGE <<EOF
$(python3 - <<'PY'
import base64
import hashlib
import secrets

verifier = base64.urlsafe_b64encode(secrets.token_bytes(32)).decode().rstrip("=")
challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
print(verifier, challenge)
PY
)
EOF

curl -fsS --silent --show-error --output /dev/null \
  --cookie-jar "$TMP_DIR/cookies" --cookie "$TMP_DIR/cookies" \
  --get "$BASE_URL/oauth/authorize" \
  --data-urlencode 'response_type=code' \
  --data-urlencode 'client_id=chatgpt-codexbridge' \
  --data-urlencode 'redirect_uri=https://chatgpt.com/codexbridge-test' \
  --data-urlencode 'scope=codexbridge.read' \
  --data-urlencode "state=$USER_ID" \
  --data-urlencode "code_challenge=$CHALLENGE" \
  --data-urlencode 'code_challenge_method=S256' \
  --data-urlencode "resource=$BASE_URL/mcp"

HTTP_CODE="$(curl -sS --show-error --output "$TMP_DIR/response" --dump-header "$TMP_DIR/headers" \
  --cookie "$TMP_DIR/cookies" --cookie-jar "$TMP_DIR/cookies" \
  --write-out '%{http_code}' \
  --data-urlencode 'response_type=code' \
  --data-urlencode 'client_id=chatgpt-codexbridge' \
  --data-urlencode 'redirect_uri=https://chatgpt.com/codexbridge-test' \
  --data-urlencode 'scope=codexbridge.read' \
  --data-urlencode "state=$USER_ID" \
  --data-urlencode "code_challenge=$CHALLENGE" \
  --data-urlencode 'code_challenge_method=S256' \
  --data-urlencode "username=$USER_ID" \
  --data-urlencode "password@$TMP_DIR/password" \
  "$BASE_URL/oauth/authorize")"

case "$HTTP_CODE" in
  302)
    echo "OAuth: senha aceita e autorização criada (HTTP 302)."
    ;;
  *)
    echo "OAuth: falhou com HTTP $HTTP_CODE."
    if grep -q 'Invalid username or password' "$TMP_DIR/response"; then
      echo "OAuth: o gateway rejeitou usuário ou senha."
    elif grep -q 'Requested scopes are not allowed' "$TMP_DIR/response"; then
      echo "OAuth: senha aceita, mas o escopo solicitado não foi permitido."
    fi
    exit 1
    ;;
esac
