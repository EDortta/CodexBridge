#!/usr/bin/env bash
# Migrate legacy system Worker state/credential to developer-owned user service.
# Explicit sudo is used ONLY to read legacy root-owned files and disable old service.
set -euo pipefail
[[ "$EUID" -ne 0 ]] || { echo "Run as developer, never root"; exit 2; }
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
STATE="${XDG_STATE_HOME:-$HOME/.local/state}/codexbridge-worker"
CONFIG="${XDG_CONFIG_HOME:-$HOME/.config}/codexbridge-worker"
install -d -m 700 "$STATE" "$CONFIG"
if systemctl is-active --quiet codexbridge-worker; then
  echo "Legacy system worker active: stop first to avoid duplicate observers" >&2
  exit 1
fi
# Only a one-time privileged migration. Never print secret.
if sudo test -f /var/lib/codexbridge-worker/state.json; then
  sudo cat /var/lib/codexbridge-worker/state.json > "$STATE/state.json"
  chmod 600 "$STATE/state.json"
fi
if sudo test -f /etc/codexbridge-worker/worker-token; then
  sudo cat /etc/codexbridge-worker/worker-token > "$CONFIG/worker-token"
  chmod 600 "$CONFIG/worker-token"
  touch "$CONFIG/worker.env"
  grep -v '^CODEXBRIDGE_WORKER_TOKEN_FILE=' "$CONFIG/worker.env" > "$CONFIG/.worker.env.tmp"
  mv "$CONFIG/.worker.env.tmp" "$CONFIG/worker.env"
  printf 'CODEXBRIDGE_WORKER_TOKEN_FILE=%s/worker-token\n' "$CONFIG" >> "$CONFIG/worker.env"
  chmod 600 "$CONFIG/worker.env"
fi
sudo systemctl disable --now codexbridge-worker >/dev/null 2>&1 || true
echo "Migrated state/Worker credential without printing contents; legacy service disabled."
echo "No service started. Validate with: systemctl --user status codexbridge-worker"
