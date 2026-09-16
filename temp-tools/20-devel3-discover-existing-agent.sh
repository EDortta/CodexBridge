#!/usr/bin/env bash
set -euo pipefail

ROOT="$(git rev-parse --show-toplevel)"
cd "$ROOT"

OUT="temp-tools/results/$(date -u +%Y%m%d-%H%M%SZ)-devel3-agent-discovery.txt"
mkdir -p "$(dirname "$OUT")"
exec > >(tee "$OUT") 2>&1

echo "== host =="
hostname
id

echo "== systemd units containing codex/bridge =="
systemctl list-unit-files --type=service --no-pager | grep -Ei 'codex|bridge' || true
systemctl list-units --type=service --all --no-pager | grep -Ei 'codex|bridge' || true

echo "== running processes =="
ps -ef | grep -Ei 'codex[_-]?bridge|codex_bridge_agent|agent\.codex' | grep -v grep || true

echo "== candidate config dirs/files =="
sudo find /etc /opt /var/lib -maxdepth 4 \
  \( -iname '*codex*bridge*' -o -iname 'projects.json' -o -iname 'machine-token' \) \
  -print 2>/dev/null | sort || true

echo "== user =="
getent passwd codexbridge || true

echo "== /srv/projects =="
sudo find /srv/projects -maxdepth 2 -type d -name .git -printf '%h\n' 2>/dev/null | sort || true

echo "== result =="
echo "Wrote $OUT"
