#!/usr/bin/env bash
set -uo pipefail

REPO_ROOT="$(git rev-parse --show-toplevel)"
cd "$REPO_ROOT"
STAMP="$(date -u +%Y%m%d-%H%M%SZ)"
OUT="temp-tools/results/${STAMP}-capture-browser-oauth-attempt.txt"
mkdir -p temp-tools/results
exec > >(tee "$OUT") 2>&1
source temp-tools/lib/result-publisher.sh

WAIT_SECONDS=180
START_LOCAL="$(date '+%Y-%m-%d %H:%M:%S')"
FRIDA=(timeout 25s ssh -p 2200 -o ConnectTimeout=8 -o StrictHostKeyChecking=accept-new esteban@frida.inovacaosistemas.com.br)

echo "== Capture one browser OAuth login attempt =="
echo "started_local=$START_LOCAL"
echo "wait_timeout_seconds=$WAIT_SECONDS"
echo
echo "Faça UMA tentativa de login no navegador agora."
echo "Quando aparecer o resultado no navegador, volte aqui e pressione ENTER."
echo

if ! IFS= read -r -t "$WAIT_SECONDS" _; then
  echo "capture_wait=timeout"
  exit 124
fi

echo "capture_wait=completed"
echo
echo "== gateway OAuth diagnostic lines since start =="
GATEWAY_LOGS="$("${FRIDA[@]}" "sudo journalctl -u codex-bridge-gateway.service --since '$START_LOCAL' --no-pager | grep -E 'oauth_authorize_(attempt|result|grant)|POST /oauth/authorize|user registry' || true")"
printf '%s\n' "$GATEWAY_LOGS"

echo
echo "== nginx OAuth lines since recent tail =="
NGINX_LOGS="$("${FRIDA[@]}" "sudo tail -300 /var/log/nginx/access.log | grep -E 'POST /oauth/authorize|GET /oauth/authorize' | tail -40 || true")"
printf '%s\n' "$NGINX_LOGS"

echo
echo "== automatic analysis =="
python3 - "$GATEWAY_LOGS" <<'PY'
import re, sys
text = sys.argv[1]
results = re.findall(r"oauth_authorize_result[^\n]*outcome=([^ ]+)[^\n]*resolved_user_id=([^ ]+)[^\n]*enabled=([^ ]+)", text)
attempts = re.findall(r"oauth_authorize_attempt[^\n]*registry=([^ ]+)[^\n]*registry_ok=([^ ]+)", text)
grants = re.findall(r"oauth_authorize_grant[^\n]*user_id=([^ ]+)", text)

print(f"diagnostic_attempt_count={len(attempts)}")
print(f"diagnostic_result_count={len(results)}")
print(f"diagnostic_grant_count={len(grants)}")

if attempts:
    registry, ok = attempts[-1]
    print(f"last_registry={registry}")
    print(f"last_registry_ok={ok}")

if not results:
    print("analysis=no_oauth_result_seen")
    raise SystemExit(10)

outcome, user_id, enabled = results[-1]
print(f"last_outcome={outcome}")
print(f"last_resolved_user_id={user_id}")
print(f"last_enabled={enabled}")

if outcome == "accepted":
    if grants:
        print("analysis=password_accepted_and_grant_created")
        print("CODEXBRIDGE_BROWSER_OAUTH_ACCEPTED")
        raise SystemExit(0)
    print("analysis=password_accepted_but_grant_missing")
    raise SystemExit(11)

mapping = {
    "unknown_user": "login_identifier_did_not_resolve_in_live_registry",
    "bad_password": "live_gateway_resolved_user_but_password_check_failed",
    "account_disabled": "live_user_is_disabled",
    "published_example_credential": "live_hash_matches_forbidden_published_example",
}
print("analysis=" + mapping.get(outcome, "oauth_rejected_for_unclassified_reason"))
raise SystemExit(12)
PY
