#!/usr/bin/env bash
# Package a tested checkout on devel3, transfer via SSH; NO git on Frida.
# This command STAGES ONLY. No database writes, restart or live file changes.
set -euo pipefail
cd "$(dirname "$0")/.."
ROOT="$PWD"
FRIDA_HOST="${FRIDA_HOST:-esteban@frida.inovacaosistemas.com.br}"
FRIDA_PORT="${FRIDA_PORT:-2200}"
RELEASE_ID="$(date -u +%Y%m%dT%H%M%SZ)"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

[[ "$FRIDA_PORT" =~ ^[0-9]+$ ]] || { echo 'Invalid port' >&2; exit 2; }
command -v git >/dev/null || { echo 'git required only on build host' >&2; exit 2; }
command -v ssh >/dev/null || { echo 'ssh required' >&2; exit 2; }
command -v scp >/dev/null || { echo 'scp required' >&2; exit 2; }
[[ -f "$ROOT/migrations/0022_worker_lease_serialization.sql" ]] || {
    echo 'Missing migration 0022; update the DEVELOPMENT checkout first' >&2; exit 2;
}
[[ -f "$ROOT/scripts/worker_identity.py" ]] || { echo 'Missing worker identity CLI' >&2; exit 2; }
# Create the source archive on devel3, with only tracked content.
# No .git tree, environment, local databases, token files or untracked data.
git archive --format=tar --prefix=codex-bridge/ HEAD | gzip -n > "$WORK/codex-bridge.tar.gz"
sha256sum "$WORK/codex-bridge.tar.gz" | awk '{print $1}' > "$WORK/archive.sha256"
echo "Source commit: $(git rev-parse --short=12 HEAD)"
echo "Archive sha256: $(cat "$WORK/archive.sha256")"
# Verify remote prerequisites without reading or printing configuration.
ssh -p "$FRIDA_PORT" "$FRIDA_HOST" '
  set -eu
  test -d /opt/codex-bridge
  test -f /etc/codex-bridge/env
  systemctl is-active --quiet codex-bridge-gateway
  printf "Gateway active; existing deploy dir and config present\n"
'
# Frida has no git and will not acquire one. Stage under the SSH account.
ssh -p "$FRIDA_PORT" "$FRIDA_HOST" 'mkdir -p "$HOME/codexbridge-staging" && chmod 700 "$HOME/codexbridge-staging"'
scp -P "$FRIDA_PORT" "$WORK/codex-bridge.tar.gz" "$FRIDA_HOST:codexbridge-staging/${RELEASE_ID}.tar.gz"
scp -P "$FRIDA_PORT" "$WORK/archive.sha256" "$FRIDA_HOST:codexbridge-staging/${RELEASE_ID}.sha256"
ssh -p "$FRIDA_PORT" "$FRIDA_HOST" "
  set -eu
  cd \"\$HOME/codexbridge-staging\"
  test \"\$(sha256sum ${RELEASE_ID}.tar.gz | awk '{print \$1}')\" = \"\$(cat ${RELEASE_ID}.sha256)\"
  tar -tzf ${RELEASE_ID}.tar.gz | grep -q '^codex-bridge/migrations/0022_worker_lease_serialization.sql\$'
  printf 'Verified stage: %s\n' '${RELEASE_ID}'
"
printf '\nSTAGED, NOT APPLIED. Frida gateway untouched. Release ID: %s\n' "$RELEASE_ID"
