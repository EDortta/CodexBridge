#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(git rev-parse --show-toplevel)"
cd "$REPO_ROOT"

STAMP="$(date -u +%Y%m%d-%H%M%SZ)"
OUT="temp-tools/results/${STAMP}-repair-private-hop-finish-unification.txt"
mkdir -p temp-tools/results
exec > >(tee "$OUT") 2>&1

HOST="codexbridge.inovacaosistemas.com.br"
T610_LAN="192.168.71.50"
FRIDA_LAN="192.168.71.248"
PORT="18082"
T610=(ssh -p 22 -o StrictHostKeyChecking=accept-new esteban@dom1.inovacaosistemas.com.br)
FRIDA=(ssh -p 2200 -o StrictHostKeyChecking=accept-new esteban@frida.inovacaosistemas.com.br)

cat <<EOF
== Repair Frida private hop and finish CodexBridge 443/8443 unification ==
utc=$(date -u +%FT%TZ)

Known topology:
- devel3 is remote and irrelevant to the Frida/T610 LAN path.
- Frida LAN: ${FRIDA_LAN}
- T610/dom1 LAN: ${T610_LAN}
- Frida public SSH: frida.inovacaosistemas.com.br:2200
- T610 public SSH: dom1.inovacaosistemas.com.br:22
- public 443 -> T610
- public 8443 -> Frida
- both hosts run nginx; esteban has passwordless sudo.

This script focuses on the one failed hop only:
  T610 ${T610_LAN} -> Frida ${FRIDA_LAN}:${PORT}
It will diagnose that hop, add a narrowly-scoped firewall allowance only if needed,
and then finish the nginx unification.
EOF

echo "== verify listener and local Frida hop =="
"${FRIDA[@]}" "sudo ss -ltnp | grep ':${PORT} ' || true; curl -sv --connect-timeout 3 --max-time 5 -H 'Host: ${HOST}' http://${FRIDA_LAN}:${PORT}/health 2>&1 | tail -40"

echo "== verify T610 route/neighbor/connectivity to Frida =="
"${T610[@]}" "ip route get ${FRIDA_LAN} || true; ping -c 2 -W 1 ${FRIDA_LAN} || true; ip neigh show ${FRIDA_LAN} || true; timeout 4 bash -c '</dev/tcp/${FRIDA_LAN}/${PORT}' && echo tcp_${PORT}=open || echo tcp_${PORT}=blocked"

echo "== inspect Frida firewall =="
"${FRIDA[@]}" "echo '--- ufw ---'; sudo ufw status verbose 2>/dev/null || true; echo '--- nft ---'; sudo nft list ruleset 2>/dev/null | sed -n '1,260p' || true; echo '--- iptables ---'; sudo iptables -S 2>/dev/null || true"

# If the listener works locally but T610 cannot establish TCP, permit exactly
# T610 -> Frida:18082. Prefer UFW when active, otherwise use nftables when a
# filter input chain exists, otherwise iptables. The rule is intentionally
# narrow and does not expose the port to the rest of the LAN or Internet.
echo "== repair firewall only if T610 cannot connect =="
if "${T610[@]}" "timeout 3 bash -c '</dev/tcp/${FRIDA_LAN}/${PORT}'" >/dev/null 2>&1; then
  echo "private_hop_already_open=yes"
else
  "${FRIDA[@]}" "T610_LAN='${T610_LAN}' FRIDA_LAN='${FRIDA_LAN}' PORT='${PORT}' bash -s" <<'REMOTE'
set -euo pipefail
if sudo ufw status 2>/dev/null | grep -q '^Status: active'; then
  sudo ufw allow from "$T610_LAN" to "$FRIDA_LAN" port "$PORT" proto tcp comment 'CodexBridge T610 private hop'
  echo firewall_backend=ufw
elif sudo nft list ruleset 2>/dev/null | grep -qE 'hook input[^;]*priority'; then
  # Find the first inet/ip input base chain and insert a precise accept rule.
  FAMILY_TABLE_CHAIN=$(sudo nft -a list ruleset 2>/dev/null | awk '
    /^table (inet|ip) / {fam=$2; tab=$3}
    /^[[:space:]]*chain / {chain=$2}
    /hook input/ {print fam,tab,chain; exit}
  ')
  read -r FAM TAB CHAIN <<<"$FAMILY_TABLE_CHAIN"
  if [ -z "${FAM:-}" ] || [ -z "${TAB:-}" ] || [ -z "${CHAIN:-}" ]; then
    echo "ERROR: nftables active but input base chain was not resolved" >&2
    exit 20
  fi
  sudo nft insert rule "$FAM" "$TAB" "$CHAIN" ip saddr "$T610_LAN" ip daddr "$FRIDA_LAN" tcp dport "$PORT" ct state new,established accept comment 'CodexBridge T610 private hop'
  echo firewall_backend=nftables
  echo firewall_nft_target="$FAM $TAB $CHAIN"
elif command -v iptables >/dev/null 2>&1; then
  if ! sudo iptables -C INPUT -p tcp -s "$T610_LAN" -d "$FRIDA_LAN" --dport "$PORT" -j ACCEPT 2>/dev/null; then
    sudo iptables -I INPUT 1 -p tcp -s "$T610_LAN" -d "$FRIDA_LAN" --dport "$PORT" -j ACCEPT
  fi
  echo firewall_backend=iptables
else
  echo "ERROR: no supported firewall manager found, but TCP is blocked" >&2
  exit 21
fi
REMOTE
fi

echo "== prove T610 -> Frida private hop after repair =="
T610_HEALTH="$("${T610[@]}" "curl -fsS --connect-timeout 5 --max-time 10 -H 'Host: ${HOST}' http://${FRIDA_LAN}:${PORT}/health")"
echo "$T610_HEALTH"
python3 - "$T610_HEALTH" <<'PY'
import json,sys
obj=json.loads(sys.argv[1])
assert isinstance(obj,dict), obj
print('t610_to_frida_private_hop=ok')
PY

# Install canonical public 443 on T610 -> private Frida hop.
echo "== install canonical T610 443 vhost =="
"${T610[@]}" "HOST='${HOST}' FRIDA_LAN='${FRIDA_LAN}' PORT='${PORT}' bash -s" <<'REMOTE'
set -euo pipefail
VHOST=/etc/nginx/sites-available/020-codexbridge.conf
ENABLED=/etc/nginx/sites-enabled/020-codexbridge.conf
BACKUP=/var/backups/codex-bridge/t610-vhost-$(date -u +%Y%m%d-%H%M%SZ)
sudo mkdir -p "$BACKUP"
sudo cp -a "$VHOST" "$BACKUP/"
CERT=/etc/letsencrypt/live/${HOST}/fullchain.pem
KEY=/etc/letsencrypt/live/${HOST}/privkey.pem
sudo test -r "$CERT"; sudo test -r "$KEY"
TMP=$(mktemp)
cat >"$TMP" <<EOF
server {
    listen 80;
    listen [::]:80;
    server_name ${HOST};
    location /.well-known/acme-challenge/ { root /var/www/html; }
    location / { return 301 https://\$host\$request_uri; }
}
server {
    listen 443 ssl http2;
    listen [::]:443 ssl http2;
    server_name ${HOST};
    ssl_certificate ${CERT};
    ssl_certificate_key ${KEY};
    ssl_protocols TLSv1.2 TLSv1.3;
    client_max_body_size 2m;
    location /agent/ws {
        proxy_pass http://${FRIDA_LAN}:${PORT}/agent/ws;
        proxy_http_version 1.1;
        proxy_set_header Upgrade \$http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host ${HOST};
        proxy_set_header X-Forwarded-Host ${HOST};
        proxy_set_header X-Forwarded-Proto https;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_read_timeout 3600s;
        proxy_send_timeout 3600s;
        proxy_buffering off;
    }
    location / {
        proxy_pass http://${FRIDA_LAN}:${PORT};
        proxy_http_version 1.1;
        proxy_set_header Host ${HOST};
        proxy_set_header X-Forwarded-Host ${HOST};
        proxy_set_header X-Forwarded-Proto https;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_read_timeout 120s;
        proxy_send_timeout 120s;
        proxy_buffering off;
    }
}
EOF
sudo install -m 0644 "$TMP" "$VHOST"; rm -f "$TMP"
[ -L "$ENABLED" ] || sudo ln -s "$VHOST" "$ENABLED"
sudo /usr/sbin/nginx -t
sudo systemctl reload nginx
echo t610_443_vhost=installed
echo backup="$BACKUP"
REMOTE

echo "== validate T610 443 locally =="
"${T610[@]}" "curl -fsS --http1.1 --resolve '${HOST}:443:127.0.0.1' --connect-timeout 5 --max-time 10 https://${HOST}/health"

# Frida public 443 is the router target for external :8443. Make it a compatibility
# proxy to T610's canonical LAN 443. The dedicated 18082 hop prevents a loop.
echo "== install Frida 8443 compatibility path -> T610 443 =="
"${FRIDA[@]}" "HOST='${HOST}' T610_LAN='${T610_LAN}' bash -s" <<'REMOTE'
set -euo pipefail
VHOST=/etc/nginx/sites-enabled/codexbridge-https
BACKUP=/var/backups/codex-bridge/frida-public-vhost-$(date -u +%Y%m%d-%H%M%SZ)
sudo mkdir -p "$BACKUP"; sudo cp -a "$VHOST" "$BACKUP/"
CERT=/etc/letsencrypt/live/${HOST}/fullchain.pem
KEY=/etc/letsencrypt/live/${HOST}/privkey.pem
TMP=$(mktemp)
cat >"$TMP" <<EOF
server {
    listen 443 ssl http2;
    server_name ${HOST};
    ssl_certificate ${CERT};
    ssl_certificate_key ${KEY};
    ssl_protocols TLSv1.2 TLSv1.3;
    client_max_body_size 2m;
    location /agent/ws {
        proxy_pass https://${T610_LAN}/agent/ws;
        proxy_http_version 1.1;
        proxy_set_header Upgrade \$http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host ${HOST};
        proxy_set_header X-Forwarded-Host ${HOST};
        proxy_set_header X-Forwarded-Proto https;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_ssl_server_name on;
        proxy_ssl_name ${HOST};
        proxy_ssl_verify on;
        proxy_ssl_trusted_certificate /etc/ssl/certs/ca-certificates.crt;
        proxy_read_timeout 3600s;
        proxy_send_timeout 3600s;
        proxy_buffering off;
    }
    location / {
        proxy_pass https://${T610_LAN};
        proxy_http_version 1.1;
        proxy_set_header Host ${HOST};
        proxy_set_header X-Forwarded-Host ${HOST};
        proxy_set_header X-Forwarded-Proto https;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_ssl_server_name on;
        proxy_ssl_name ${HOST};
        proxy_ssl_verify on;
        proxy_ssl_trusted_certificate /etc/ssl/certs/ca-certificates.crt;
        proxy_read_timeout 120s;
        proxy_send_timeout 120s;
        proxy_buffering off;
    }
}
EOF
sudo install -m 0644 "$TMP" "$VHOST"; rm -f "$TMP"
sudo /usr/sbin/nginx -t
sudo systemctl reload nginx
echo frida_8443_compat=installed
echo backup="$BACKUP"
REMOTE

echo "== public validation =="
for url in "https://${HOST}/health" "https://${HOST}:8443/health"; do
  echo "-- $url"
  curl -fsS --http1.1 --connect-timeout 8 --max-time 20 -H 'User-Agent: cb57' -H 'Accept: application/json' "$url"
  echo
done

BARE_META="$(curl -fsS --http1.1 --connect-timeout 8 --max-time 20 "https://${HOST}/.well-known/oauth-authorization-server")"
COMPAT_META="$(curl -fsS --http1.1 --connect-timeout 8 --max-time 20 "https://${HOST}:8443/.well-known/oauth-authorization-server")"
python3 - "$BARE_META" "$COMPAT_META" "https://${HOST}" <<'PY'
import json,sys
base=sys.argv[3]
for label,raw in [('443',sys.argv[1]),('8443',sys.argv[2])]:
    obj=json.loads(raw)
    assert obj.get('issuer') == base, (label,obj)
    assert obj.get('authorization_endpoint') == base+'/oauth/authorize', (label,obj)
    assert obj.get('token_endpoint') == base+'/oauth/token', (label,obj)
    assert 'S256' in obj.get('code_challenge_methods_supported',[]), (label,obj)
print('oauth_443_8443_canonical=ok')
PY

echo CODEXBRIDGE_443_8443_UNIFIED_READY

git add "$OUT"
if ! git diff --cached --quiet; then
  git commit -m "results: repair private hop and unify CodexBridge 443/8443"
  git push origin development
fi
