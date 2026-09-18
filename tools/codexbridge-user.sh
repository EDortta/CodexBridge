#!/usr/bin/env bash
set -euo pipefail

HOST="frida.inovacaosistemas.com.br"
PORT="2200"
REMOTE_USER="esteban"

usage() {
  cat <<'EOF'
Usage:
  tools/codexbridge-user.sh --user USERNAME --email EMAIL [--create] [--admin]

The password is prompted on Frida itself and never appears in shell history.
EOF
}

ARGS=()
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

REMOTE_CMD=(sudo python3 /tmp/codexbridge-user.py)
REMOTE_CMD+=("${ARGS[@]}")

ssh -tt -p "$PORT" -o StrictHostKeyChecking=accept-new \
  "$REMOTE_USER@$HOST" "${REMOTE_CMD[@]}"

ssh -p "$PORT" -o StrictHostKeyChecking=accept-new "$REMOTE_USER@$HOST" \
  'rm -f /tmp/codexbridge-user.py; sudo systemctl restart codex-bridge-gateway.service; sleep 2; sudo systemctl is-active codex-bridge-gateway.service'
