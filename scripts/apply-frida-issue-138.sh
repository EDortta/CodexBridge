#!/usr/bin/env bash
# Explicitly invoked ON frida via sudo. No Git, no migrations, no DB restoration.
# Update is restricted to four OAuth files; failure automatically restores them.
set -Eeuo pipefail
if (( EUID != 0 )) || [[ "$#" -ne 2 || ( "$1" != "--apply" && "$1" != "--check" ) ]]; then
  echo "Usage: sudo bash apply-frida-issue-138.sh --check|--apply issue138-YYYYMMDDTHHMMSSZ" >&2
  exit 2
fi
MODE="$1"
ID="$2"
[[ "$ID" =~ ^issue138-[0-9]{8}T[0-9]{6}Z$ ]] || { echo "Invalid patch ID" >&2; exit 2; }
DEPLOY_USER="${SUDO_USER:-}"
[[ -n "$DEPLOY_USER" && "$DEPLOY_USER" != root ]] || { echo "sudo must be invoked by staging user" >&2; exit 2; }
HOME_DIR="$(getent passwd "$DEPLOY_USER" | cut -d: -f6)"
STAGE="$HOME_DIR/codexbridge-staging/$ID"
BACKUP="/var/backups/codexbridge/$ID"
TARGET="/opt/codex-bridge"
SERVICE="codex-bridge-gateway"
FILES=(
  gateway/app/main.py
  gateway/app/api/routes/auth.py
  gateway/app/core/config.py
  gateway/app/core/oauth.py
)
[[ -f "$STAGE/patch.tar.gz" && -f "$STAGE/patch.sha256" && -f "$STAGE/checksums.txt" ]] || {
  echo "Stage incomplete" >&2; exit 2;
}
[[ "$(sha256sum "$STAGE/patch.tar.gz" | cut -d' ' -f1)" == "$(cat "$STAGE/patch.sha256")" ]] || {
  echo "Archive checksum mismatch" >&2; exit 2;
}
[[ "$(head -n 1 "$STAGE/checksums.txt")" == "ISSUE_138_PATCH_V1" ]] || exit 2
[[ "$(wc -l < "$STAGE/checksums.txt")" == 5 ]] || exit 2
[[ -d "$TARGET" && -f /etc/codex-bridge/env ]] || exit 2
systemctl is-active --quiet "$SERVICE" || { echo "Gateway not active" >&2; exit 2; }
curl -fsS --max-time 5 http://127.0.0.1:18080/health >/dev/null || exit 2
# Guard against silently overwriting a different production baseline.
for file in "${FILES[@]}"; do
  read -r observed expected_before expected_after < <(grep -F "$file " "$STAGE/checksums.txt")
  [[ "$observed" == "$file" ]] || { echo "Missing manifest entry: $file" >&2; exit 2; }
  [[ -f "$TARGET/$file" && ! -L "$TARGET/$file" ]] || { echo "Target missing or symlinked: $file" >&2; exit 2; }
  [[ "$(sha256sum "$TARGET/$file" | cut -d' ' -f1)" == "$expected_before" ]] || {
    echo "REFUSED: running $file differs from origin/development baseline; inspect before changing production" >&2
    exit 3
  }
done
# Reject surprising files, links and duplicates inside archive; no arbitrary extraction.
EXPECTED="$(printf 'patch/%s\n' "${FILES[@]}" | LC_ALL=C sort)"
ACTUAL="$(tar -tzf "$STAGE/patch.tar.gz" | grep -v '/$' | LC_ALL=C sort)"
[[ "$ACTUAL" == "$EXPECTED" ]] || { echo "Unexpected archive contents" >&2; exit 2; }
# Verify candidate bytes from signed-off manifest, not only outer archive hash.
while read -r file _before candidate_sha; do
  [[ "$file" == "ISSUE_138_PATCH_V1" ]] && continue
  staged_sha="$(tar -xzOf "$STAGE/patch.tar.gz" "patch/$file" | sha256sum | cut -d' ' -f1)"
  [[ "$staged_sha" == "$candidate_sha" ]] || {
    echo "Candidate file hash mismatch: $file" >&2; exit 2;
  }
done < "$STAGE/checksums.txt"
if [[ "$MODE" == "--check" ]]; then
  printf 'CHECK=ok\\nBASELINE=matched\\nARCHIVE=verified\\nLIVE_FILES_UNCHANGED=1\\n'
  exit 0
fi
umask 077
[[ ! -e "$BACKUP" ]] || { echo "Backup target exists: $BACKUP" >&2; exit 2; }
mkdir -p "$BACKUP/old" "$BACKUP/new"
tar -xzf "$STAGE/patch.tar.gz" -C "$BACKUP/new" --no-same-owner --no-same-permissions
for file in "${FILES[@]}"; do
  [[ -f "$BACKUP/new/patch/$file" && ! -L "$BACKUP/new/patch/$file" ]] || exit 2
  cp -a --parents "$TARGET/$file" "$BACKUP/old/"
done
# The backup carries full original path under old/opt/codex-bridge.
restore() {
  echo "ROLLBACK: restoring previous OAuth code" >&2
  for file in "${FILES[@]}"; do
    cp -a "$BACKUP/old/opt/codex-bridge/$file" "$TARGET/$file"
  done
  systemctl restart "$SERVICE" || true
  for i in $(seq 1 30); do
    if systemctl is-active --quiet "$SERVICE" && \
       curl -fsS --max-time 3 http://127.0.0.1:18080/health >/dev/null; then
      echo "ROLLBACK_HEALTH=ok"
      return 0
    fi
    sleep 2
  done
  echo "ROLLBACK_HEALTH=failed; manual recovery required; backup=$BACKUP" >&2
  return 1
}
CHANGED=0
rollback_on_exit() {
  local rc=$?
  trap - EXIT
  if (( rc != 0 && CHANGED == 1 )); then
    restore || true
  fi
  exit "$rc"
}
trap rollback_on_exit EXIT
# Compile candidate before touching service. Production interpreter is authoritative.
PYTHONDONTWRITEBYTECODE=1 "$TARGET/.venv/bin/python" -B -m py_compile \
  "${FILES[@]/#/$BACKUP/new/patch/}" 2>/dev/null || {
    echo "Candidate Python syntax check failed" >&2; exit 2;
  }
CHANGED=1
systemctl stop "$SERVICE"
for file in "${FILES[@]}"; do
  install -o codexbridge -g codexbridge -m 0644 "$BACKUP/new/patch/$file" "$TARGET/$file"
done
systemctl start "$SERVICE"
READY=0
for i in $(seq 1 30); do
  if systemctl is-active --quiet "$SERVICE" && \
     curl -fsS --max-time 3 http://127.0.0.1:18080/health >/dev/null; then
    READY=1
    break
  fi
  sleep 2
done
[[ "$READY" == 1 ]] || { echo "Gateway failed health check" >&2; exit 1; }
# Check that the new OAuth discovery is live locally (no secrets).
curl -fsS --max-time 5 http://127.0.0.1:18080/.well-known/oauth-authorization-server \
  | "$TARGET/.venv/bin/python" -c '
import json,sys
obj=json.load(sys.stdin)
assert "refresh_token" in obj.get("grant_types_supported", []), "refresh grant not advertised"
' || { echo "OAuth discovery check failed" >&2; exit 1; }
trap - EXIT
printf 'APPLIED=%s\nHEALTH=ok\nOAUTH_REFRESH_DISCOVERY=ok\nBACKUP=%s\n' "$ID" "$BACKUP"
