#!/usr/bin/env bash
# Install Worker as a USER systemd unit. No root or sudo.
set -euo pipefail
if [[ "${EUID}" -eq 0 ]]; then
  echo "Run as the developer, not root/sudo" >&2
  exit 2
fi
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
INSTALL_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/codexbridge-worker"
STATE_DIR="${XDG_STATE_HOME:-$HOME/.local/state}/codexbridge-worker"
CONFIG_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/codexbridge-worker"
UNIT_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"
install -d -m 0700 "$INSTALL_DIR/scripts" "$STATE_DIR" "$CONFIG_DIR"
install -d -m 0700 "$UNIT_DIR"
for file in worker_watch.py worker_request.py workerctl.py; do
  install -m 0600 "$ROOT/scripts/$file" "$INSTALL_DIR/scripts/$file"
done
cat > "$UNIT_DIR/codexbridge-worker.service" <<UNIT
[Unit]
Description=CodexBridge Git control-branch observer
After=network-online.target

[Service]
Type=simple
WorkingDirectory=$INSTALL_DIR
Environment=CODEXBRIDGE_GIT_CACHE=$STATE_DIR/git-cache
EnvironmentFile=-$CONFIG_DIR/worker.env
ExecStart=/usr/bin/python3 $INSTALL_DIR/scripts/worker_watch.py --forward-gateway --interval 60 --state-file $STATE_DIR/state.json
Restart=on-failure
RestartSec=15
UMask=0077

[Install]
WantedBy=default.target
UNIT
if [[ ! -f "$CONFIG_DIR/worker.env" ]]; then
  cat > "$CONFIG_DIR/worker.env" <<'ENV'
CODEXBRIDGE_GATEWAY_URL=https://codexbridge.inovacaosistemas.com.br
# Must be provisioned separately; never store this token in Git.
CODEXBRIDGE_WORKER_TOKEN_FILE=
ENV
fi
chmod 0600 "$CONFIG_DIR/worker.env"
systemctl --user daemon-reload
echo "Installed user unit, NOT started: systemctl --user start codexbridge-worker"
echo "Configure Worker Gateway credential and enable project under $STATE_DIR/state.json"
