#!/usr/bin/env bash
set -euo pipefail

cd "$(git rev-parse --show-toplevel)"

HOST="codexbridge.inovacaosistemas.com.br"
BASE="https://${HOST}"
STAMP="$(date -u +%Y%m%d-%H%M%SZ)"
RESULT="temp-tools/results/${STAMP}-canonical-443.txt"
mkdir -p temp-tools/results
exec > >(tee "$RESULT") 2>&1

echo "== Canonicalize CodexBridge on 443 =="
echo "canonical=${BASE}"

echo "== preflight =="
curl -fsS "${BASE}/health"
echo
curl -fsS "${BASE}/.well-known/oauth-authorization-server" || true
echo

# The live Gateway has historically been managed through Frida. 443 may reach it
# through the current T610 ingress, but public OAuth identity must match the URL
# already registered in ChatGPT: https://codexbridge.inovacaosistemas.com.br/mcp
ssh -p 2200 esteban@frida.inovacaosistemas.com.br "BASE='$BASE' bash -s" <<'REMOTE'
set -euo pipefail
ENV=/etc/codex-bridge/env
sudo test -f "$ENV"
BACKUP="/var/backups/codex-bridge/canonical-443-$(date -u +%Y%m%d-%H%M%SZ)"
sudo mkdir -p "$BACKUP"
sudo cp -a "$ENV" "$BACKUP/env"
echo "backup=$BACKUP"
if sudo grep -q '^CODEX_BRIDGE_PUBLIC_BASE_URL=' "$ENV"; then
  sudo sed -i "s#^CODEX_BRIDGE_PUBLIC_BASE_URL=.*#CODEX_BRIDGE_PUBLIC_BASE_URL=${BASE}#" "$ENV"
else
  echo "CODEX_BRIDGE_PUBLIC_BASE_URL=${BASE}" | sudo tee -a "$ENV" >/dev/null
fi
sudo systemctl restart codex-bridge-gateway.service
for i in $(seq 1 30); do
  curl -fsS http://127.0.0.1:18080/health >/dev/null 2>&1 && break
  sleep 1
done
curl -fsS http://127.0.0.1:18080/health >/dev/null
echo "gateway_restart=ok"
sudo sed -n 's/^CODEX_BRIDGE_PUBLIC_BASE_URL=/public_base_url=/p' "$ENV"
REMOTE

echo "== point devel3 agent WebSocket to 443 =="
AGENT_ENV=/etc/codex-bridge-agent/env
if sudo test -f "$AGENT_ENV"; then
  sudo cp "$AGENT_ENV" "${AGENT_ENV}.bak-${STAMP}"
  if sudo grep -q '^CODEX_BRIDGE_AGENT_GATEWAY_WS_URL=' "$AGENT_ENV"; then
    sudo sed -i "s#^CODEX_BRIDGE_AGENT_GATEWAY_WS_URL=.*#CODEX_BRIDGE_AGENT_GATEWAY_WS_URL=wss://${HOST}/agent/ws#" "$AGENT_ENV"
  fi
  sudo systemctl restart codex-bridge-agent.service
  sleep 3
  sudo systemctl is-active --quiet codex-bridge-agent.service
  echo "devel3_agent=active"
fi

echo "== update repository defaults =="
python3 - <<'PY'
from pathlib import Path
old='https://codexbridge.inovacaosistemas.com.br:8443'
new='https://codexbridge.inovacaosistemas.com.br'
for name in ['.env.example','gateway/app/core/config.py','docs/installation.md']:
    p=Path(name)
    if p.exists():
        s=p.read_text()
        if old in s:
            p.write_text(s.replace(old,new))
            print('updated='+name)
PY

echo "== validate ChatGPT-facing OAuth metadata =="
for path in \
  '/.well-known/oauth-authorization-server' \
  '/.well-known/openid-configuration' \
  '/.well-known/oauth-protected-resource' \
  '/.well-known/oauth-protected-resource/mcp'
do
  body="$(curl -fsS -H 'Cache-Control: no-cache' "${BASE}${path}")"
  echo "$path => $body"
  if printf '%s' "$body" | grep -q ':8443'; then
    echo "ERROR: ${path} still advertises :8443" >&2
    exit 1
  fi
done

python3 - <<'PY'
import json, urllib.request
base='https://codexbridge.inovacaosistemas.com.br'
with urllib.request.urlopen(base+'/.well-known/oauth-authorization-server') as r:
    auth=json.load(r)
assert auth.get('issuer') == base, auth
assert auth.get('authorization_endpoint') == base+'/oauth/authorize', auth
assert auth.get('token_endpoint') == base+'/oauth/token', auth
assert 'S256' in auth.get('code_challenge_methods_supported', []), auth
with urllib.request.urlopen(base+'/.well-known/oauth-protected-resource/mcp') as r:
    pr=json.load(r)
assert pr.get('resource') == base+'/mcp', pr
assert pr.get('authorization_servers') == [base], pr
print('oauth_443=ok')
PY

echo "CODEXBRIDGE_CANONICAL_443_READY"

git add .env.example gateway/app/core/config.py docs/installation.md "$RESULT"
if ! git diff --cached --quiet; then
  git commit -m "ops: canonicalize CodexBridge on bare 443"
  git push origin development
fi
