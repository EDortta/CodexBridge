#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(git rev-parse --show-toplevel)"
cd "$REPO_ROOT"

FRIDA_HOST="esteban@frida.inovacaosistemas.com.br"
FRIDA_SSH_PORT=2200
PUBLIC_HOST="codexbridge.inovacaosistemas.com.br"
OUT="temp-tools/results/$(date -u +%Y%m%d-%H%M%SZ)-repair-frida-8443.txt"
mkdir -p temp-tools/results
exec > >(tee "$OUT") 2>&1

echo "== CodexBridge active 8443 repair =="
echo "utc=$(date -u +%Y-%m-%dT%H:%M:%SZ)"

echo "== current external state from devel3 =="
set +e
curl -fsS --connect-timeout 6 "https://${PUBLIC_HOST}:8443/health"
RC_BEFORE=$?
set -e
echo "rc_before=$RC_BEFORE"
if [[ $RC_BEFORE -eq 0 ]]; then
  echo "8443 already healthy; restarting agent only"
  sudo systemctl restart codex-bridge-agent.service
  sleep 3
  sudo systemctl is-active codex-bridge-agent.service
  echo "REPAIR_NOT_NEEDED"
  git add "$OUT"
  git commit -m "results: Frida 8443 already healthy" || true
  git push origin development
  exit 0
fi

echo "== inspect Frida and try automatic NAT repair =="
ssh -p "$FRIDA_SSH_PORT" "$FRIDA_HOST" 'bash -s' <<'REMOTE'
set -euo pipefail
FRIDA_IP="$(hostname -I | tr " " "\n" | awk '/^192\.168\./{print; exit}')"
GW="$(ip route | awk '/^default /{print $3; exit}')"
echo "frida_ip=$FRIDA_IP"
echo "gateway=$GW"
echo "-- local HTTPS --"
curl -fsS --connect-timeout 3 https://127.0.0.1/health -k || curl -fsS --connect-timeout 3 http://127.0.0.1:18080/health

echo "-- local firewall summary --"
if command -v nft >/dev/null 2>&1; then sudo nft list ruleset 2>/dev/null | grep -E '8443|443|drop|reject' | tail -n 80 || true; fi
if command -v iptables >/dev/null 2>&1; then sudo iptables -S 2>/dev/null | grep -E '8443|443|DROP|REJECT' || true; fi

echo "-- UPnP discovery / mapping attempt --"
if ! command -v upnpc >/dev/null 2>&1; then
  if command -v apt-get >/dev/null 2>&1; then
    sudo apt-get update -qq >/dev/null 2>&1 || true
    sudo apt-get install -y -qq miniupnpc >/dev/null 2>&1 || true
  fi
fi
if command -v upnpc >/dev/null 2>&1; then
  upnpc -l || true
  # Remove stale mapping if one exists, then add the intended mapping.
  upnpc -d 8443 TCP || true
  upnpc -a "$FRIDA_IP" 443 8443 TCP || true
  echo "-- mapping after attempt --"
  upnpc -l || true
else
  echo "upnpc_unavailable"
fi

echo "-- NAT-PMP attempt if available --"
if command -v natpmpc >/dev/null 2>&1; then
  natpmpc -a 443 8443 tcp 7200 -g "$GW" || true
fi
REMOTE

echo "== retest public 8443 from devel3 =="
sleep 2
set +e
BODY="$(curl -fsS --connect-timeout 8 "https://${PUBLIC_HOST}:8443/health" 2>&1)"
RC_AFTER=$?
set -e
printf '%s\n' "$BODY"
echo "rc_after=$RC_AFTER"

if [[ $RC_AFTER -eq 0 ]]; then
  echo "== restart devel3 agent and verify =="
  sudo systemctl restart codex-bridge-agent.service
  sleep 4
  sudo systemctl is-active codex-bridge-agent.service
  sudo journalctl -u codex-bridge-agent.service --since '-2 minutes' --no-pager | tail -n 80 || true
  echo "FRIDA_8443_REPAIRED"
else
  echo "FRIDA_8443_AUTOREPAIR_FAILED"
  echo "Automatic UPnP/NAT-PMP repair was unavailable or rejected by the router."
  echo "Required router rule: TCP WAN 8443 -> ${PUBLIC_HOST} Frida LAN 192.168.71.248:443"
  echo "Router gateway seen from Frida should be inspected for a disabled/stale port-forward rule."
fi

echo "== save result =="
git add "$OUT"
git commit -m "results: active repair attempt for Frida public 8443" || true
git push origin development

exit "$RC_AFTER"
