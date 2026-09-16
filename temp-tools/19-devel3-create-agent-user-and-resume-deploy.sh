#!/usr/bin/env bash
set -euo pipefail

ROOT="$(git rev-parse --show-toplevel)"
cd "$ROOT"

if getent passwd codexbridge >/dev/null; then
  echo "codexbridge user already exists"
else
  sudo useradd --system --create-home --home-dir /var/lib/codex-bridge-agent codexbridge
  echo "created system user codexbridge"
fi

exec bash temp-tools/18-devel3-deploy-chatgpt-ready-frida-ssh.sh
