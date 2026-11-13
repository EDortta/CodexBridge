#!/usr/bin/env bash
set -euo pipefail

ROOT="${CODEXBRIDGE_EVIDENCE_ROOT:-logs/mcp-recordings}"
ACTIVE="$ROOT/.active"
HOST="frida.inovacaosistemas.com.br"
PORT="2200"
REMOTE_USER="esteban"
SERVICE="codex-bridge-gateway.service"
ENDPOINT="${CODEXBRIDGE_ENDPOINT:-https://codexbridge.inovacaosistemas.com.br:8443}"
CREDENTIALS="${CODEXBRIDGE_CREDENTIALS:-.credentials/codex-bridge-initial-admin-password.ini}"

die() { echo "ERROR: $*" >&2; exit 1; }

start_recording() {
  [[ ! -e "$ACTIVE" ]] || die "já existe uma gravação ativa: $(cat "$ACTIVE")"
  mkdir -p "$ROOT"
  local run_id started run_dir capture_pid
  run_id="$(date -u +%Y%m%dT%H%M%SZ)"
  started="$(date -u '+%Y-%m-%d %H:%M:%S')"
  run_dir="$ROOT/$run_id"
  mkdir -p "$run_dir"
  {
    printf 'RUN_ID=%s\n' "$run_id"
    printf 'STARTED_AT=%s\n' "$started"
    printf 'MCP_ENDPOINT=%s/mcp\n' "$ENDPOINT"
    printf 'GATEWAY_SERVICE=%s\n' "$SERVICE"
  } > "$run_dir/recording.env"
  chmod 700 "$run_dir"

  ssh -T -p "$PORT" -o StrictHostKeyChecking=accept-new \
    "$REMOTE_USER@$HOST" "sudo bash -s -- '$SERVICE' '$started'" \
    > "$run_dir/gateway-live.log" 2>&1 <<'REMOTE' &
set -u
SERVICE="$1"
STARTED="$2"
cleanup() { jobs -pr | xargs -r sudo kill 2>/dev/null || true; }
trap cleanup EXIT INT TERM
{
  sudo journalctl --since "$STARTED" --follow --unit "$SERVICE" --output short-iso --no-pager
} | stdbuf -oL sed -E 's/((code|state|code_challenge|code_verifier|access_token|refresh_token|token|authorization)=)[^ ,"]*/\1[REDACTED]/Ig' | sed 's/^/[gateway] /' &
JOURNAL_PID=$!
if [[ -e /var/log/nginx/access.log || -e /var/log/nginx/error.log ]]; then
  sudo tail -F /var/log/nginx/access.log /var/log/nginx/error.log 2>/dev/null \
    | stdbuf -oL sed -E 's/((code|state|code_challenge|code_verifier|access_token|refresh_token|token|authorization)=)[^ ,"]*/\1[REDACTED]/Ig' \
    | awk '/\/mcp|\/oauth\/|\/api\/v1\/auth\// { print "[nginx] " $0; fflush() }' &
fi
wait "$JOURNAL_PID"
REMOTE
  capture_pid=$!
  printf '%s\n' "$run_dir" > "$ACTIVE"
  printf '%s\n' "$capture_pid" >> "$ACTIVE"
  echo "Gravação iniciada: $run_id"
  echo "Use: $0 --stop-recording"
}

stop_recording() {
  [[ -f "$ACTIVE" ]] || die "não existe gravação ativa"
  mapfile -t state < "$ACTIVE"
  local run_dir="${state[0]}" capture_pid="${state[1]}" probe_rc=0

  umask 077
  python3 tools/codexbridge-mcp-evidence.py \
    --endpoint "$ENDPOINT" --credentials "$CREDENTIALS" --output "$run_dir" \
    > "$run_dir/probe-output.json" 2>&1 || probe_rc=$?

  kill "$capture_pid" 2>/dev/null || true
  wait "$capture_pid" 2>/dev/null || true
  local started finished
  started="$(sed -n 's/^STARTED_AT=//p' "$run_dir/recording.env")"
  finished="$(date -u '+%Y-%m-%d %H:%M:%S')"
  printf 'STOPPED_AT=%s\n' "$finished" >> "$run_dir/recording.env"
  ssh -T -p "$PORT" -o StrictHostKeyChecking=accept-new \
    "$REMOTE_USER@$HOST" "sudo bash -s -- '$SERVICE' '$started' '$finished'" \
    <<'REMOTE' | sed -E 's/((code|state|code_challenge|code_verifier|access_token|refresh_token|token|authorization)=)[^ ,"]*/\1[REDACTED]/Ig' \
    > "$run_dir/gateway-snapshot.log" 2>&1
set -u
SERVICE="$1"
STARTED="$2"
FINISHED="$3"
echo "===== gateway journal ====="
sudo journalctl --since "$STARTED" --until "$FINISHED" --unit "$SERVICE" --output short-iso --no-pager
echo "===== nginx auth and MCP access ====="
sudo grep -hEi '/mcp|/oauth/|/api/v1/auth/' /var/log/nginx/access.log /var/log/nginx/error.log 2>/dev/null || true
REMOTE
  rm -f "$ACTIVE"
  if [[ ! -f "$run_dir/report.env" ]]; then
    printf 'ERRORS=probe_crashed; see probe-output.json\n' > "$run_dir/report.env"
  fi
  chmod 600 "$run_dir"/* 2>/dev/null || true
  echo "Gravação encerrada: $run_dir"
  cat "$run_dir/report.env"
  return "$probe_rc"
}

case "${1:-}" in
  --start-recording) start_recording ;;
  --stop-recording) stop_recording ;;
  -h|--help)
    echo "Uso: $0 --start-recording | --stop-recording"
    ;;
  *) die "use --start-recording ou --stop-recording" ;;
esac
