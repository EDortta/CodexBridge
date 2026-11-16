PASSWORD=$(cat .credentials/codex-bridge-initial-admin-password.ini | grep "PASSWORD" | awk -F= '{ print $2 }')
BASE="https://codexbridge.inovacaosistemas.com.br"

RESPONSE=$(curl -fsS \
  -X POST "$BASE/api/v1/auth/sign-in" \
  -H "Content-Type: application/json" \
  -d "$(jq -n \
    --arg u "esteban" \
    --arg p "$PASSWORD" \
    '{username:$u,password:$p}')")

unset PASSWORD

export CODEXBRIDGE_ADMIN_TOKEN=$(
  jq -r '.accessToken // empty' <<< "$RESPONSE"
)

unset RESPONSE

if [ -z "$CODEXBRIDGE_ADMIN_TOKEN" ]; then
  echo "ERRO: token não recebido"
else
  echo "Login realizado; token recebido."
fi
