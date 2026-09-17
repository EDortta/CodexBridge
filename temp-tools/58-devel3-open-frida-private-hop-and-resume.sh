#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(git rev-parse --show-toplevel)"
cd "$REPO_ROOT"
STAMP="$(date -u +%Y%m%d-%H%M%SZ)"
OUT="temp-tools/results/${STAMP}-open-frida-private-hop-and-resume.txt"
mkdir -p temp-tools/results
exec > >(tee "$OUT") 2>&1
source temp-tools/lib/result-publisher.sh

T610_LAN="192.168.71.50"
FRIDA_LAN="192.168.71.248"
PORT="18082"
HOST="codexbridge.inovacaosistemas.com.br"
T610=(ssh -p 22 -o StrictHostKeyChecking=accept-new esteban@dom1.inovacaosistemas.com.br)
FRIDA=(ssh -p 2200 -o StrictHostKeyChecking=accept-new esteban@frida.inovacaosistemas.com.br)

echo "== Repair Frida firewall for CodexBridge private hop =="
echo "utc=$(date -u +%FT%TZ)"
echo "T610=${T610_LAN} -> Frida=${FRIDA_LAN}:${PORT}/tcp"
echo

echo "== confirm listener =="
"${FRIDA[@]}" "sudo ss -ltnp | grep '${FRIDA_LAN}:${PORT}'"

echo "== current T610 connectivity =="
if "${T610[@]}" "timeout 3 bash -c '</dev/tcp/${FRIDA_LAN}/${PORT}'" >/dev/null 2>&1; then
  echo "private_hop_already_open=yes"
else
  echo "private_hop_already_open=no"

  echo "== install narrowly-scoped firewall allowance on Frida =="
  "${FRIDA[@]}" "T610_LAN='${T610_LAN}' FRIDA_LAN='${FRIDA_LAN}' PORT='${PORT}' bash -s" <<'REMOTE'
set -euo pipefail
export PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin

CSF=""
for p in /usr/sbin/csf /usr/local/csf/bin/csf; do
  if [ -x "$p" ]; then CSF="$p"; break; fi
done

if [ -n "$CSF" ] && [ -f /etc/csf/csf.allow ]; then
  RULE="tcp|in|d=${PORT}|s=${T610_LAN}"
  if ! sudo grep -Fqx "$RULE # CodexBridge T610 private hop" /etc/csf/csf.allow 2>/dev/null; then
    echo "$RULE # CodexBridge T610 private hop" | sudo tee -a /etc/csf/csf.allow >/dev/null
  fi
  sudo "$CSF" -r >/dev/null
  echo "firewall_backend=csf"
  echo "firewall_persistent=yes"
else
  IPT=""
  for p in /usr/sbin/iptables /sbin/iptables; do
    if [ -x "$p" ]; then IPT="$p"; break; fi
  done
  if [ -n "$IPT" ]; then
    if ! sudo "$IPT" -C INPUT -p tcp -s "$T610_LAN" -d "$FRIDA_LAN" --dport "$PORT" -m conntrack --ctstate NEW -j ACCEPT 2>/dev/null; then
      sudo "$IPT" -I INPUT 1 -p tcp -s "$T610_LAN" -d "$FRIDA_LAN" --dport "$PORT" -m conntrack --ctstate NEW -j ACCEPT
    fi
    echo "firewall_backend=iptables"

    if command -v netfilter-persistent >/dev/null 2>&1; then
      sudo netfilter-persistent save >/dev/null 2>&1 || true
      echo "firewall_persistent=netfilter-persistent"
    elif [ -d /etc/iptables ]; then
      sudo mkdir -p /etc/iptables
      sudo sh -c 'iptables-save > /etc/iptables/rules.v4'
      echo "firewall_persistent=/etc/iptables/rules.v4"
    else
      echo "firewall_persistent=unknown"
    fi
  else
    NFT=""
    for p in /usr/sbin/nft /sbin/nft; do
      if [ -x "$p" ]; then NFT="$p"; break; fi
    done
    if [ -n "$NFT" ]; then
      if ! sudo "$NFT" list chain ip filter INPUT 2>/dev/null | grep -Fq "ip saddr $T610_LAN ip daddr $FRIDA_LAN tcp dport $PORT"; then
        sudo "$NFT" insert rule ip filter INPUT ip saddr "$T610_LAN" ip daddr "$FRIDA_LAN" tcp dport "$PORT" ct state new accept comment "CodexBridge T610 private hop"
      fi
      echo "firewall_backend=nftables"
      echo "firewall_persistent=runtime_only"
    else
      echo "ERROR: neither CSF, iptables nor nft binaries found in system paths" >&2
      exit 31
    fi
  fi
fi

sudo iptables -S INPUT 2>/dev/null | grep -E "${T610_LAN//./\\.}.*${PORT}|${PORT}.*${T610_LAN//./\\.}" || true
REMOTE
fi

echo "== prove T610 -> Frida ${PORT} =="
"${T610[@]}" "timeout 4 bash -c '</dev/tcp/${FRIDA_LAN}/${PORT}'"
echo "tcp_${PORT}=open"

HEALTH="$("${T610[@]}" "curl -fsS --connect-timeout 5 --max-time 10 -H 'Host: ${HOST}' http://${FRIDA_LAN}:${PORT}/health")"
echo "$HEALTH"
python3 - "$HEALTH" <<'PY'
import json,sys
obj=json.loads(sys.argv[1])
assert isinstance(obj,dict), obj
print('private_hop_health=ok')
PY

echo "== resume unification using script 57 =="
# Now that the only failed prerequisite is fixed, reuse the already-reviewed
# unification steps. Its output is also captured inside this script's result file.
bash temp-tools/57-devel3-repair-frida-private-hop-and-finish-unification.sh

echo "CODEXBRIDGE_PRIVATE_HOP_REPAIRED_AND_UNIFICATION_RESUMED"
