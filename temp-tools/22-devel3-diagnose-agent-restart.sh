#!/usr/bin/env bash
set -euo pipefail

ROOT="$(git rev-parse --show-toplevel)"
cd "$ROOT"
OUT="temp-tools/results/$(date -u +%Y%m%d-%H%M%SZ)-devel3-agent-restart.txt"
mkdir -p temp-tools/results

{
  echo "== service =="
  sudo systemctl status codex-bridge-agent.service --no-pager --full || true
  echo
  echo "== journal =="
  sudo journalctl -u codex-bridge-agent.service -n 80 --no-pager || true
  echo
  echo "== files =="
  sudo ls -ld /opt/codex-bridge /opt/codex-bridge/.venv /etc/codex-bridge-agent /var/lib/codex-bridge-agent 2>&1 || true
  sudo ls -l /etc/codex-bridge-agent/env /etc/codex-bridge-agent/projects.json 2>&1 || true
  echo
  echo "== env keys only =="
  sudo sed -n 's/^\([A-Za-z_][A-Za-z0-9_]*\)=.*/\1/p' /etc/codex-bridge-agent/env 2>/dev/null | sort || true
  echo
  echo "== referenced paths =="
  APF="$(sudo sed -n 's/^CODEX_BRIDGE_AGENT_ALLOWED_PROJECTS_FILE=//p' /etc/codex-bridge-agent/env 2>/dev/null | tail -1)"
  MTF="$(sudo sed -n 's/^CODEX_BRIDGE_AGENT_MACHINE_TOKEN_FILE=//p' /etc/codex-bridge-agent/env 2>/dev/null | tail -1)"
  printf 'allowed_projects_file=%s exists=%s\n' "${APF:-<unset>}" "$( [ -n "$APF" ] && [ -f "$APF" ] && echo yes || echo no )"
  printf 'machine_token_file=%s exists=%s\n' "${MTF:-<unset>}" "$( [ -n "$MTF" ] && [ -f "$MTF" ] && echo yes || echo no )"
  echo
  echo "== python/import =="
  sudo -u codexbridge /opt/codex-bridge/.venv/bin/python - <<'PY' 2>&1 || true
import sys
print(sys.executable)
import agent.codex_bridge_agent.service
print('import_ok')
PY
  echo
  echo "== processes =="
  pgrep -af 'agent.codex_bridge_agent.service' || true
} | tee "$OUT"

git add "$OUT"
git commit -m "results: diagnose devel3 agent restart" || true
git push origin development

echo "Wrote $OUT"
