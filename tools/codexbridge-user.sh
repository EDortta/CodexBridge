#!/usr/bin/env bash
set -euo pipefail

HOST="frida.inovacaosistemas.com.br"
PORT="2200"
REMOTE_USER="esteban"

usage() {
  cat <<'EOF'
Usage:
  tools/codexbridge-user.sh --user USERNAME --email EMAIL [--create] [--admin]
  tools/codexbridge-user.sh --list

The password is prompted on Frida itself and never appears in shell history.
EOF
}

ARGS=()
READ_ONLY=0
while [[ $# -gt 0 ]]; do
  case "$1" in
    --user|--email)
      [[ $# -ge 2 ]] || { usage >&2; exit 2; }
      ARGS+=("$1" "$2")
      shift 2
      ;;
    --create|--admin)
      ARGS+=("$1")
      shift
      ;;
    --list)
      ARGS+=("$1")
      READ_ONLY=1
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown argument: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

scp -P "$PORT" -o StrictHostKeyChecking=accept-new \
  tools/codexbridge-user.py \
  "$REMOTE_USER@$HOST:/tmp/codexbridge-user.py"

REMOTE_REGISTRY=$(ssh -T -p "$PORT" -o StrictHostKeyChecking=accept-new \
  "$REMOTE_USER@$HOST" \
  "sudo awk -F= '/^CODEX_BRIDGE_USER_REGISTRY_FILE=/{print \$2; exit}' /etc/codex-bridge/env")
REMOTE_REGISTRY=${REMOTE_REGISTRY:-/etc/codex-bridge/users.json}

REMOTE_CMD=(sudo python3 /tmp/codexbridge-user.py --registry "$REMOTE_REGISTRY")
REMOTE_CMD+=("${ARGS[@]}")

ssh -tt -p "$PORT" -o StrictHostKeyChecking=accept-new \
  "$REMOTE_USER@$HOST" "${REMOTE_CMD[@]}"

if [[ "$READ_ONLY" -eq 1 ]]; then
  ssh -p "$PORT" -o StrictHostKeyChecking=accept-new "$REMOTE_USER@$HOST" \
    'rm -f /tmp/codexbridge-user.py'
  exit 0
fi

ssh -p "$PORT" -o StrictHostKeyChecking=accept-new "$REMOTE_USER@$HOST" \
  'rm -f /tmp/codexbridge-user.py; sudo systemctl restart codex-bridge-gateway.service; sleep 2; sudo systemctl is-active codex-bridge-gateway.service'
