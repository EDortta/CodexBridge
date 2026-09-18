#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(git rev-parse --show-toplevel)"
cd "$REPO_ROOT"

STAMP="$(date -u +%Y%m%d-%H%M%SZ)"
OUT="temp-tools/results/${STAMP}-repair-oauth-registry-permissions.txt"
mkdir -p temp-tools/results
exec > >(tee "$OUT") 2>&1

if [ -f temp-tools/lib/result-publisher.sh ]; then
  source temp-tools/lib/result-publisher.sh
fi

FRIDA=(ssh -p 2200 -o StrictHostKeyChecking=accept-new esteban@frida.inovacaosistemas.com.br)

echo "== Repair CodexBridge OAuth registry permissions =="
echo "utc=$(date -u +%FT%TZ)"
echo

"${FRIDA[@]}" 'bash -s' <<'REMOTE'
set -euo pipefail

OLD="/etc/codex-bridge/users.json"
NEW_DIR="/etc/codex-bridge/auth"
NEW="/etc/codex-bridge/auth/users.json"
ENV="/etc/codex-bridge/env"
STAMP="$(date -u +%Y%m%d-%H%M%SZ)"
BACKUP="/var/backups/codex-bridge/oauth-registry-${STAMP}"

echo "== current state =="
sudo ls -ld /etc/codex-bridge
sudo ls -l "$OLD" 2>/dev/null || true
sudo grep '^CODEX_BRIDGE_USER_REGISTRY_FILE=' "$ENV" 2>/dev/null || true

echo
echo "== backup =="
sudo mkdir -p "$BACKUP"
sudo cp -a "$ENV" "$BACKUP/env"
sudo cp -a "$OLD" "$BACKUP/users.json"
echo "backup=$BACKUP"

echo
echo "== install dedicated writable auth registry directory =="
sudo install -d -o codexbridge -g codexbridge -m 0700 "$NEW_DIR"
sudo install -o codexbridge -g codexbridge -m 0600 "$OLD" "$NEW"

echo
echo "== point gateway at dedicated registry =="
sudo python3 - "$ENV" "$NEW" <<'PY'
from pathlib import Path
import sys

path = Path(sys.argv[1])
new = sys.argv[2]
lines = path.read_text(encoding="utf-8").splitlines()
key = "CODEX_BRIDGE_USER_REGISTRY_FILE="
out = []
replaced = False
for line in lines:
    if line.startswith(key):
        if not replaced:
            out.append(key + new)
            replaced = True
        continue
    out.append(line)
if not replaced:
    out.append(key + new)
path.write_text("\n".join(out) + "\n", encoding="utf-8")
PY

sudo chmod 0600 "$ENV"

echo
echo "== prove service account can read and atomically replace in auth directory =="
sudo -u codexbridge test -r "$NEW"
sudo -u codexbridge test -w "$NEW"
sudo -u codexbridge sh -c 'tmp=/etc/codex-bridge/auth/.write-test-$$; : > "$tmp"; rm -f "$tmp"'
echo "service_registry_access=ok"

echo
echo "== restart gateway =="
sudo systemctl restart codex-bridge-gateway.service
sleep 3
sudo systemctl is-active codex-bridge-gateway.service

echo
echo "== verify effective settings and user lookup as service account =="
sudo -u codexbridge bash -lc 'cd /opt/codex-bridge && /opt/codex-bridge/.venv/bin/python3 - <<'"'"'PY'"'"'
from gateway.app.core.config import settings
from gateway.app.core.users import lookup_user, unusable_registry_reason
print("registry_path=" + settings.user_registry_file)
print("registry_reason=" + str(unusable_registry_reason(settings.user_registry_file)))
u = lookup_user(settings.user_registry_file, "edortta71@gmail.com")
print("lookup_user=" + ("found" if u else "missing"))
if u:
    print("user_id=" + u.user_id)
    print("email=" + u.email)
    print("enabled=" + str(u.enabled))
PY'

echo
echo "== recent auth warnings after restart =="
sudo journalctl -u codex-bridge-gateway.service --since "2 minutes ago" --no-pager   | grep -E 'user registry|PermissionError|oauth/authorize' || true
REMOTE

echo
echo "== external health from devel3 =="
curl -fsS --connect-timeout 8 --max-time 20 https://codexbridge.inovacaosistemas.com.br/health
echo

echo "CODEXBRIDGE_OAUTH_REGISTRY_PERMISSIONS_READY"
