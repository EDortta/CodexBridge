#!/usr/bin/env bash
set -euo pipefail

ROOT="$(git rev-parse --show-toplevel)"
cd "$ROOT"

LEGACY_ROOT="/home/esteban/.local/share/codex-bridge"
AGENT_ENV_DIR="/etc/codex-bridge-agent"
AGENT_ENV="$AGENT_ENV_DIR/env"
AGENT_PROJECTS="$AGENT_ENV_DIR/projects.json"
AGENT_UNIT="codex-bridge-agent.service"

if ! pgrep -af "$LEGACY_ROOT/.venv/bin/python -m agent.codex_bridge_agent.service" >/dev/null; then
  echo "ERROR: agente legado não está rodando em $LEGACY_ROOT" >&2
  exit 2
fi

sudo mkdir -p "$AGENT_ENV_DIR"

# Reuse legacy config only if it exists; do not invent credentials.
CANDIDATES=(
  "$LEGACY_ROOT/.env"
  "$LEGACY_ROOT/agent.env"
  "$HOME/.config/codex-bridge-agent/env"
)
SRC_ENV=""
for f in "${CANDIDATES[@]}"; do
  if [[ -f "$f" ]]; then SRC_ENV="$f"; break; fi
done
if [[ -z "$SRC_ENV" ]]; then
  echo "ERROR: config legado não encontrado. Procurei: ${CANDIDATES[*]}" >&2
  exit 2
fi

sudo install -m 0600 -o root -g root "$SRC_ENV" "$AGENT_ENV"

# Determine allowed projects file from env; otherwise reuse a legacy projects file if present.
ALLOWED_FILE="$(sed -n 's/^CODEX_BRIDGE_AGENT_ALLOWED_PROJECTS_FILE=//p' "$SRC_ENV" | tail -1)"
if [[ -n "$ALLOWED_FILE" && -f "$ALLOWED_FILE" ]]; then
  sudo install -m 0644 -o root -g root "$ALLOWED_FILE" "$AGENT_PROJECTS"
elif [[ -f "$LEGACY_ROOT/projects.json" ]]; then
  sudo install -m 0644 -o root -g root "$LEGACY_ROOT/projects.json" "$AGENT_PROJECTS"
elif [[ -f "$HOME/.config/codex-bridge-agent/projects.json" ]]; then
  sudo install -m 0644 -o root -g root "$HOME/.config/codex-bridge-agent/projects.json" "$AGENT_PROJECTS"
else
  echo "ERROR: projects.json legado não encontrado" >&2
  exit 2
fi

# Stop the legacy user-owned process only after config has been copied safely.
LEGACY_PIDS="$(pgrep -f "$LEGACY_ROOT/.venv/bin/python -m agent.codex_bridge_agent.service" || true)"
if [[ -n "$LEGACY_PIDS" ]]; then
  kill $LEGACY_PIDS || true
  sleep 2
fi

# Hand off to canonical deploy script.
bash temp-tools/18-devel3-deploy-chatgpt-ready-frida-ssh.sh
