#!/usr/bin/env bash
set -uo pipefail

REPO_ROOT="$(git rev-parse --show-toplevel)"
cd "$REPO_ROOT"
STAMP="$(date -u +%Y%m%d-%H%M%SZ)"
OUT="temp-tools/results/${STAMP}-deploy-oauth-diagnostic-logging.txt"
mkdir -p temp-tools/results
exec > >(tee "$OUT") 2>&1
source temp-tools/lib/result-publisher.sh

GLOBAL_TIMEOUT=120
(
set -euo pipefail

echo "== Deploy OAuth diagnostic logging =="
echo "utc=$(date -u +%FT%TZ)"
python3 -m py_compile gateway/app/main.py

echo "== bounded OAuth integration tests =="
timeout 75s pytest -q tests/integration/test_oauth_authorize.py

echo "== deploy main.py to Frida =="
timeout 20s scp -q -P 2200 -o ConnectTimeout=8 -o StrictHostKeyChecking=accept-new   gateway/app/main.py esteban@frida.inovacaosistemas.com.br:/tmp/codexbridge-main.py

timeout 30s ssh -p 2200 -o ConnectTimeout=8 -o StrictHostKeyChecking=accept-new   esteban@frida.inovacaosistemas.com.br 'bash -s' <<'REMOTE'
set -euo pipefail
STAMP="$(date -u +%Y%m%d-%H%M%SZ)"
BACKUP="/var/backups/codex-bridge/oauth-logging-${STAMP}"
sudo mkdir -p "$BACKUP"
sudo cp -a /opt/codex-bridge/gateway/app/main.py "$BACKUP/main.py"
sudo install -o codexbridge -g codexbridge -m 0644   /tmp/codexbridge-main.py /opt/codex-bridge/gateway/app/main.py
rm -f /tmp/codexbridge-main.py
sudo -u codexbridge /opt/codex-bridge/.venv/bin/python3 -m py_compile   /opt/codex-bridge/gateway/app/main.py
sudo systemctl restart codex-bridge-gateway.service
for i in $(seq 1 15); do
  sudo systemctl is-active --quiet codex-bridge-gateway.service && break
  sleep 1
done
sudo systemctl is-active codex-bridge-gateway.service
echo "backup=$BACKUP"
REMOTE

echo "== external health =="
timeout 15s curl -fsS --connect-timeout 5 --max-time 12   https://codexbridge.inovacaosistemas.com.br/health
echo

echo "CODEXBRIDGE_OAUTH_DIAGNOSTIC_LOGGING_READY"
) &
PID=$!
if ! timeout "${GLOBAL_TIMEOUT}s" tail --pid="$PID" -f /dev/null; then
  echo "ERROR: global timeout after ${GLOBAL_TIMEOUT}s"
  kill "$PID" 2>/dev/null || true
  wait "$PID" 2>/dev/null || true
  exit 124
fi
wait "$PID"
