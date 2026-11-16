#!/usr/bin/env bash
set -euo pipefail

HOST="frida.inovacaosistemas.com.br"
PORT="2200"
REMOTE_USER="esteban"
SERVICE="codex-bridge-gateway.service"

usage() {
  cat <<'EOF'
Uso:
  tools/codexbridge-auth-watch.sh

Acompanha, no Frida, o serviço do gateway e as requisições de autenticação do
Nginx. Deixe este comando aberto e tente entrar no aplicativo ou navegador em
outra janela. Interrompa com Ctrl-C.

Não mostra senha, token, corpo de requisição ou arquivo users.json.
EOF
}

case "${1:-}" in
  "") ;;
  -h|--help)
    usage
    exit 0
    ;;
  *)
    echo "Argumento desconhecido: $1" >&2
    usage >&2
    exit 2
    ;;
esac

echo "Conectando a ${REMOTE_USER}@${HOST}:${PORT}..."
echo "Tente autenticar agora; Ctrl-C encerra o acompanhamento."
echo

ssh -T -p "$PORT" -o StrictHostKeyChecking=accept-new \
  "$REMOTE_USER@$HOST" "sudo bash -s -- '$SERVICE'" <<'REMOTE'
set -u
SERVICE="$1"

cleanup() {
  jobs -pr | xargs -r sudo kill 2>/dev/null || true
}
trap cleanup EXIT INT TERM

echo "===== estado inicial ====="
sudo systemctl is-active "$SERVICE" || true
sudo systemctl --no-pager --full status "$SERVICE" | sed -n '1,14p' || true
echo
echo "===== acompanhando gateway e Nginx ====="
echo "[gateway] mensagens do serviço"

sudo journalctl --since "now" --follow --unit "$SERVICE" --output short-iso --no-pager \
  | sed 's/^/[gateway] /' &
JOURNAL_PID=$!

if [[ -e /var/log/nginx/access.log || -e /var/log/nginx/error.log ]]; then
  {
    sudo tail -F /var/log/nginx/access.log /var/log/nginx/error.log 2>/dev/null \
      | awk '
          /\/api\/v1\/auth\// || /\/oauth\// {
            print "[nginx] " $0
            fflush()
          }
        '
  } &
  NGINX_PID=$!
else
  echo "[nginx] arquivos de log padrão não encontrados"
  NGINX_PID=""
fi

wait "$JOURNAL_PID"
REMOTE
