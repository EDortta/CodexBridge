#!/usr/bin/env bash
# Explicit operator-controlled live application of a staged release on Frida.
# Run ON FRIDA with sudo, after staging from devel3. No git dependency.
set -euo pipefail
if [[ "$EUID" -ne 0 || "$#" -ne 2 || "$1" != "--apply" ]]; then
  echo "Usage: sudo bash apply-frida-staged-release.sh --apply YYYYMMDDTHHMMSSZ" >&2
  exit 2
fi
ID="$2"
[[ "$ID" =~ ^[0-9]{8}T[0-9]{6}Z$ ]] || { echo "Invalid release ID" >&2; exit 2; }
DEPLOY_USER="${SUDO_USER:-}"
[[ -n "$DEPLOY_USER" && "$DEPLOY_USER" != root ]] || { echo "Run via sudo from staging user" >&2; exit 2; }
STAGING="$(getent passwd "$DEPLOY_USER" | cut -d: -f6)/codexbridge-staging"
ARCHIVE="$STAGING/$ID.tar.gz"
HASH="$STAGING/$ID.sha256"
[[ -f "$ARCHIVE" && -f "$HASH" ]] || { echo "Missing verified staged files" >&2; exit 2; }
[[ "$(sha256sum "$ARCHIVE" | awk '{print $1}')" == "$(cat "$HASH")" ]] || { echo "Archive hash mismatch" >&2; exit 2; }
[[ -x /opt/codex-bridge/.venv/bin/python ]] || { echo "Existing Python venv missing" >&2; exit 2; }
[[ -f /etc/codex-bridge/env ]] || { echo "Gateway environment missing" >&2; exit 2; }
systemctl is-active --quiet codex-bridge-gateway || { echo "Gateway must be running before deployment" >&2; exit 2; }
# Read ONLY the database URL key. EnvironmentFile is not a shell script.
DBURL="$(sed -n 's/^CODEX_BRIDGE_DATABASE_URL=//p' /etc/codex-bridge/env | tail -n 1)"
[[ "$DBURL" == sqlite* ]] || { echo "Unsupported/absent SQLite database URL; manual review required" >&2; exit 2; }
# sqlite:///absolute/path => four slash characters total.
DBPATH="${DBURL#sqlite+aiosqlite:///}"
if [[ "$DBPATH" == "$DBURL" ]]; then DBPATH="${DBURL#sqlite:///}"; fi
[[ "$DBPATH" == /* && -f "$DBPATH" ]] || { echo "Database must resolve to an absolute existing SQLite file" >&2; exit 2; }
BACKUP="/var/backups/codexbridge/$ID"
mkdir -p "$BACKUP"
chmod 0700 "$BACKUP"
# SQLite online backup guarantees consistency even with WAL in use.
python3 - "$DBPATH" "$BACKUP/database.sqlite3" <<'PY'
import sqlite3, sys
source = sqlite3.connect(f"file:{sys.argv[1]}?mode=ro", uri=True, timeout=30)
destination = sqlite3.connect(sys.argv[2], timeout=30)
try:
    assert source.execute("pragma quick_check").fetchone()[0] == "ok"
    source.backup(destination, pages=256, sleep=0.1)
    assert destination.execute("pragma integrity_check").fetchone()[0] == "ok"
finally:
    destination.close()
    source.close()
PY
echo "Database backup verified: $BACKUP/database.sqlite3"
mkdir -p "$BACKUP/old-code" "$BACKUP/incoming"
tar -xzf "$ARCHIVE" -C "$BACKUP/incoming"
[[ -f "$BACKUP/incoming/codex-bridge/migrations/0022_worker_lease_serialization.sql" ]] || exit 2
rsync -a --exclude '.venv/' --exclude '*.db' --exclude '*.sqlite*' \
  /opt/codex-bridge/ "$BACKUP/old-code/"
echo "Existing application backed up: $BACKUP/old-code"
echo "Stopping Gateway briefly for schema/application update"
systemctl stop codex-bridge-gateway
# Keep virtualenv, db and configuration (these are NOT release assets).
rsync -a --exclude '.venv/' --exclude '*.db' --exclude '*.sqlite*' \
  "$BACKUP/incoming/codex-bridge/" /opt/codex-bridge/
chown -R codexbridge:codexbridge /opt/codex-bridge
# Migration runner is intentionally explicit and uses the ACTUAL database URL.
set +e
sudo -u codexbridge /opt/codex-bridge/.venv/bin/python \
  /opt/codex-bridge/scripts/apply_migrations.py --database-url "$DBURL"
MIGRATE_STATUS=$?
set -e
if (( MIGRATE_STATUS != 0 )); then
  echo "Migration failed. Gateway remains STOPPED. Database backup is $BACKUP/database.sqlite3" >&2
  exit 1
fi
systemctl start codex-bridge-gateway
sleep 3
if ! systemctl is-active --quiet codex-bridge-gateway || \
    ! curl --fail --silent --max-time 10 http://127.0.0.1:18080/health >/dev/null; then
  echo "Health check failed; Gateway requires operator intervention. Backup: $BACKUP" >&2
  exit 1
fi
echo "Release $ID deployed; Gateway active and local /health succeeded."
echo "Backup preserved at $BACKUP"
