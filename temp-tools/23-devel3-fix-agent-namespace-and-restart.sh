#!/usr/bin/env bash
set -euo pipefail

ROOT="$(git rev-parse --show-toplevel)"
cd "$ROOT"

echo "== fix agent namespace paths =="
sudo install -d -m 0750 -o codexbridge -g codexbridge /home/codexbridge
sudo install -d -m 0700 -o codexbridge -g codexbridge /home/codexbridge/.codex
sudo install -d -m 0700 -o codexbridge -g codexbridge /home/codexbridge/.claude

echo "== restart agent =="
sudo systemctl reset-failed codex-bridge-agent.service || true
sudo systemctl restart codex-bridge-agent.service
sleep 2
sudo systemctl is-active --quiet codex-bridge-agent.service
sudo systemctl --no-pager --full status codex-bridge-agent.service | sed -n '1,14p'

echo "== processes =="
pgrep -af 'agent.codex_bridge_agent.service' || true

echo "AGENT_OK"
