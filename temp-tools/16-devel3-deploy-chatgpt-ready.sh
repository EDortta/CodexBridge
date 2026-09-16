#!/usr/bin/env bash
set -euo pipefail

ROOT="$(git rev-parse --show-toplevel)"
cd "$ROOT"

FRIDA_HOST="${FRIDA_HOST:-frida}"
REMOTE_ROOT="/opt/codex-bridge"
LOCAL_ROOT="/opt/codex-bridge"
PUBLIC_BASE="${CODEX_BRIDGE_PUBLIC_BASE_URL:-https://codexbridge.inovacaosistemas.com.br:8443}"

if [[ "$(git branch --show-current)" != "development" ]]; then
  echo "ERROR: rode a partir da branch development" >&2
  exit 2
fi

# Tracked changes must be clean. Untracked local operator files are ignored.
if ! git diff --quiet || ! git diff --cached --quiet; then
  echo "ERROR: há mudanças rastreadas locais; não vou fazer deploy por cima delas." >&2
  git status --short
  exit 2
fi

git fetch origin development >/dev/null
LOCAL_HEAD="$(git rev-parse HEAD)"
REMOTE_HEAD="$(git rev-parse origin/development)"
if [[ "$LOCAL_HEAD" != "$REMOTE_HEAD" ]]; then
  echo "ERROR: development local não coincide com origin/development." >&2
  echo "local=$LOCAL_HEAD"
  echo "origin=$REMOTE_HEAD"
  echo "Rode: git pull --ff-only origin development" >&2
  exit 2
fi

echo "== CodexBridge deploy ChatGPT-ready =="
echo "commit=$LOCAL_HEAD"
echo "gateway=$FRIDA_HOST:$REMOTE_ROOT"
echo "agent=$(hostname):$LOCAL_ROOT"

command -v rsync >/dev/null || { echo "ERROR: rsync não encontrado" >&2; exit 2; }
command -v ssh >/dev/null || { echo "ERROR: ssh não encontrado" >&2; exit 2; }

# Verify the two live units before touching files.
echo "== preflight: services =="
sudo systemctl cat codex-bridge-agent >/dev/null
ssh "$FRIDA_HOST" 'sudo systemctl cat codex-bridge-gateway >/dev/null'

# Verify the configured public MCP endpoint and DB settings exist on Frida.
echo "== preflight: Frida configuration =="
ssh "$FRIDA_HOST" 'test -f /etc/codex-bridge/env && sudo test -f /etc/codex-bridge/env'
MCP_MODE="$(ssh "$FRIDA_HOST" "sudo sed -n 's/^CODEX_BRIDGE_MCP_AUTH_MODE=//p' /etc/codex-bridge/env | head -1")"
PUBLIC_URL="$(ssh "$FRIDA_HOST" "sudo sed -n 's/^CODEX_BRIDGE_PUBLIC_BASE_URL=//p' /etc/codex-bridge/env | head -1")"
DBURL="$(ssh "$FRIDA_HOST" "sudo sed -n 's/^CODEX_BRIDGE_DATABASE_URL=//p' /etc/codex-bridge/env | head -1")"

if [[ "$MCP_MODE" != "oauth" ]]; then
  echo "ERROR: Frida não está em CODEX_BRIDGE_MCP_AUTH_MODE=oauth (valor: ${MCP_MODE:-<vazio>})." >&2
  exit 2
fi
if [[ -z "$PUBLIC_URL" ]]; then
  echo "ERROR: CODEX_BRIDGE_PUBLIC_BASE_URL não definido em Frida." >&2
  exit 2
fi
if [[ -z "$DBURL" ]]; then
  echo "ERROR: CODEX_BRIDGE_DATABASE_URL não definido em Frida." >&2
  exit 2
fi

echo "mcp_auth_mode=$MCP_MODE"
echo "public_base_url=$PUBLIC_URL"

RSYNC_EXCLUDES=(
  --exclude '.git/'
  --exclude '.venv/'
  --exclude '.claude-flow/'
  --exclude '.swarm/'
  --exclude 'ruvector.db'
  --exclude 'claude-handoff-*'
  --exclude 'coordination-status-*'
  --exclude 'temp-tools/results/'
  --exclude '__pycache__/'
  --exclude '*.pyc'
)

# Gateway: update application tree but do not delete host-local files.
echo "== deploy gateway to Frida =="
ssh "$FRIDA_HOST" "sudo mkdir -p '$REMOTE_ROOT' && sudo chown -R \$(id -un):\$(id -gn) '$REMOTE_ROOT'"
rsync -az "${RSYNC_EXCLUDES[@]}" ./ "$FRIDA_HOST:$REMOTE_ROOT/"
ssh "$FRIDA_HOST" "sudo chown -R codexbridge:codexbridge '$REMOTE_ROOT'"

# Reinstall package into the existing service venv so dependency/entrypoint changes are active.
echo "== install gateway package =="
ssh "$FRIDA_HOST" "sudo '$REMOTE_ROOT/.venv/bin/pip' install -q '$REMOTE_ROOT'"

# Migrations are intentionally explicit in this project. Dry-run first, then apply.
echo "== gateway migrations dry-run =="
ssh "$FRIDA_HOST" "sudo -u codexbridge '$REMOTE_ROOT/.venv/bin/python' '$REMOTE_ROOT/scripts/apply_migrations.py' --database-url '$DBURL' --dry-run"
echo "== gateway migrations apply =="
ssh "$FRIDA_HOST" "sudo -u codexbridge '$REMOTE_ROOT/.venv/bin/python' '$REMOTE_ROOT/scripts/apply_migrations.py' --database-url '$DBURL'"

# Restart gateway only after files/deps/migrations are ready.
echo "== restart gateway =="
ssh "$FRIDA_HOST" 'sudo systemctl restart codex-bridge-gateway && sudo systemctl is-active --quiet codex-bridge-gateway'

# Agent on devel3: copy current code to the service tree and refresh package.
echo "== deploy agent locally =="
sudo mkdir -p "$LOCAL_ROOT"
sudo rsync -a "${RSYNC_EXCLUDES[@]}" ./ "$LOCAL_ROOT/"
sudo chown -R codexbridge:codexbridge "$LOCAL_ROOT"
sudo "$LOCAL_ROOT/.venv/bin/pip" install -q "$LOCAL_ROOT"

echo "== restart agent =="
sudo systemctl restart codex-bridge-agent
sudo systemctl is-active --quiet codex-bridge-agent

# Local health, public health, and MCP discovery smoke checks.
echo "== smoke: gateway health =="
ssh "$FRIDA_HOST" 'curl -fsS http://127.0.0.1:18080/health >/dev/null'
curl -fsS "$PUBLIC_URL/health" >/dev/null

echo "== smoke: MCP initialize through public endpoint =="
HTTP_CODE="$(curl -sS -o /tmp/codexbridge-mcp-smoke.json -w '%{http_code}' \
  -H 'Content-Type: application/json' \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{}}' \
  "$PUBLIC_URL/mcp")"
# OAuth deployments may allow unauthenticated discovery (200) or demand auth (401).
if [[ "$HTTP_CODE" != "200" && "$HTTP_CODE" != "401" ]]; then
  echo "ERROR: /mcp respondeu HTTP $HTTP_CODE" >&2
  cat /tmp/codexbridge-mcp-smoke.json >&2 || true
  exit 1
fi

echo "== smoke: agent connection =="
sleep 2
sudo systemctl --no-pager --full status codex-bridge-agent | sed -n '1,12p'
ssh "$FRIDA_HOST" 'sudo systemctl --no-pager --full status codex-bridge-gateway | sed -n "1,12p"'

echo
echo "DEPLOY_OK"
echo "commit=$LOCAL_HEAD"
echo "public=$PUBLIC_URL"
echo "mcp_http=$HTTP_CODE"
echo "Gateway e Agent foram atualizados e reiniciados. Nginx não foi alterado nem reiniciado porque esta entrega não adiciona nova rota pública."
