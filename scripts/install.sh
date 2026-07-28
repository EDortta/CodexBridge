#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TARGET_DIR="${TARGET_DIR:-/opt/codex-bridge}"

mkdir -p "$TARGET_DIR"
rsync -a --delete \
  --exclude '.git' \
  --exclude '__pycache__' \
  "$ROOT_DIR"/ "$TARGET_DIR"/

python3 -m venv "$TARGET_DIR/.venv"
"$TARGET_DIR/.venv/bin/pip" install --upgrade pip
"$TARGET_DIR/.venv/bin/pip" install "$TARGET_DIR"

echo "Projeto sincronizado em $TARGET_DIR"
echo "Ajuste /etc/codex-bridge/env e /etc/codex-bridge-agent/env antes de habilitar os servicos."
