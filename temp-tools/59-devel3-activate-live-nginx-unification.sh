#!/usr/bin/env bash
set -u

REPO_ROOT="$(git rev-parse --show-toplevel)"
cd "$REPO_ROOT"
STAMP="$(date -u +%Y%m%d-%H%M%SZ)"
OUT="temp-tools/results/${STAMP}-activate-live-nginx-unification.txt"
mkdir -p temp-tools/results
exec > >(tee "$OUT") 2>&1

publish_result() {
  rc=$?
  set +e
  echo "exit_code=$rc"
  git add "$OUT"
  if ! git diff --cached --quiet; then
    git commit -m "results: activate live nginx unification ${STAMP}" >/dev/null 2>&1
    git push origin development >/dev/null 2>&1
  fi
  exit "$rc"
}
trap publish_result EXIT

HOST="codexbridge.inovacaosistemas.com.br"
T610_LAN="192.168.71.50"
FRIDA_LAN="192.168.71.248"
PORT="18082"
T610=(ssh -p 22 -o StrictHostKeyChecking=accept-new esteban@dom1.inovacaosistemas.com.br)
FRIDA=(ssh -p 2200 -o StrictHostKeyChecking=accept-new esteban@frida.inovacaosistemas.com.br)

cat <<EOF
== Activate live nginx unification ==
utc=$(date -u +%FT%TZ)

Reason:
- previous run wrote and validated the new T610 vhost;
- it then aborted because systemctl is unavailable on that environment;
- nginx was therefore never reloaded, leaving the old 127.0.0.1:18081 loop live;
- that loop explains the external "Request Header Or Cookie Too Large" response.
EOF

echo "== confirm private hop remains healthy =="
"${T610[@]}" "curl -fsS --connect-timeout 5 --max-time 10 -H 'Host: ${HOST}' http://${FRIDA_LAN}:${PORT}/health"

echo "== inspect T610 live/file state before reload =="
"${T610[@]}" "echo pid1=\$(ps -p 1 -o comm= 2>/dev/null || true); echo '--- vhost file ---'; sudo sed -n '1,220p' /etc/nginx/sites-available/020-codexbridge.conf; echo '--- master ---'; ps -ef | grep '[n]ginx: master' || true"

echo "== reload T610 nginx without relying on systemd =="
"${T610[@]}" 'sudo /usr/sbin/nginx -t && sudo /usr/sbin/nginx -s reload && sleep 2'

echo "== prove T610 local 443 now uses private Frida hop =="
"${T610[@]}" "curl -fsS --http1.1 --resolve '${HOST}:443:127.0.0.1' --connect-timeout 5 --max-time 10 https://${HOST}/health"

# Now make Frida public 443 (external :8443 NAT target) a compatibility proxy
# to canonical T610:443. Use nginx -s reload there too so service-manager
# differences cannot abort the operation.
echo "== install Frida legacy 8443 compatibility vhost =="
"${FRIDA[@]}" "HOST='${HOST}' T610_LAN='${T610_LAN}' bash -s" <<'REMOTE'
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
sudo install -m 0644 "$TMP" "$VHOST"
rm -f "$TMP"
sudo /usr/sbin/nginx -t
sudo /usr/sbin/nginx -s reload
sleep 2
echo backup="$BACKUP"
REMOTE

echo "== validate from devel3 as external client =="
for url in "https://${HOST}/health" "https://${HOST}:8443/health"; do
  echo "-- $url"
  curl -fsS --http1.1 --connect-timeout 8 --max-time 20 -H 'User-Agent: cb59' -H 'Accept: application/json' "$url"
  echo
done

echo "== validate canonical OAuth metadata on both paths =="
for base in "https://${HOST}" "https://${HOST}:8443"; do
  echo "-- $base/.well-known/oauth-authorization-server"
  curl -fsS --http1.1 --connect-timeout 8 --max-time 20 "$base/.well-known/oauth-authorization-server" | python3 -m json.tool
  echo "-- $base/.well-known/oauth-protected-resource/mcp"
  curl -fsS --http1.1 --connect-timeout 8 --max-time 20 "$base/.well-known/oauth-protected-resource/mcp" | python3 -m json.tool
done

BARE="$(curl -fsS --http1.1 https://${HOST}/.well-known/oauth-authorization-server)"
COMPAT="$(curl -fsS --http1.1 https://${HOST}:8443/.well-known/oauth-authorization-server)"
python3 - "$BARE" "$COMPAT" "https://${HOST}" <<'PY'
import json,sys
base=sys.argv[3]
for label,raw in [('443',sys.argv[1]),('8443',sys.argv[2])]:
    o=json.loads(raw)
    assert o.get('issuer') == base, (label,o)
    assert o.get('authorization_endpoint') == base + '/oauth/authorize', (label,o)
    assert o.get('token_endpoint') == base + '/oauth/token', (label,o)
    assert 'S256' in o.get('code_challenge_methods_supported', []), (label,o)
print('oauth_identity_canonical_on_443_and_8443=ok')
PY

echo CODEXBRIDGE_LIVE_443_8443_UNIFIED_READY
