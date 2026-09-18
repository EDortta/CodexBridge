#!/usr/bin/env bash
set -uo pipefail

REPO_ROOT="$(git rev-parse --show-toplevel)"
cd "$REPO_ROOT"

STAMP="$(date -u +%Y%m%d-%H%M%SZ)"
OUT="temp-tools/results/${STAMP}-oauth-registry-runtime-repair.txt"
mkdir -p temp-tools/results

# Always capture and publish the result, whether success, error, or timeout.
exec > >(tee "$OUT") 2>&1
if [ -f temp-tools/lib/result-publisher.sh ]; then
  source temp-tools/lib/result-publisher.sh
fi

GLOBAL_TIMEOUT_SECONDS=120
SSH_TIMEOUT_SECONDS=20
CURL_TIMEOUT_SECONDS=15
FRIDA_HOST="frida.inovacaosistemas.com.br"
FRIDA_PORT="2200"
FRIDA_USER="esteban"
EXPECTED_REGISTRY="/etc/codex-bridge/auth/users.json"

finish_fallback() {
  rc=$?
  trap - EXIT
  set +e
  if [ -f "$OUT" ]; then
    {
      echo
      echo "== script exit =="
      echo "exit_code=$rc"
      echo "utc=$(date -u +%FT%TZ)"
    } >>"$OUT"
    git add "$OUT" >/dev/null 2>&1 || true
    if ! git diff --cached --quiet -- "$OUT" 2>/dev/null; then
      git commit -m "results: ${STAMP}-oauth-registry-runtime-repair" >/dev/null 2>&1 || true
      timeout 20s git push origin development >/dev/null 2>&1 || true
    fi
  fi
  exit "$rc"
}
trap finish_fallback EXIT

# Hard ceiling for the whole diagnostic/repair.
(
set -euo pipefail

SSH=(timeout "${SSH_TIMEOUT_SECONDS}s" ssh -p "$FRIDA_PORT" -o ConnectTimeout=8 -o StrictHostKeyChecking=accept-new "$FRIDA_USER@$FRIDA_HOST")

echo "== CodexBridge OAuth runtime registry repair =="
echo "utc=$(date -u +%FT%TZ)"
echo "global_timeout_seconds=$GLOBAL_TIMEOUT_SECONDS"
echo "ssh_timeout_seconds=$SSH_TIMEOUT_SECONDS"
echo "curl_timeout_seconds=$CURL_TIMEOUT_SECONDS"
echo

echo "== inspect live service process environment =="
"${SSH[@]}" "sudo bash -s -- '$EXPECTED_REGISTRY'" <<'REMOTE'
set -euo pipefail
EXPECTED="$1"
UNIT="codex-bridge-gateway.service"
PID="$(systemctl show "$UNIT" -p MainPID --value)"
echo "main_pid=$PID"
echo "unit_active=$(systemctl is-active "$UNIT" || true)"
echo "env_file_line=$(grep '^CODEX_BRIDGE_USER_REGISTRY_FILE=' /etc/codex-bridge/env 2>/dev/null || true)"
if [ -n "$PID" ] && [ "$PID" != "0" ] && [ -r "/proc/$PID/environ" ]; then
  LIVE="$(tr '\0' '\n' < "/proc/$PID/environ" | grep '^CODEX_BRIDGE_USER_REGISTRY_FILE=' || true)"
else
  LIVE=""
fi
echo "process_env_line=$LIVE"
echo "expected=$EXPECTED"
REMOTE

echo
echo "== ensure the running service receives the intended registry =="
"${SSH[@]}" "sudo bash -s -- '$EXPECTED_REGISTRY'" <<'REMOTE'
set -euo pipefail
EXPECTED="$1"
UNIT="codex-bridge-gateway.service"
ENV_FILE="/etc/codex-bridge/env"

grep -q "^CODEX_BRIDGE_USER_REGISTRY_FILE=$EXPECTED$" "$ENV_FILE" || {
  sed -i '/^CODEX_BRIDGE_USER_REGISTRY_FILE=/d' "$ENV_FILE"
  printf 'CODEX_BRIDGE_USER_REGISTRY_FILE=%s\n' "$EXPECTED" >> "$ENV_FILE"
}

PID="$(systemctl show "$UNIT" -p MainPID --value)"
LIVE=""
if [ -n "$PID" ] && [ "$PID" != "0" ] && [ -r "/proc/$PID/environ" ]; then
  LIVE="$(tr '\0' '\n' < "/proc/$PID/environ" | grep '^CODEX_BRIDGE_USER_REGISTRY_FILE=' || true)"
fi

if [ "$LIVE" != "CODEX_BRIDGE_USER_REGISTRY_FILE=$EXPECTED" ]; then
  echo "process_env_mismatch=repairing"
  systemctl restart "$UNIT"
  for i in $(seq 1 15); do
    if systemctl is-active --quiet "$UNIT"; then
      PID="$(systemctl show "$UNIT" -p MainPID --value)"
      LIVE="$(tr '\0' '\n' < "/proc/$PID/environ" | grep '^CODEX_BRIDGE_USER_REGISTRY_FILE=' || true)"
      if [ "$LIVE" = "CODEX_BRIDGE_USER_REGISTRY_FILE=$EXPECTED" ]; then
        break
      fi
    fi
    sleep 1
  done
else
  echo "process_env_mismatch=no"
fi

PID="$(systemctl show "$UNIT" -p MainPID --value)"
LIVE="$(tr '\0' '\n' < "/proc/$PID/environ" | grep '^CODEX_BRIDGE_USER_REGISTRY_FILE=' || true)"
echo "final_process_env_line=$LIVE"

if [ "$LIVE" != "CODEX_BRIDGE_USER_REGISTRY_FILE=$EXPECTED" ]; then
  echo "ERROR: running gateway still does not have expected registry env"
  exit 11
fi
REMOTE

echo
echo "== verify registry as codexbridge service account using exact live env =="
"${SSH[@]}" "sudo bash -s -- '$EXPECTED_REGISTRY'" <<'REMOTE'
set -euo pipefail
EXPECTED="$1"
sudo -u codexbridge test -r "$EXPECTED"
sudo -u codexbridge test -w "$EXPECTED"
sudo -u codexbridge env CODEX_BRIDGE_USER_REGISTRY_FILE="$EXPECTED" bash -lc '
  cd /opt/codex-bridge
  /opt/codex-bridge/.venv/bin/python3 - <<"PY"
from gateway.app.core.config import settings
from gateway.app.core.users import lookup_user, unusable_registry_reason
print("settings.user_registry_file=" + settings.user_registry_file)
print("registry_reason=" + str(unusable_registry_reason(settings.user_registry_file)))
u = lookup_user(settings.user_registry_file, "edortta71@gmail.com")
print("lookup_user=" + ("found" if u else "missing"))
if u:
    print("user_id=" + u.user_id)
    print("email=" + u.email)
    print("enabled=" + str(u.enabled))
PY
'
REMOTE

echo
echo "== gateway journal after repair =="
"${SSH[@]}" 'sudo journalctl -u codex-bridge-gateway.service --since "10 minutes ago" --no-pager | tail -120'

echo
echo "== external health with bounded retries =="
HEALTH_OK=0
for i in $(seq 1 12); do
  if timeout "${CURL_TIMEOUT_SECONDS}s" curl -fsS --connect-timeout 5 --max-time "$CURL_TIMEOUT_SECONDS"       https://codexbridge.inovacaosistemas.com.br/health; then
    echo
    echo "external_health=ok"
    HEALTH_OK=1
    break
  fi
  echo "external_health_attempt_${i}=failed"
  sleep 2
done

if [ "$HEALTH_OK" -ne 1 ]; then
  echo "external_health=failed"
  exit 22
fi

echo
echo "CODEXBRIDGE_OAUTH_RUNTIME_REGISTRY_READY"
) &
WORK_PID=$!

if ! timeout "$GLOBAL_TIMEOUT_SECONDS" tail --pid="$WORK_PID" -f /dev/null; then
  echo "ERROR: global timeout after ${GLOBAL_TIMEOUT_SECONDS}s"
  kill "$WORK_PID" 2>/dev/null || true
  wait "$WORK_PID" 2>/dev/null || true
  exit 124
fi

wait "$WORK_PID"
