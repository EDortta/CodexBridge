#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(git rev-parse --show-toplevel)"
cd "$REPO_ROOT"

STAMP="$(date -u +%Y%m%d-%H%M%SZ)"
OUT="temp-tools/results/${STAMP}-unify-443-8443-internal-hop.txt"
mkdir -p temp-tools/results
exec > >(tee "$OUT") 2>&1

HOST="codexbridge.inovacaosistemas.com.br"
T610_LAN="192.168.71.50"
FRIDA_LAN="192.168.71.248"
FRIDA_INTERNAL_PORT="18082"
T610=(ssh -p 22 -o StrictHostKeyChecking=accept-new esteban@"$HOST")
FRIDA=(ssh -p 2200 -o StrictHostKeyChecking=accept-new esteban@"$HOST")

cat <<EOF
== Unify CodexBridge 443 and legacy 8443 without a proxy loop ==
utc=$(date -u +%FT%TZ)

Target topology:
  public :443  -> T610 nginx -> Frida ${FRIDA_LAN}:${FRIDA_INTERNAL_PORT} -> gateway 127.0.0.1:18080
  public :8443 -> Frida nginx -> T610 ${T610_LAN}:443 -> Frida ${FRIDA_LAN}:${FRIDA_INTERNAL_PORT} -> gateway

Canonical OAuth/MCP identity:
  https://${HOST}

Why this design:
- gateway stays bound to localhost on Frida;
- T610 does not need direct access to Frida:18080;
- Frida gets one LAN-only nginx hop, reachable only from T610;
- :8443 really traverses T610, as requested;
- no public-hostname hairpin and no T610<->Frida loop.
EOF

echo "== preflight identities =="
"${T610[@]}" 'echo t610_hostname=$(hostname); ip -4 -o addr show | awk '\''{print $4}'\'' | tr "\n" " "; echo'
"${FRIDA[@]}" 'echo frida_hostname=$(hostname); ip -4 -o addr show | awk '\''{print $4}'\'' | tr "\n" " "; echo'

# 1) Create a LAN-only ingress on Frida. It is deliberately HTTP because it never
# leaves the local LAN and nginx ACLs restrict it to T610. TLS remains on both
# public edges.
echo "== install Frida LAN-only gateway hop on ${FRIDA_LAN}:${FRIDA_INTERNAL_PORT} =="
"${FRIDA[@]}" "HOST='$HOST' T610_LAN='$T610_LAN' FRIDA_LAN='$FRIDA_LAN' PORT='$FRIDA_INTERNAL_PORT' bash -s" <<'REMOTE'
set -euo pipefail
CONF=/etc/nginx/conf.d/codexbridge-t610-internal.conf
BACKUP=/var/backups/codex-bridge/internal-hop-$(date -u +%Y%m%d-%H%M%SZ)
sudo mkdir -p "$BACKUP"
if [ -f "$CONF" ]; then sudo cp -a "$CONF" "$BACKUP/"; fi

# Refuse to steal an unrelated listener.
if sudo ss -ltnp | grep -q "${FRIDA_LAN}:${PORT}"; then
  if ! sudo grep -q 'CODEXBRIDGE_T610_INTERNAL_HOP' "$CONF" 2>/dev/null; then
    echo "ERROR: ${FRIDA_LAN}:${PORT} is already in use by something else"
    sudo ss -ltnp | grep "${FRIDA_LAN}:${PORT}" || true
    exit 10
  fi
fi

TMP=$(mktemp)
cat >"$TMP" <<EOF
# CODEXBRIDGE_T610_INTERNAL_HOP
server {
    listen ${FRIDA_LAN}:${PORT};
    server_name _;

    allow ${T610_LAN};
    allow 127.0.0.1;
    deny all;

    client_max_body_size 2m;

    location /agent/ws {
        proxy_pass http://127.0.0.1:18080/agent/ws;
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
        proxy_pass http://127.0.0.1:18080;
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
sudo install -m 0644 "$TMP" "$CONF"
rm -f "$TMP"
sudo /usr/sbin/nginx -t
sudo systemctl reload nginx
echo "frida_internal_hop=installed"
echo "backup=$BACKUP"
REMOTE

# 2) Prove the exact private hop before changing either public edge.
echo "== verify T610 -> Frida internal hop =="
T610_HEALTH="$("${T610[@]}" "curl -fsS --connect-timeout 5 --max-time 10 -H 'Host: $HOST' http://${FRIDA_LAN}:${FRIDA_INTERNAL_PORT}/health")"
echo "$T610_HEALTH"
python3 - "$T610_HEALTH" <<'PY'
import json,sys
obj=json.loads(sys.argv[1])
assert isinstance(obj, dict), obj
print('t610_to_frida_internal=ok')
PY

# 3) Make T610 the canonical public 443 edge and point it only at the dedicated
# Frida internal hop. This removes the retired 127.0.0.1:18081 edge proxy from
# the request path.
echo "== install canonical CodexBridge vhost on T610 =="
"${T610[@]}" "HOST='$HOST' FRIDA_LAN='$FRIDA_LAN' PORT='$FRIDA_INTERNAL_PORT' bash -s" <<'REMOTE'
set -euo pipefail
VHOST=/etc/nginx/sites-available/020-codexbridge.conf
ENABLED=/etc/nginx/sites-enabled/020-codexbridge.conf
BACKUP=/var/backups/codex-bridge/t610-vhost-$(date -u +%Y%m%d-%H%M%SZ)
sudo mkdir -p "$BACKUP"
sudo cp -a "$VHOST" "$BACKUP/"

CERT=/etc/letsencrypt/live/${HOST}/fullchain.pem
KEY=/etc/letsencrypt/live/${HOST}/privkey.pem
sudo test -r "$CERT"
sudo test -r "$KEY"

TMP=$(mktemp)
cat >"$TMP" <<EOF
server {
    listen 80;
    listen [::]:80;
    server_name ${HOST};

    location /.well-known/acme-challenge/ {
        root /var/www/html;
    }

    location / {
        return 301 https://\$host\$request_uri;
    }
}

server {
    listen 443 ssl http2;
    listen [::]:443 ssl http2;
    server_name ${HOST};

    ssl_certificate ${CERT};
    ssl_certificate_key ${KEY};
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_prefer_server_ciphers on;

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
sudo install -m 0644 "$TMP" "$VHOST"
rm -f "$TMP"
[ -L "$ENABLED" ] || sudo ln -s "$VHOST" "$ENABLED"
sudo /usr/sbin/nginx -t
sudo systemctl reload nginx
echo "t610_canonical_vhost=installed"
echo "backup=$BACKUP"
REMOTE

# 4) Validate T610 locally before letting legacy :8443 traverse it.
echo "== validate canonical T610 443 locally =="
T610_LOCAL="$("${T610[@]}" "curl -fsS --http1.1 --resolve '$HOST:443:127.0.0.1' --connect-timeout 5 --max-time 10 https://$HOST/health")"
echo "$T610_LOCAL"

# 5) Turn Frida's public CodexBridge 443 vhost (public NAT :8443) into a pure
# compatibility hop to T610. A separate internal listener above prevents a loop.
echo "== make Frida public CodexBridge vhost a compatibility proxy to T610 =="
"${FRIDA[@]}" "HOST='$HOST' T610_LAN='$T610_LAN' bash -s" <<'REMOTE'
set -euo pipefail
VHOST=/etc/nginx/sites-enabled/codexbridge-https
BACKUP=/var/backups/codex-bridge/frida-public-vhost-$(date -u +%Y%m%d-%H%M%SZ)
sudo mkdir -p "$BACKUP"
sudo cp -a "$VHOST" "$BACKUP/"

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
    ssl_prefer_server_ciphers on;

    client_max_body_size 2m;

    # Public :8443 compatibility path. Router/NAT lands here on Frida:443;
    # Frida deliberately sends it through canonical T610:443.
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
sudo install -m 0644 "$TMP" "$VHOST"
rm -f "$TMP"
sudo /usr/sbin/nginx -t
sudo systemctl reload nginx
echo "frida_8443_compat_to_t610=installed"
echo "backup=$BACKUP"
REMOTE

# 6) Public validation from devel3. These requests contain no browser cookies, so
# a remaining 'Request Header Or Cookie Too Large' proves an actual proxy loop.
echo "== validate public 443 and 8443 =="
for url in "https://${HOST}/health" "https://${HOST}:8443/health"; do
  echo "-- $url"
  curl -fsS --http1.1 --connect-timeout 8 --max-time 20 -H 'User-Agent: cb56' -H 'Accept: application/json' "$url"
  echo
done

BARE_META="$(curl -fsS --http1.1 --connect-timeout 8 --max-time 20 "https://${HOST}/.well-known/oauth-authorization-server")"
COMPAT_META="$(curl -fsS --http1.1 --connect-timeout 8 --max-time 20 "https://${HOST}:8443/.well-known/oauth-authorization-server")"
python3 - "$BARE_META" "$COMPAT_META" "https://${HOST}" <<'PY'
import json,sys
bare=json.loads(sys.argv[1]); compat=json.loads(sys.argv[2]); base=sys.argv[3]
for name,obj in [('443',bare),('8443',compat)]:
    assert obj.get('issuer') == base, (name,obj)
    assert obj.get('authorization_endpoint') == base + '/oauth/authorize', (name,obj)
    assert obj.get('token_endpoint') == base + '/oauth/token', (name,obj)
    assert 'S256' in obj.get('code_challenge_methods_supported', []), (name,obj)
print('oauth_metadata_443_8443_canonical=ok')
PY

PROTECTED_BARE="$(curl -fsS --http1.1 --connect-timeout 8 --max-time 20 "https://${HOST}/.well-known/oauth-protected-resource/mcp")"
PROTECTED_COMPAT="$(curl -fsS --http1.1 --connect-timeout 8 --max-time 20 "https://${HOST}:8443/.well-known/oauth-protected-resource/mcp")"
python3 - "$PROTECTED_BARE" "$PROTECTED_COMPAT" "https://${HOST}/mcp" <<'PY'
import json,sys
for label,raw in [('443',sys.argv[1]),('8443',sys.argv[2])]:
    obj=json.loads(raw)
    assert obj.get('resource') == sys.argv[3], (label,obj)
print('protected_resource_443_8443_canonical=ok')
PY

cat <<EOF
CODEXBRIDGE_443_8443_UNIFIED_READY
Final topology:
  public 443  -> T610 -> Frida LAN ${FRIDA_INTERNAL_PORT} -> gateway
  public 8443 -> Frida -> T610 -> Frida LAN ${FRIDA_INTERNAL_PORT} -> gateway
Canonical identity on both paths: https://${HOST}
EOF

git add "$OUT"
if ! git diff --cached --quiet; then
  git commit -m "results: unify CodexBridge 443 and 8443 through T610"
  git push origin development
fi
