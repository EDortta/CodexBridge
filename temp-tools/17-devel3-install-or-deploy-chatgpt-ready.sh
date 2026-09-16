#!/usr/bin/env bash
set -euo pipefail

ROOT="$(git rev-parse --show-toplevel)"
cd "$ROOT"

FRIDA_HOST="${FRIDA_HOST:-frida}"
REMOTE_ROOT="/opt/codex-bridge"
LOCAL_ROOT="/opt/codex-bridge"
AGENT_UNIT="codex-bridge-agent.service"
GATEWAY_UNIT="codex-bridge-gateway.service"

if [[ "$(git branch --show-current)" != "development" ]]; then
  echo "ERROR: rode a partir da branch development" >&2
  exit 2
fi
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

command -v rsync >/dev/null || { echo "ERROR: rsync não encontrado" >&2; exit 2; }
command -v ssh >/dev/null || { echo "ERROR: ssh não encontrado" >&2; exit 2; }

echo "== CodexBridge deploy/install ChatGPT-ready =="
echo "commit=$LOCAL_HEAD"

echo "== preflight: Frida gateway =="
ssh "$FRIDA_HOST" "sudo systemctl cat '$GATEWAY_UNIT' >/dev/null"
ssh "$FRIDA_HOST" 'sudo test -f /etc/codex-bridge/env'
MCP_MODE="$(ssh "$FRIDA_HOST" "sudo sed -n 's/^CODEX_BRIDGE_MCP_AUTH_MODE=//p' /etc/codex-bridge/env | head -1")"
PUBLIC_URL="$(ssh "$FRIDA_HOST" "sudo sed -n 's/^CODEX_BRIDGE_PUBLIC_BASE_URL=//p' /etc/codex-bridge/env | head -1")"
DBURL="$(ssh "$FRIDA_HOST" "sudo sed -n 's/^CODEX_BRIDGE_DATABASE_URL=//p' /etc/codex-bridge/env | head -1")"
if [[ "$MCP_MODE" != "oauth" ]]; then
  echo "ERROR: Frida não está com CODEX_BRIDGE_MCP_AUTH_MODE=oauth (valor: ${MCP_MODE:-<vazio>})." >&2
  exit 2
fi
[[ -n "$PUBLIC_URL" ]] || { echo "ERROR: CODEX_BRIDGE_PUBLIC_BASE_URL ausente em Frida" >&2; exit 2; }
[[ -n "$DBURL" ]] || { echo "ERROR: CODEX_BRIDGE_DATABASE_URL ausente em Frida" >&2; exit 2; }

echo "== preflight: devel3 agent installation =="
if sudo systemctl cat "$AGENT_UNIT" >/dev/null 2>&1; then
  echo "agent_unit=installed"
else
  echo "agent_unit=missing; will install canonical unit from repository"
  getent passwd codexbridge >/dev/null || {
    echo "ERROR: usuário codexbridge não existe em devel3; abortando antes de alterar o host." >&2
    exit 2
  }
  sudo test -f /etc/codex-bridge-agent/env || {
    echo "ERROR: /etc/codex-bridge-agent/env não existe; não vou inventar credenciais/configuração." >&2
    exit 2
  }
  sudo test -f /etc/codex-bridge-agent/projects.json || {
    echo "ERROR: /etc/codex-bridge-agent/projects.json não existe; não vou inventar bindings de projeto." >&2
    exit 2
  }
fi

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

echo "== deploy gateway to Frida =="
ssh "$FRIDA_HOST" "sudo mkdir -p '$REMOTE_ROOT' && sudo chown -R \$(id -un):\$(id -gn) '$REMOTE_ROOT'"
rsync -az "${RSYNC_EXCLUDES[@]}" ./ "$FRIDA_HOST:$REMOTE_ROOT/"
ssh "$FRIDA_HOST" "sudo chown -R codexbridge:codexbridge '$REMOTE_ROOT'"
ssh "$FRIDA_HOST" "if [ ! -x '$REMOTE_ROOT/.venv/bin/python' ]; then sudo -u codexbridge python3 -m venv '$REMOTE_ROOT/.venv'; fi"
ssh "$FRIDA_HOST" "sudo '$REMOTE_ROOT/.venv/bin/pip' install -q '$REMOTE_ROOT'"

echo "== gateway migrations =="
ssh "$FRIDA_HOST" "sudo -u codexbridge '$REMOTE_ROOT/.venv/bin/python' '$REMOTE_ROOT/scripts/apply_migrations.py' --database-url '$DBURL' --dry-run"
ssh "$FRIDA_HOST" "sudo -u codexbridge '$REMOTE_ROOT/.venv/bin/python' '$REMOTE_ROOT/scripts/apply_migrations.py' --database-url '$DBURL'"

echo "== restart gateway =="
ssh "$FRIDA_HOST" "sudo systemctl restart '$GATEWAY_UNIT' && sudo systemctl is-active --quiet '$GATEWAY_UNIT'"

echo "== deploy agent to devel3 =="
sudo mkdir -p "$LOCAL_ROOT"
sudo rsync -a "${RSYNC_EXCLUDES[@]}" ./ "$LOCAL_ROOT/"
sudo chown -R codexbridge:codexbridge "$LOCAL_ROOT"
if [[ ! -x "$LOCAL_ROOT/.venv/bin/python" ]]; then
  sudo -u codexbridge python3 -m venv "$LOCAL_ROOT/.venv"
fi
sudo "$LOCAL_ROOT/.venv/bin/pip" install -q "$LOCAL_ROOT"

if ! sudo systemctl cat "$AGENT_UNIT" >/dev/null 2>&1; then
  echo "== install canonical agent systemd unit =="
  sudo install -m 0644 deploy/systemd/codex-bridge-agent.service "/etc/systemd/system/$AGENT_UNIT"
  sudo systemctl daemon-reload
  sudo systemctl enable "$AGENT_UNIT"
fi

echo "== restart agent =="
sudo systemctl restart "$AGENT_UNIT"
sudo systemctl is-active --quiet "$AGENT_UNIT"

echo "== smoke: gateway =="
ssh "$FRIDA_HOST" 'curl -fsS http://127.0.0.1:18080/health >/dev/null'
curl -fsS "$PUBLIC_URL/health" >/dev/null

HTTP_CODE="$(curl -sS -o /tmp/codexbridge-mcp-smoke.json -w '%{http_code}' \
  -H 'Content-Type: application/json' \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{}}' \
  "$PUBLIC_URL/mcp")"
if [[ "$HTTP_CODE" != "200" && "$HTTP_CODE" != "401" ]]; then
  echo "ERROR: /mcp respondeu HTTP $HTTP_CODE" >&2
  cat /tmp/codexbridge-mcp-smoke.json >&2 || true
  exit 1
fi

echo "== smoke: services =="
sleep 2
sudo systemctl --no-pager --full status "$AGENT_UNIT" | sed -n '1,14p'
ssh "$FRIDA_HOST" "sudo systemctl --no-pager --full status '$GATEWAY_UNIT' | sed -n '1,14p'"

echo
echo "DEPLOY_OK"
echo "commit=$LOCAL_HEAD"
echo "public=$PUBLIC_URL"
echo "mcp_http=$HTTP_CODE"
echo "agent_unit=$AGENT_UNIT"
