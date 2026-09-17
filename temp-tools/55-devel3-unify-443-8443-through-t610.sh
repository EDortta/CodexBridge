#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(git rev-parse --show-toplevel)"
cd "$REPO_ROOT"

STAMP="$(date -u +%Y%m%d-%H%M%SZ)"
OUT="temp-tools/results/${STAMP}-unify-443-8443-through-t610.txt"
mkdir -p temp-tools/results
exec > >(tee "$OUT") 2>&1

HOST="codexbridge.inovacaosistemas.com.br"
T610_LAN="192.168.71.50"
FRIDA_LAN="192.168.71.248"
T610=(ssh -p 22 -o StrictHostKeyChecking=accept-new esteban@"$HOST")
FRIDA=(ssh -p 2200 -o StrictHostKeyChecking=accept-new esteban@"$HOST")

cat <<EOF
== Unify CodexBridge public 443 and 8443 through T610 ==
utc=$(date -u +%FT%TZ)

Target topology:
  public :443  -> T610 nginx -> Frida gateway :18080
  public :8443 -> Frida nginx -> T610 LAN :443 -> Frida gateway :18080

Canonical OAuth/MCP identity remains:
  https://$HOST

This deliberately avoids any public-hostname hairpin between Frida and T610.
EOF

# Preconditions: prove the actual app is reachable directly on Frida from T610.
echo "== preflight: T610 -> Frida gateway 18080 =="
"${T610[@]}" "curl -fsS --connect-timeout 5 --max-time 10 http://${FRIDA_LAN}:18080/health"
echo

# Prove T610 LAN 443 is reachable from Frida before changing Frida.
echo "== preflight: Frida -> T610 LAN 443 TCP =="
"${FRIDA[@]}" "timeout 5 bash -c '</dev/tcp/${T610_LAN}/443' && echo t610_443_tcp=ok"

# Replace only the CodexBridge vhost on T610 with a direct LAN proxy to the
# actual gateway on Frida. This removes any accidental public-hostname recursion.
echo "== install clean CodexBridge vhost on T610 =="
"${T610[@]}" "HOST='$HOST' FRIDA_LAN='$FRIDA_LAN' bash -s" <<'REMOTE_T610'
set -euo pipefail
VHOST=/etc/nginx/sites-available/020-codexbridge.conf
STAMP=$(date -u +%Y%m%d-%H%M%SZ)
BACKUP=/var/backups/codex-bridge/t610-vhost-$STAMP
sudo mkdir -p "$BACKUP"
sudo cp -a "$VHOST" "$BACKUP/020-codexbridge.conf"
echo "t610_backup=$BACKUP/020-codexbridge.conf"

CERT="/etc/letsencrypt/live/${HOST}/fullchain.pem"
KEY="/etc/letsencrypt/live/${HOST}/privkey.pem"
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
        return 308 https://\$host\$request_uri;
    }
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
        proxy_pass http://${FRIDA_LAN}:18080/agent/ws;
        proxy_http_version 1.1;
        proxy_set_header Upgrade \$http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host ${HOST};
        proxy_set_header X-Forwarded-Host ${HOST};
        proxy_set_header X-Forwarded-Proto https;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_read_timeout 3600s;
        proxy_send_timeout 3600s;
    }

    location / {
        proxy_pass http://${FRIDA_LAN}:18080;
        proxy_http_version 1.1;
        proxy_set_header Host ${HOST};
        proxy_set_header X-Forwarded-Host ${HOST};
        proxy_set_header X-Forwarded-Proto https;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_read_timeout 120s;
        proxy_send_timeout 120s;
    }
}
EOF
sudo install -m 0644 "$TMP" "$VHOST"
rm -f "$TMP"
sudo ln -sfn "$VHOST" /etc/nginx/sites-enabled/020-codexbridge.conf
sudo /usr/sbin/nginx -t
sudo systemctl reload nginx

echo "t610_vhost=installed"
REMOTE_T610

# Validate T610 directly, before touching Frida's compatibility ingress.
echo "== validate T610 local/LAN path =="
"${T610[@]}" "curl -fsS --resolve '$HOST:443:127.0.0.1' https://$HOST/health"
echo
"${FRIDA[@]}" "curl -fsS --resolve '$HOST:443:${T610_LAN}' https://$HOST/health"
echo

# Now make Frida's public 8443 ingress a compatibility proxy to T610 LAN 443.
echo "== install Frida compatibility vhost -> T610 LAN 443 =="
"${FRIDA[@]}" "HOST='$HOST' T610_LAN='$T610_LAN' bash -s" <<'REMOTE_FRIDA'
set -euo pipefail
VHOST=/etc/nginx/sites-enabled/codexbridge-https
STAMP=$(date -u +%Y%m%d-%H%M%SZ)
BACKUP=/var/backups/codex-bridge/frida-vhost-$STAMP
sudo mkdir -p "$BACKUP"
sudo cp -a "$VHOST" "$BACKUP/codexbridge-https"
echo "frida_backup=$BACKUP/codexbridge-https"

CERT="/etc/letsencrypt/live/${HOST}/fullchain.pem"
KEY="/etc/letsencrypt/live/${HOST}/privkey.pem"
TMP=$(mktemp)
cat >"$TMP" <<EOF
server {
    listen 443 ssl http2;
    server_name ${HOST};

    ssl_certificate ${CERT};
    ssl_certificate_key ${KEY};
    ssl_protocols TLSv1.2 TLSv1.3;

    client_max_body_size 2m;

    # Frida serves only the public :8443 compatibility ingress. Every request
    # is handed to T610 over the physical LAN, never through the public DNS name.
    location / {
        proxy_pass https://${T610_LAN};
        proxy_http_version 1.1;
        proxy_set_header Host ${HOST};
        proxy_set_header X-Forwarded-Host ${HOST};
        proxy_set_header X-Forwarded-Proto https;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_ssl_server_name on;
        proxy_ssl_name ${HOST};
        proxy_read_timeout 3600s;
        proxy_send_timeout 3600s;
    }
}
EOF
sudo install -m 0644 "$TMP" "$VHOST"
rm -f "$TMP"
sudo /usr/sbin/nginx -t
sudo systemctl reload nginx

echo "frida_compat_vhost=installed"
REMOTE_FRIDA

# Public validation. No cookies, no inherited headers.
echo "== validate public 443 and 8443 =="
for base in "https://${HOST}" "https://${HOST}:8443"; do
  echo "-- $base --"
  curl -fsS --connect-timeout 8 --max-time 20 "$base/health"
  echo
  curl -fsS --connect-timeout 8 --max-time 20 "$base/.well-known/oauth-authorization-server"
  echo
  curl -fsS --connect-timeout 8 --max-time 20 "$base/.well-known/oauth-protected-resource/mcp"
  echo
done

# Canonical identity must never regress to :8443.
python3 - "$HOST" <<'PY'
import json, subprocess, sys
host=sys.argv[1]
for base in (f"https://{host}", f"https://{host}:8443"):
    raw=subprocess.check_output(["curl","-fsS",base+"/.well-known/oauth-authorization-server"], text=True)
    obj=json.loads(raw)
    canon=f"https://{host}"
    assert obj.get("issuer")==canon, (base,obj)
    assert obj.get("authorization_endpoint")==canon+"/oauth/authorize", (base,obj)
    assert obj.get("token_endpoint")==canon+"/oauth/token", (base,obj)
    assert "S256" in obj.get("code_challenge_methods_supported",[]), (base,obj)
print("oauth_identity_443_8443=canonical")
PY

cat <<EOF
CODEXBRIDGE_443_8443_UNIFIED_THROUGH_T610_READY
EOF

git add "$OUT"
if ! git diff --cached --quiet; then
  git commit -m "results: unify CodexBridge 443 and 8443 through T610"
  git push origin development
fi
