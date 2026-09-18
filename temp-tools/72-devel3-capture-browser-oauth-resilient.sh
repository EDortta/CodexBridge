#!/usr/bin/env bash
set -uo pipefail

REPO_ROOT="$(git rev-parse --show-toplevel)"
cd "$REPO_ROOT"

STAMP="$(date -u +%Y%m%d-%H%M%SZ)"
OUT="temp-tools/results/${STAMP}-browser-oauth-capture-resilient.txt"
mkdir -p temp-tools/results
exec > >(tee "$OUT") 2>&1
source temp-tools/lib/result-publisher.sh

GLOBAL_TIMEOUT_SECONDS=300
WAIT_SECONDS=180
SSH_TIMEOUT_SECONDS=25
CURL_TIMEOUT_SECONDS=12
FRIDA=(timeout "${SSH_TIMEOUT_SECONDS}s" ssh -p 2200 -o ConnectTimeout=8 -o StrictHostKeyChecking=accept-new esteban@frida.inovacaosistemas.com.br)
T610=(timeout "${SSH_TIMEOUT_SECONDS}s" ssh -p 22 -o ConnectTimeout=8 -o StrictHostKeyChecking=accept-new esteban@dom1.inovacaosistemas.com.br)

collect_diag() {
  echo
  echo "== diagnostic bundle =="
  echo "-- external 443 --"
  timeout "${CURL_TIMEOUT_SECONDS}s" curl -sS -D- --connect-timeout 5 --max-time "$CURL_TIMEOUT_SECONDS"     https://codexbridge.inovacaosistemas.com.br/health || true
  echo
  echo "-- Frida service --"
  "${FRIDA[@]}" 'sudo systemctl status codex-bridge-gateway.service --no-pager -l || true' || true
  echo "-- Frida journal --"
  "${FRIDA[@]}" 'sudo journalctl -u codex-bridge-gateway.service --since "15 minutes ago" --no-pager | tail -220 || true' || true
  echo "-- Frida nginx errors --"
  "${FRIDA[@]}" 'sudo tail -220 /var/log/nginx/error.log 2>/dev/null | tail -120 || true' || true
  echo "-- T610 local 443 --"
  "${T610[@]}" 'curl -sS -D- --http1.1 --resolve codexbridge.inovacaosistemas.com.br:443:127.0.0.1 --connect-timeout 5 --max-time 10 https://codexbridge.inovacaosistemas.com.br/health || true' || true
}

main() {
  echo "== Resilient browser OAuth capture =="
  echo "utc=$(date -u +%FT%TZ)"
  echo "global_timeout_seconds=$GLOBAL_TIMEOUT_SECONDS"
  echo "browser_wait_seconds=$WAIT_SECONDS"
  echo

  echo "== wait until external canonical 443 is truly healthy =="
  READY=0
  for i in $(seq 1 20); do
    CODE="$(timeout "${CURL_TIMEOUT_SECONDS}s" curl -sS -o /tmp/cb72-health.$$ -w '%{http_code}'       --connect-timeout 5 --max-time "$CURL_TIMEOUT_SECONDS"       https://codexbridge.inovacaosistemas.com.br/health 2>/tmp/cb72-health-err.$$ || true)"
    BODY="$(cat /tmp/cb72-health.$$ 2>/dev/null || true)"
    ERR="$(cat /tmp/cb72-health-err.$$ 2>/dev/null || true)"
    rm -f /tmp/cb72-health.$$ /tmp/cb72-health-err.$$
    echo "attempt=$i http_code=${CODE:-none} body=$BODY"
    [ -n "$ERR" ] && echo "curl_error=$ERR"
    if [ "$CODE" = "200" ] && printf '%s' "$BODY" | grep -q '"status":"ok"'; then
      READY=1
      break
    fi
    sleep 3
  done

  if [ "$READY" -ne 1 ]; then
    echo "preflight=failed"
    collect_diag
    echo "CODEXBRIDGE_BROWSER_OAUTH_CAPTURE_PREFLIGHT_FAILED"
    return 20
  fi

  echo "preflight=ok"
  START_UTC="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  START_LOCAL="$(date '+%Y-%m-%d %H:%M:%S')"
  echo "capture_start_utc=$START_UTC"
  echo
  echo "Faça UMA tentativa de login no navegador agora."
  echo "Quando aparecer a resposta, volte aqui e pressione ENTER."
  echo "O script aguardará no máximo ${WAIT_SECONDS}s."
  echo

  if ! IFS= read -r -t "$WAIT_SECONDS" _; then
    echo "browser_wait=timeout"
    collect_diag
    echo "CODEXBRIDGE_BROWSER_OAUTH_CAPTURE_TIMEOUT"
    return 124
  fi

  echo "browser_wait=completed"
  echo

  echo "== OAuth application logs from this capture window =="
  LOGS="$("${FRIDA[@]}" "sudo journalctl -u codex-bridge-gateway.service --since '$START_LOCAL' --no-pager | grep -E 'oauth_authorize_(attempt|result|grant)|POST /oauth/authorize|user registry' || true")"
  printf '%s\n' "$LOGS"

  echo
  echo "== nginx OAuth requests =="
  "${FRIDA[@]}" "sudo tail -250 /var/log/nginx/access.log | grep -E 'POST /oauth/authorize|GET /oauth/authorize' | tail -60 || true"

  echo
  echo "== automatic analysis =="
  python3 - "$LOGS" <<'PY'
import re, sys
text = sys.argv[1]
attempts = re.findall(r"oauth_authorize_attempt[^\n]*login_fp=([^ ]+)[^\n]*registry=([^ ]+)[^\n]*registry_ok=([^ ]+)", text)
results = re.findall(r"oauth_authorize_result[^\n]*login_fp=([^ ]+)[^\n]*outcome=([^ ]+)[^\n]*resolved_user_id=([^ ]+)[^\n]*enabled=([^ ]+)", text)
grants = re.findall(r"oauth_authorize_grant[^\n]*login_fp=([^ ]+)[^\n]*user_id=([^ ]+)", text)

print(f"attempt_count={len(attempts)}")
print(f"result_count={len(results)}")
print(f"grant_count={len(grants)}")

if attempts:
    fp, registry, ok = attempts[-1]
    print(f"last_login_fp={fp}")
    print(f"last_registry={registry}")
    print(f"last_registry_ok={ok}")

if not results:
    print("analysis=no_instrumented_oauth_result_seen")
    raise SystemExit(10)

fp, outcome, user_id, enabled = results[-1]
print(f"last_outcome={outcome}")
print(f"last_resolved_user_id={user_id}")
print(f"last_enabled={enabled}")

if outcome == "accepted":
    if grants:
        print("analysis=password_accepted_and_authorization_grant_created")
        print("CODEXBRIDGE_BROWSER_OAUTH_ACCEPTED")
        raise SystemExit(0)
    print("analysis=password_accepted_but_grant_not_created")
    raise SystemExit(11)

mapping = {
    "unknown_user": "live_gateway_did_not_resolve_login",
    "bad_password": "live_gateway_resolved_user_but_password_verification_failed",
    "account_disabled": "live_account_disabled",
    "published_example_credential": "live_hash_matches_forbidden_example_credential",
}
print("analysis=" + mapping.get(outcome, "oauth_rejected_unclassified"))
raise SystemExit(12)
PY
  ANALYSIS_RC=$?

  if [ "$ANALYSIS_RC" -ne 0 ]; then
    collect_diag
    echo "CODEXBRIDGE_BROWSER_OAUTH_CAPTURE_FAILED"
    return "$ANALYSIS_RC"
  fi

  return 0
}

main &
WORK_PID=$!

if ! timeout "${GLOBAL_TIMEOUT_SECONDS}s" tail --pid="$WORK_PID" -f /dev/null; then
  echo
  echo "ERROR: global timeout after ${GLOBAL_TIMEOUT_SECONDS}s"
  kill "$WORK_PID" 2>/dev/null || true
  wait "$WORK_PID" 2>/dev/null || true
  collect_diag
  exit 124
fi

wait "$WORK_PID"
