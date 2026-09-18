#!/usr/bin/env bash
set -uo pipefail

REPO_ROOT="$(git rev-parse --show-toplevel)"
cd "$REPO_ROOT"

STAMP="$(date -u +%Y%m%d-%H%M%SZ)"
OUT="temp-tools/results/${STAMP}-oauth-logging-resilient-deploy.txt"
mkdir -p temp-tools/results

exec > >(tee "$OUT") 2>&1
source temp-tools/lib/result-publisher.sh

GLOBAL_TIMEOUT_SECONDS=180
SSH_TIMEOUT_SECONDS=20
CURL_TIMEOUT_SECONDS=12

FRIDA=(timeout "${SSH_TIMEOUT_SECONDS}s" ssh -p 2200 -o ConnectTimeout=8 -o StrictHostKeyChecking=accept-new esteban@frida.inovacaosistemas.com.br)
T610=(timeout "${SSH_TIMEOUT_SECONDS}s" ssh -p 22 -o ConnectTimeout=8 -o StrictHostKeyChecking=accept-new esteban@dom1.inovacaosistemas.com.br)

FAIL=0

run_step() {
  local name="$1"
  shift
  echo
  echo "== $name =="
  "$@"
  local rc=$?
  echo "step_exit_code=$rc"
  if [ "$rc" -ne 0 ]; then
    FAIL=1
  fi
  return 0
}

probe_url() {
  local label="$1"
  local url="$2"
  local tries="${3:-8}"
  local i
  for i in $(seq 1 "$tries"); do
    echo "-- $label attempt=$i url=$url"
    if timeout "${CURL_TIMEOUT_SECONDS}s" curl -sS -D- --connect-timeout 5 --max-time "$CURL_TIMEOUT_SECONDS" "$url"; then
      echo
      echo "${label}_status=ok"
      return 0
    fi
    echo
    sleep 2
  done
  echo "${label}_status=failed"
  return 1
}

collect_diagnostics() {
  echo
  echo "== diagnostic bundle =="

  echo "-- Frida service status --"
  "${FRIDA[@]}" 'sudo systemctl status codex-bridge-gateway.service --no-pager -l || true' || true

  echo "-- Frida live process environment --"
  "${FRIDA[@]}" 'PID=$(sudo systemctl show codex-bridge-gateway.service -p MainPID --value); echo "pid=$PID"; if [ -n "$PID" ] && [ "$PID" != "0" ]; then sudo sh -c "tr \"\\0\" \"\\n\" < /proc/$PID/environ | grep -E \"^CODEX_BRIDGE_(USER_REGISTRY_FILE|PUBLIC_BASE_URL|OAUTH_ISSUER_URL)=\" || true"; fi' || true

  echo "-- Frida recent gateway journal --"
  "${FRIDA[@]}" 'sudo journalctl -u codex-bridge-gateway.service --since "15 minutes ago" --no-pager | tail -250 || true' || true

  echo "-- Frida nginx recent access --"
  "${FRIDA[@]}" 'sudo tail -250 /var/log/nginx/access.log 2>/dev/null | grep -E "health|oauth/authorize|oauth/token|/mcp" | tail -120 || true' || true

  echo "-- Frida nginx recent errors --"
  "${FRIDA[@]}" 'sudo tail -250 /var/log/nginx/error.log 2>/dev/null | tail -120 || true' || true

  echo "-- Frida listeners --"
  "${FRIDA[@]}" 'sudo ss -ltnp | grep -E ":(443|8443|18080|18082) " || true' || true

  echo "-- T610 nginx status/config --"
  "${T610[@]}" 'sudo /usr/sbin/nginx -t || true; sudo ss -ltnp | grep -E ":(80|443) " || true; sudo grep -nE "server_name|listen|proxy_pass" /etc/nginx/sites-available/020-codexbridge.conf 2>/dev/null || true' || true

  echo "-- T610 recent nginx access --"
  "${T610[@]}" 'sudo tail -250 /var/log/nginx/access.log 2>/dev/null | grep -E "health|oauth/authorize|oauth/token|/mcp" | tail -120 || true' || true

  echo "-- T610 recent nginx errors --"
  "${T610[@]}" 'sudo tail -250 /var/log/nginx/error.log 2>/dev/null | tail -120 || true' || true

  echo "-- T610 to Frida private hop --"
  "${T610[@]}" 'curl -sS -D- --connect-timeout 5 --max-time 10 -H "Host: codexbridge.inovacaosistemas.com.br" http://192.168.71.248:18082/health || true' || true

  echo "-- T610 local canonical 443 --"
  "${T610[@]}" 'curl -sS -D- --http1.1 --resolve codexbridge.inovacaosistemas.com.br:443:127.0.0.1 --connect-timeout 5 --max-time 10 https://codexbridge.inovacaosistemas.com.br/health || true' || true
}

main() {
  echo "== Resilient OAuth diagnostic logging deployment =="
  echo "utc=$(date -u +%FT%TZ)"
  echo "global_timeout_seconds=$GLOBAL_TIMEOUT_SECONDS"
  echo "ssh_timeout_seconds=$SSH_TIMEOUT_SECONDS"
  echo "curl_timeout_seconds=$CURL_TIMEOUT_SECONDS"

  run_step "source compile" python3 -m py_compile gateway/app/main.py
  run_step "bounded OAuth integration tests" timeout 75s pytest -q tests/integration/test_oauth_authorize.py

  echo
  echo "== upload main.py =="
  timeout 20s scp -q -P 2200 -o ConnectTimeout=8 -o StrictHostKeyChecking=accept-new     gateway/app/main.py esteban@frida.inovacaosistemas.com.br:/tmp/codexbridge-main.py
  rc=$?
  echo "upload_exit_code=$rc"
  if [ "$rc" -ne 0 ]; then
    FAIL=1
  else
    echo
    echo "== install with rollback guard =="
    "${FRIDA[@]}" 'bash -s' <<'REMOTE'
set -u
STAMP="$(date -u +%Y%m%d-%H%M%SZ)"
BACKUP="/var/backups/codex-bridge/oauth-logging-${STAMP}"
sudo mkdir -p "$BACKUP"
sudo cp -a /opt/codex-bridge/gateway/app/main.py "$BACKUP/main.py"

sudo install -o codexbridge -g codexbridge -m 0644   /tmp/codexbridge-main.py /opt/codex-bridge/gateway/app/main.py
rm -f /tmp/codexbridge-main.py

if ! sudo -u codexbridge /opt/codex-bridge/.venv/bin/python3 -m py_compile   /opt/codex-bridge/gateway/app/main.py; then
  echo "deploy_compile=failed"
  sudo cp -a "$BACKUP/main.py" /opt/codex-bridge/gateway/app/main.py
  sudo systemctl restart codex-bridge-gateway.service || true
  exit 21
fi

sudo systemctl restart codex-bridge-gateway.service || true

LOCAL_OK=0
for i in $(seq 1 20); do
  if sudo systemctl is-active --quiet codex-bridge-gateway.service &&      curl -fsS --connect-timeout 2 --max-time 4 http://127.0.0.1:18080/health >/tmp/cb-health.$$ 2>/tmp/cb-health-err.$$; then
    cat /tmp/cb-health.$$
    echo
    LOCAL_OK=1
    break
  fi
  sleep 1
done
rm -f /tmp/cb-health.$$ /tmp/cb-health-err.$$

if [ "$LOCAL_OK" -ne 1 ]; then
  echo "local_gateway_health=failed"
  echo "rollback=starting"
  sudo cp -a "$BACKUP/main.py" /opt/codex-bridge/gateway/app/main.py
  sudo systemctl restart codex-bridge-gateway.service || true
  sleep 3
  sudo systemctl status codex-bridge-gateway.service --no-pager -l || true
  exit 22
fi

echo "local_gateway_health=ok"
echo "backup=$BACKUP"
REMOTE
    rc=$?
    echo "install_exit_code=$rc"
    if [ "$rc" -ne 0 ]; then
      FAIL=1
    fi
  fi

  run_step "external canonical health" probe_url external_443 https://codexbridge.inovacaosistemas.com.br/health 10
  run_step "external legacy health" probe_url external_8443 https://codexbridge.inovacaosistemas.com.br:8443/health 6

  collect_diagnostics

  echo
  echo "== final classification =="
  if [ "$FAIL" -eq 0 ]; then
    echo "deployment_and_path=ok"
    echo "CODEXBRIDGE_OAUTH_DIAGNOSTIC_LOGGING_READY"
    return 0
  fi

  echo "deployment_and_path=failed"
  echo "diagnostics_collected=yes"
  echo "CODEXBRIDGE_OAUTH_DIAGNOSTIC_LOGGING_FAILED"
  return 1
}

main &
WORK_PID=$!

if ! timeout "${GLOBAL_TIMEOUT_SECONDS}s" tail --pid="$WORK_PID" -f /dev/null; then
  echo
  echo "ERROR: global timeout after ${GLOBAL_TIMEOUT_SECONDS}s"
  kill "$WORK_PID" 2>/dev/null || true
  wait "$WORK_PID" 2>/dev/null || true
  collect_diagnostics
  exit 124
fi

wait "$WORK_PID"
