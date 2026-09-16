#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(git rev-parse --show-toplevel)"
cd "$REPO_ROOT"

FRIDA_HOST="frida.inovacaosistemas.com.br"
FRIDA_USER="esteban"
FRIDA_PORT=2200
BASE="https://codexbridge.inovacaosistemas.com.br:8443"
TARGET_VERSION="0.2.0"
OUT="temp-tools/results/$(date -u +%Y%m%d-%H%M%SZ)-deploy-${TARGET_VERSION}.txt"
mkdir -p temp-tools/results
exec > >(tee "$OUT") 2>&1

echo "== Deploy CodexBridge ${TARGET_VERSION} =="
echo "utc=$(date -u +%Y-%m-%dT%H:%M:%SZ)"

echo "== sync local checkout =="
git pull --ff-only origin development

echo "== verify local version sources =="
PY_VERSION="$(python3 - <<'PY'
from gateway.app.version import APP_VERSION
print(APP_VERSION)
PY
)"
TOML_VERSION="$(python3 - <<'PY'
from pathlib import Path
import re
s=Path('pyproject.toml').read_text()
m=re.search(r'^version\s*=\s*"([^"]+)"', s, re.M)
print(m.group(1) if m else '')
PY
)"
echo "gateway_version=$PY_VERSION"
echo "pyproject_version=$TOML_VERSION"
[[ "$PY_VERSION" == "$TARGET_VERSION" && "$TOML_VERSION" == "$TARGET_VERSION" ]] || {
  echo "ERROR: local version sources are not both ${TARGET_VERSION}"
  exit 2
}

python3 -m pytest -q tests/unit/test_version_is_single_sourced.py tests/unit/test_security.py

echo "== stage release files for Frida =="
scp -P "$FRIDA_PORT" gateway/app/version.py pyproject.toml "$FRIDA_USER@$FRIDA_HOST:/tmp/"

ssh -p "$FRIDA_PORT" "$FRIDA_USER@$FRIDA_HOST" 'bash -s' <<'REMOTE'
set -euo pipefail
STAMP="$(date -u +%Y%m%d-%H%M%SZ)"
BACKUP="/var/backups/codex-bridge/release-$STAMP"
sudo mkdir -p "$BACKUP"

if sudo test -f /opt/codex-bridge/gateway/app/version.py; then
  sudo cp -a /opt/codex-bridge/gateway/app/version.py "$BACKUP/version.py"
fi
if sudo test -f /opt/codex-bridge/pyproject.toml; then
  sudo cp -a /opt/codex-bridge/pyproject.toml "$BACKUP/pyproject.toml"
fi

echo "backup=$BACKUP"

sudo install -o codexbridge -g codexbridge -m 0644 /tmp/version.py /opt/codex-bridge/gateway/app/version.py
sudo install -o codexbridge -g codexbridge -m 0644 /tmp/pyproject.toml /opt/codex-bridge/pyproject.toml
rm -f /tmp/version.py /tmp/pyproject.toml

sudo -u codexbridge /opt/codex-bridge/.venv/bin/python -m py_compile /opt/codex-bridge/gateway/app/version.py
sudo systemctl restart codex-bridge-gateway.service

for i in $(seq 1 30); do
  if curl -fsS --connect-timeout 2 http://127.0.0.1:18080/health >/dev/null 2>&1; then
    break
  fi
  sleep 1
done
curl -fsS http://127.0.0.1:18080/health
echo
REMOTE

echo "== verify public MCP announces ${TARGET_VERSION} =="
INIT="$(curl -fsS --connect-timeout 8 \
  -H 'content-type: application/json' \
  -H 'accept: application/json, text/event-stream' \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"release-check","version":"1"}}}' \
  "$BASE/mcp")"
printf '%s\n' "$INIT"
printf '%s' "$INIT" | grep -q '"version"[[:space:]]*:[[:space:]]*"0.2.0"' || {
  echo "ERROR: MCP did not announce ${TARGET_VERSION}"
  exit 3
}
echo "mcp_version=${TARGET_VERSION}"

echo "== verify OAuth discovery =="
curl -fsS --connect-timeout 8 "$BASE/.well-known/oauth-protected-resource/mcp" >/dev/null
curl -fsS --connect-timeout 8 "$BASE/.well-known/oauth-authorization-server" >/dev/null
echo "oauth_discovery=ok"

echo "== verify devel3 reconnect =="
connected=0
for i in $(seq 1 30); do
  if ssh -p "$FRIDA_PORT" "$FRIDA_USER@$FRIDA_HOST" \
    "sudo journalctl -u codex-bridge-gateway.service --since '-2 minutes' --no-pager | grep -q 'WebSocket /agent/ws?executor_id=devel3.*accepted'"; then
    connected=1
    break
  fi
  sleep 2
done
[[ "$connected" -eq 1 ]] || {
  echo "ERROR: devel3 did not reconnect after gateway restart"
  exit 4
}
echo "devel3_websocket=accepted"

echo "CODEXBRIDGE_0_2_0_DEPLOYED"

git add "$OUT"
git commit -m "results: deploy CodexBridge 0.2.0" || true
git push origin development
