#!/usr/bin/env bash
set -uo pipefail

REPO_ROOT="$(git rev-parse --show-toplevel)"
cd "$REPO_ROOT"

STAMP="$(date -u +%Y%m%d-%H%M%SZ)"
OUT="temp-tools/results/${STAMP}-oauth-live-logs.txt"
mkdir -p temp-tools/results

if [ -f temp-tools/lib/result-publisher.sh ]; then
  source temp-tools/lib/result-publisher.sh
fi

exec > >(tee "$OUT") 2>&1

LOGIN="${1:-edortta71@gmail.com}"
FRIDA=(ssh -p 2200 -o StrictHostKeyChecking=accept-new esteban@frida.inovacaosistemas.com.br)

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
      git commit -m "results: ${STAMP}-oauth-live-logs" >/dev/null 2>&1 || true
      git push origin development >/dev/null 2>&1 || true
    fi
  fi
  exit "$rc"
}
trap finish_fallback EXIT

echo "== CodexBridge OAuth live logs =="
echo "utc=$(date -u +%FT%TZ)"
echo "login=$LOGIN"
echo

echo "== gateway service identity =="
"${FRIDA[@]}" 'sudo systemctl show codex-bridge-gateway.service -p MainPID -p ExecStart -p EnvironmentFiles -p FragmentPath --no-pager'
echo

echo "== effective configured user registry =="
"${FRIDA[@]}" "sudo -u codexbridge bash -lc 'cd /opt/codex-bridge && /opt/codex-bridge/.venv/bin/python3 - <<"PY"
from gateway.app.core.config import settings
from gateway.app.core.users import lookup_user
print("settings.user_registry_file=" + settings.user_registry_file)
u = lookup_user(settings.user_registry_file, "$LOGIN")
print("lookup_user=" + ("found" if u else "missing"))
if u:
    print("user_id=" + u.user_id)
    print("email=" + u.email)
    print("enabled=" + str(u.enabled))
    print("roles=" + ",".join(u.roles))
PY'"
echo

echo "== recent gateway journal =="
"${FRIDA[@]}" 'sudo journalctl -u codex-bridge-gateway.service --since "30 minutes ago" --no-pager | tail -300'
echo

echo "== recent nginx OAuth access lines =="
"${FRIDA[@]}" 'sudo tail -500 /var/log/nginx/access.log | grep -E "/oauth/authorize|/oauth/token" | tail -120 || true'
echo

echo "== recent nginx errors =="
"${FRIDA[@]}" 'sudo tail -500 /var/log/nginx/error.log | grep -Ei "oauth|upstream|error|fail" | tail -120 || true'
echo

echo "CODEXBRIDGE_OAUTH_LIVE_LOGS_COMPLETE"
