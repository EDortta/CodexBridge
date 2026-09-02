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

# The gateway refuses to start when a migration adds a COLUMN and it has not
# been applied (gateway/app/db/schema_guard.py REQUIRED_COLUMNS /
# FORBIDDEN_COLUMNS), and the unit restarts every 5s, so skipping this can turn
# a routine upgrade into a crash loop.
#
# A migration that only adds TABLES fails silently instead — 0006, 0007 and
# 0008 are all of that shape. startup runs Base.metadata.create_all one
# statement before check_schema, so the gateway creates the missing tables
# itself and starts: no indexes, no column defaults from the .sql, and no
# schema_migrations row. Nothing warns. Do not read a clean start as "the
# migrations are applied" — see docs/api/README.md, "Deploy needs migration
# 0008", and tests/unit/test_schema_guard.py.
#
# Applying it is NOT automated on purpose: migrating a live database is an
# operator decision, not a side effect of a deploy.
echo
echo "ANTES de (re)iniciar o gateway, aplique as migrations:"
echo "  DBURL=\$(sudo sed -n 's/^CODEX_BRIDGE_DATABASE_URL=//p' /etc/codex-bridge/env | head -1)"
echo "  sudo -u codexbridge /opt/codex-bridge/.venv/bin/python \\"
echo "      /opt/codex-bridge/scripts/apply_migrations.py --database-url \"\$DBURL\" --dry-run"
echo
echo "NAO use '. /etc/codex-bridge/env': o formato do EnvironmentFile permite"
echo "valor com espaco sem aspas, que o bash tenta executar."
echo
echo "Banco criado antes do runner (todos os atuais) precisa uma vez de:"
echo "  ... apply_migrations.py --database-url \"\$DBURL\" --mark-applied 0001_init.sql"
echo "Detalhes: docs/installation.md, passo 9."
