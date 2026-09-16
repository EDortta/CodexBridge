#!/usr/bin/env bash
set -euo pipefail

ROOT="$(git rev-parse --show-toplevel)"
cd "$ROOT"

PROJECT_ID="codexbridge"
PROJECT_NAME="CodexBridge"
WORKSPACE="/srv/projects/CodexBridge"
AGENT_ENV="/etc/codex-bridge-agent/env"
AGENT_PROJECTS="/etc/codex-bridge-agent/projects.json"
FRIDA_HOST="esteban@frida.inovacaosistemas.com.br"
FRIDA_PORT="2200"
OUT="temp-tools/results/$(date -u +%Y%m%d-%H%M%SZ)-self-onboard-codexbridge.txt"
mkdir -p temp-tools/results

exec > >(tee "$OUT") 2>&1

echo "== CodexBridge self-onboarding =="
[[ -d .git ]] || { echo "ERROR: rode na raiz do repo CodexBridge"; exit 2; }
sudo test -f "$AGENT_ENV" || { echo "ERROR: $AGENT_ENV ausente"; exit 2; }
sudo test -f "$AGENT_PROJECTS" || { echo "ERROR: $AGENT_PROJECTS ausente"; exit 2; }
ssh -p "$FRIDA_PORT" "$FRIDA_HOST" 'sudo test -f /etc/codex-bridge/registry.json && sudo test -f /etc/codex-bridge/users.json'

EXECUTOR_ID="$(sudo sed -n 's/^CODEX_BRIDGE_AGENT_EXECUTOR_ID=//p' "$AGENT_ENV" | tail -1)"
[[ -n "$EXECUTOR_ID" ]] || { echo "ERROR: executor id ausente no env"; exit 2; }
echo "executor=$EXECUTOR_ID"

# Keep the runtime workspace outside /home so the hardened systemd service can write it.
echo "== workspace =="
if [[ -e "$WORKSPACE" ]]; then
  sudo test -d "$WORKSPACE/.git" || { echo "ERROR: $WORKSPACE existe mas não é git"; exit 2; }
  if [[ -n "$(sudo git -C "$WORKSPACE" status --porcelain)" ]]; then
    echo "ERROR: $WORKSPACE tem mudanças locais; não vou sobrescrever"; exit 2
  fi
  sudo git -C "$WORKSPACE" fetch "$ROOT" development
  sudo git -C "$WORKSPACE" checkout -q development || sudo git -C "$WORKSPACE" checkout -q -B development FETCH_HEAD
  sudo git -C "$WORKSPACE" reset --hard FETCH_HEAD
else
  sudo mkdir -p /srv/projects
  sudo git clone -q --shared "$ROOT" "$WORKSPACE"
  sudo git -C "$WORKSPACE" checkout -q development
fi
sudo chown -R codexbridge:codexbridge "$WORKSPACE"

# Canonical local allowlist.
echo "== local project allowlist =="
sudo python3 - "$AGENT_PROJECTS" "$PROJECT_ID" "$PROJECT_NAME" "$WORKSPACE" <<'PY'
import json, pathlib, shutil, sys, time
path = pathlib.Path(sys.argv[1]); pid, name, workspace = sys.argv[2:]
data = json.loads(path.read_text())
projects = data.setdefault("projects", [])
existing = next((p for p in projects if p.get("project_id") == pid), None)
entry = {
    "project_id": pid,
    "name": name,
    "path": workspace,
    "allowed_modes": ["analyze", "review", "edit", "test", "implement"],
    "max_timeout_seconds": 3600,
    "sensitive_patterns": ["deploy", "migration", "push"],
    "enabled": True,
}
if existing is None:
    projects.append(entry)
else:
    existing.update(entry)
backup = path.with_suffix(path.suffix + f".bak-{int(time.time())}")
shutil.copy2(path, backup)
path.write_text(json.dumps(data, indent=2) + "\n")
print(f"local_project={pid} backup={backup}")
PY

# Ensure the system service reads the canonical file we just updated.
if sudo grep -q '^CODEX_BRIDGE_AGENT_ALLOWED_PROJECTS_FILE=' "$AGENT_ENV"; then
  sudo sed -i 's#^CODEX_BRIDGE_AGENT_ALLOWED_PROJECTS_FILE=.*#CODEX_BRIDGE_AGENT_ALLOWED_PROJECTS_FILE=/etc/codex-bridge-agent/projects.json#' "$AGENT_ENV"
else
  echo 'CODEX_BRIDGE_AGENT_ALLOWED_PROJECTS_FILE=/etc/codex-bridge-agent/projects.json' | sudo tee -a "$AGENT_ENV" >/dev/null
fi

# Update gateway + the single configured human user atomically after validation.
echo "== gateway/user authorization =="
ssh -p "$FRIDA_PORT" "$FRIDA_HOST" "sudo python3 - '$EXECUTOR_ID' '$PROJECT_ID' '$PROJECT_NAME'" <<'PY'
import json, pathlib, shutil, sys, time
executor_id, pid, name = sys.argv[1:]
regp = pathlib.Path('/etc/codex-bridge/registry.json')
userp = pathlib.Path('/etc/codex-bridge/users.json')
reg = json.loads(regp.read_text())
users = json.loads(userp.read_text())
matched = [e for e in reg.get('executors', []) if e.get('executor_id') == executor_id]
if len(matched) != 1:
    raise SystemExit(f'ERROR: executor {executor_id!r} encontrado {len(matched)} vezes no registry')
user_rows = users.get('users', [])
if len(user_rows) != 1:
    ids = [u.get('user_id') for u in user_rows]
    raise SystemExit(f'ERROR: esperado exatamente 1 usuário para bootstrap; encontrados {ids}')
projects = reg.setdefault('projects', [])
entry = {
    'project_id': pid,
    'name': name,
    'path': '/srv/projects/CodexBridge',
    'allowed_modes': ['analyze','review','edit','test','implement'],
    'max_timeout_seconds': 3600,
    'sensitive_patterns': ['deploy','migration','push'],
    'enabled': True,
}
existing = next((p for p in projects if p.get('project_id') == pid), None)
if existing is None: projects.append(entry)
else: existing.update(entry)
allowed = matched[0].setdefault('allowed_projects', [])
if pid not in allowed: allowed.append(pid)
ual = user_rows[0].setdefault('allowed_projects', [])
if pid not in ual: ual.append(pid)
stamp = int(time.time())
for path, data in ((regp, reg), (userp, users)):
    shutil.copy2(path, path.with_suffix(path.suffix + f'.bak-{stamp}'))
    path.write_text(json.dumps(data, indent=2) + '\n')
print(f'gateway_project={pid} executor={executor_id} user={user_rows[0].get("user_id")}')
PY

# Avoid two agents competing for the same executor id.
echo "== restart services =="
LEGACY_PIDS="$(pgrep -f '/home/esteban/.local/share/codex-bridge/.venv/bin/python -m agent.codex_bridge_agent.service' || true)"
if [[ -n "$LEGACY_PIDS" ]]; then
  kill $LEGACY_PIDS || true
  sleep 1
fi
sudo systemctl restart codex-bridge-agent.service
sudo systemctl is-active --quiet codex-bridge-agent.service
ssh -p "$FRIDA_PORT" "$FRIDA_HOST" 'sudo systemctl restart codex-bridge-gateway.service && sudo systemctl is-active --quiet codex-bridge-gateway.service'

sleep 3
echo "agent=$(sudo systemctl is-active codex-bridge-agent.service)"
echo "gateway=$(ssh -p "$FRIDA_PORT" "$FRIDA_HOST" 'sudo systemctl is-active codex-bridge-gateway.service')"
echo "project=$PROJECT_ID"
echo "workspace=$WORKSPACE"
echo "SELF_ONBOARD_OK"

git add "$OUT"
git commit -m "results: self-onboard CodexBridge on devel3" || true
git push origin development
