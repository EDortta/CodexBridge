#!/usr/bin/env bash
# Install CodexBridge Worker on a Linux systemd host without starting it.
# Run as root from the repository checkout; secrets are NOT copied or created.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WORKER_USER="${WORKER_USER:-codexbridge-worker}"
INSTALL_DIR="${INSTALL_DIR:-/opt/codexbridge-worker}"
CONFIG_DIR="${CONFIG_DIR:-/etc/codexbridge-worker}"
if [[ "${EUID}" -ne 0 ]]; then echo "Run as root" >&2; exit 1; fi
if ! id "${WORKER_USER}" >/dev/null 2>&1; then
  useradd --system --home-dir /nonexistent --shell /usr/sbin/nologin "${WORKER_USER}"
fi
install -d -m 0755 "${INSTALL_DIR}/scripts" "${CONFIG_DIR}"
for file in worker_watch.py worker_request.py workerctl.py; do
  install -m 0644 "${ROOT}/scripts/${file}" "${INSTALL_DIR}/scripts/${file}"
done
install -d -o "${WORKER_USER}" -g "${WORKER_USER}" -m 0700 "/var/lib/codexbridge-worker"
if [[ ! -e "${CONFIG_DIR}/worker.env" ]]; then
cat >"${CONFIG_DIR}/worker.env" <<'ENV'
CODEXBRIDGE_GATEWAY_URL=https://codexbridge.inovacaosistemas.com.br
CODEXBRIDGE_WORKER_TOKEN_FILE=/etc/codexbridge-worker/worker-token
CODEXBRIDGE_GITHUB_TOKEN_FILE=/etc/codexbridge-worker/github-token
ENV
fi
chmod 0640 "${CONFIG_DIR}/worker.env"
chown root:"${WORKER_USER}" "${CONFIG_DIR}/worker.env"
cat > /etc/systemd/system/codexbridge-worker.service <<UNIT
[Unit]
Description=CodexBridge GitHub control branch to Gateway intake
Wants=network-online.target
After=network-online.target

[Service]
Type=simple
User=${WORKER_USER}
Group=${WORKER_USER}
EnvironmentFile=${CONFIG_DIR}/worker.env
WorkingDirectory=${INSTALL_DIR}
ExecStart=/usr/bin/python3 ${INSTALL_DIR}/scripts/worker_watch.py --forward-gateway --interval 60 --state-file /var/lib/codexbridge-worker/state.json
Restart=on-failure
RestartSec=15
NoNewPrivileges=true
ProtectSystem=strict
ProtectHome=true
ReadWritePaths=/var/lib/codexbridge-worker
PrivateTmp=true
UMask=0077

[Install]
WantedBy=multi-user.target
UNIT
systemctl daemon-reload
echo "Installed, NOT started. Put worker-token and github-token (chmod 0640, chown root:${WORKER_USER}) in ${CONFIG_DIR}, register/activate projects and obtain a Gateway lease before starting."
