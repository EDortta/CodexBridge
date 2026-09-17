#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(git rev-parse --show-toplevel)"
cd "$REPO_ROOT"

STAMP="$(date -u +%Y%m%d-%H%M%SZ)"
RESULT="temp-tools/results/${STAMP}-route-8443-to-t610-via-lan.txt"
mkdir -p temp-tools/results
exec > >(tee "$RESULT") 2>&1

HOST="codexbridge.inovacaosistemas.com.br"
FRIDA_SSH=(ssh -p 2200 -o StrictHostKeyChecking=accept-new esteban@frida.inovacaosistemas.com.br)
# Public :22 currently lands on T610/dom1.
T610_SSH=(ssh -p 22 -o StrictHostKeyChecking=accept-new esteban@frida.inovacaosistemas.com.br)
VHOST="/etc/nginx/sites-enabled/codexbridge-https"

cat <<EOF
== Route public :8443 on Frida to T610 over LAN ==
utc=$(date -u +%FT%TZ)
host=$HOST

This fixes script 50's bad hairpin assumption: Frida must NOT reach T610 by
calling the public hostname, because that path can loop/hairpin through the
router and hit the wrong virtual host. We discover T610's LAN address and use
that as Frida's upstream while preserving TLS SNI/Host=$HOST.
EOF

echo "== identify T610 =="
T610_HOSTNAME="$("${T610_SSH[@]}" hostname)"
echo "t610_hostname=$T610_HOSTNAME"

# Collect ordinary private/LAN IPv4 addresses from T610. Exclude loopback,
# docker/bridge/link-local ranges and keep RFC1918 candidates first.
T610_IPS="$("${T610_SSH[@]}" "ip -4 -o addr show scope global | awk '{print \$4}' | cut -d/ -f1" | tr '\n' ' ')"
echo "t610_ipv4_candidates=$T610_IPS"

if [[ -z "${T610_IPS// }" ]]; then
  echo "ERROR: no T610 IPv4 candidates discovered"
  exit 1
fi

echo "== test Frida -> T610 candidates on HTTPS 443 with correct SNI =="
UPSTREAM_IP=""
for ip in $T610_IPS; do
  case "$ip" in
    127.*|169.254.*|172.17.*|172.18.*|172.19.*|172.20.*|172.21.*|172.22.*|172.23.*|172.24.*|172.25.*|172.26.*|172.27.*|172.28.*|172.29.*|172.30.*|172.31.*) continue ;;
  esac
  echo "candidate=$ip"
  if "${FRIDA_SSH[@]}" "curl -fsS --connect-timeout 5 --max-time 10 --resolve '$HOST:443:$ip' 'https://$HOST/health'" >/tmp/cb51-health.$$ 2>/tmp/cb51-err.$$; then
    cat /tmp/cb51-health.$$
    echo
    UPSTREAM_IP="$ip"
    echo "selected_upstream_ip=$UPSTREAM_IP"
    break
  else
    echo "candidate_failed=$(tr '\n' ' ' </tmp/cb51-err.$$ | sed 's/[[:space:]]\+/ /g')"
  fi
done
rm -f /tmp/cb51-health.$$ /tmp/cb51-err.$$

if [[ -z "$UPSTREAM_IP" ]]; then
  echo "ERROR: Frida cannot reach any discovered T610 LAN address on HTTPS 443 with SNI $HOST"
  echo "No nginx changes were made."
  exit 1
fi

# Verify canonical OAuth metadata directly against the selected T610 address.
echo "== validate canonical T610 OAuth identity over LAN =="
CANON_META="$("${FRIDA_SSH[@]}" "curl -fsS --connect-timeout 5 --max-time 10 --resolve '$HOST:443:$UPSTREAM_IP' 'https://$HOST/.well-known/oauth-authorization-server'")"
python3 - "$CANON_META" "https://$HOST" <<'PY'
import json,sys
obj=json.loads(sys.argv[1]); base=sys.argv[2]
assert obj.get('issuer') == base, obj
assert obj.get('authorization_endpoint') == base + '/oauth/authorize', obj
assert obj.get('token_endpoint') == base + '/oauth/token', obj
assert 'S256' in obj.get('code_challenge_methods_supported', []), obj
print('t610_lan_oauth=ok')
PY

echo "== install Frida compatibility proxy =="
"${FRIDA_SSH[@]}" "VHOST='$VHOST' HOST='$HOST' UPSTREAM_IP='$UPSTREAM_IP' bash -s" <<'REMOTE'
set -euo pipefail
BACKUP="/var/backups/codex-bridge/nginx-8443-to-t610-lan-$(date -u +%Y%m%d-%H%M%SZ)"
sudo mkdir -p "$BACKUP"
sudo cp -a "$VHOST" "$BACKUP/"
echo "backup=$BACKUP"

CERT="/etc/letsencrypt/live/${HOST}/fullchain.pem"
KEY="/etc/letsencrypt/live/${HOST}/privkey.pem"
TMP="$(mktemp)"
cat >"$TMP" <<EOF
server {
    listen 443 ssl http2;
    server_name ${HOST};

    ssl_certificate ${CERT};
    ssl_certificate_key ${KEY};
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_prefer_server_ciphers on;
    client_max_body_size 2m;

    # Compatibility ingress: public :8443 -> Frida:443 -> T610 LAN:443.
    # T610 is canonical. Preserve Host/SNI as the public hostname so OAuth/MCP
    # metadata remains https://${HOST} with no :8443 identity.
    location /agent/ws {
        proxy_pass https://${UPSTREAM_IP};
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
        proxy_connect_timeout 10s;
        proxy_read_timeout 3600s;
        proxy_send_timeout 3600s;
    }

    location / {
        proxy_pass https://${UPSTREAM_IP};
        proxy_http_version 1.1;
        proxy_set_header Host ${HOST};
        proxy_set_header X-Forwarded-Host ${HOST};
        proxy_set_header X-Forwarded-Proto https;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_ssl_server_name on;
        proxy_ssl_name ${HOST};
        proxy_ssl_verify on;
        proxy_ssl_trusted_certificate /etc/ssl/certs/ca-certificates.crt;
        proxy_connect_timeout 10s;
        proxy_read_timeout 120s;
        proxy_send_timeout 120s;
    }
}
EOF

sudo install -m 0644 "$TMP" "$VHOST"
rm -f "$TMP"
sudo nginx -t
sudo systemctl reload nginx
echo "frida_compat_proxy=installed"
REMOTE

# Validate externally from devel3. Public 443 is canonical T610; public 8443
# lands on Frida and must mirror it.
echo "== validate public 443 vs 8443 =="
for p in /health /.well-known/oauth-authorization-server /.well-known/oauth-protected-resource/mcp; do
  echo "-- $p --"
  bare="$(curl -fsS --connect-timeout 8 --max-time 20 "https://${HOST}${p}")"
  compat="$(curl -fsS --connect-timeout 8 --max-time 20 "https://${HOST}:8443${p}")"
  if [[ "$bare" != "$compat" ]]; then
    echo "mismatch_path=$p"
    echo "bare=$bare"
    echo "compat=$compat"
    exit 1
  fi
  echo "mirror_ok=$p"
done

COMPAT_META="$(curl -fsS --connect-timeout 8 --max-time 20 "https://${HOST}:8443/.well-known/oauth-authorization-server")"
python3 - "$COMPAT_META" "https://$HOST" <<'PY'
import json,sys
obj=json.loads(sys.argv[1]); base=sys.argv[2]
assert obj.get('issuer') == base, obj
assert obj.get('authorization_endpoint') == base + '/oauth/authorize', obj
assert obj.get('token_endpoint') == base + '/oauth/token', obj
assert 'S256' in obj.get('code_challenge_methods_supported', []), obj
print('compat_8443_advertises_canonical_443=ok')
PY

# MCP initialize equality check.
echo "== validate MCP initialize =="
PAYLOAD='{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"compat-probe","version":"1"}}}'
BARE_MCP="$(curl -fsS --connect-timeout 8 --max-time 20 -H 'content-type: application/json' -H 'accept: application/json, text/event-stream' -d "$PAYLOAD" "https://${HOST}/mcp")"
COMPAT_MCP="$(curl -fsS --connect-timeout 8 --max-time 20 -H 'content-type: application/json' -H 'accept: application/json, text/event-stream' -d "$PAYLOAD" "https://${HOST}:8443/mcp")"
python3 - "$BARE_MCP" "$COMPAT_MCP" <<'PY'
import json,sys

def parse(s):
    s=s.strip()
    if s.startswith('data:'):
        s='\n'.join(line[5:].strip() for line in s.splitlines() if line.startswith('data:'))
    return json.loads(s)
a=parse(sys.argv[1]); b=parse(sys.argv[2])
sa=a['result']['serverInfo']; sb=b['result']['serverInfo']
assert sa == sb, (sa,sb)
print('mcp_serverInfo=', sa)
print('mcp_443_8443_match=ok')
PY

cat <<EOF
CODEXBRIDGE_8443_COMPAT_TO_T610_READY
upstream_t610_lan_ip=$UPSTREAM_IP
public_443=canonical_T610
public_8443=Frida_proxy_to_T610_LAN_443
OAuth/MCP identity=https://$HOST
EOF

git add "$RESULT"
if ! git diff --cached --quiet; then
  git commit -m "results: route 8443 to T610 over LAN"
  git push origin development
fi
