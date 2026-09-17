#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(git rev-parse --show-toplevel)"
cd "$REPO_ROOT"

STAMP="$(date -u +%Y%m%d-%H%M%SZ)"
RESULT="temp-tools/results/${STAMP}-route-8443-to-t610.txt"
mkdir -p temp-tools/results
exec > >(tee "$RESULT") 2>&1

HOST="codexbridge.inovacaosistemas.com.br"
FRIDA_SSH=(ssh -p 2200 esteban@frida.inovacaosistemas.com.br)
T610_SSH=(ssh -p 22 -o StrictHostKeyChecking=accept-new esteban@frida.inovacaosistemas.com.br)
VHOST="/etc/nginx/sites-enabled/codexbridge-https"

cat <<EOF
== Route public :8443 through Frida to canonical T610 :443 ==
utc=$(date -u +%FT%TZ)
host=$HOST

Goal:
- keep ChatGPT legacy OAuth/MCP calls to :8443 working;
- make Frida act only as a compatibility reverse proxy for :8443;
- canonical application/OAuth identity remains https://$HOST (bare 443);
- T610 remains the canonical 443 origin for now.
EOF

# 1) Prove that from Frida, bare 443 reaches a healthy canonical CodexBridge.
echo "== preflight: Frida can reach canonical bare 443 =="
"${FRIDA_SSH[@]}" "curl -fsS --connect-timeout 8 --max-time 15 https://$HOST/health"
echo

CANON_META="$("${FRIDA_SSH[@]}" "curl -fsS --connect-timeout 8 --max-time 15 https://$HOST/.well-known/oauth-authorization-server")"
python3 - "$CANON_META" "https://$HOST" <<'PY'
import json,sys
obj=json.loads(sys.argv[1]); base=sys.argv[2]
assert obj.get('issuer') == base, obj
assert obj.get('authorization_endpoint') == base + '/oauth/authorize', obj
assert obj.get('token_endpoint') == base + '/oauth/token', obj
assert 'S256' in obj.get('code_challenge_methods_supported', []), obj
print('canonical_443_oauth=ok')
PY

# 2) Replace Frida's CodexBridge vhost with a minimal compatibility proxy.
#    Important: proxy upstream is the PUBLIC bare-443 hostname. On this network,
#    public 443 is the T610 path while public 8443 maps to Frida:443, so this does
#    not loop as long as that NAT split remains true. We validate immediately.
echo "== install compatibility proxy on Frida =="
"${FRIDA_SSH[@]}" "VHOST='$VHOST' HOST='$HOST' bash -s" <<'REMOTE'
set -euo pipefail
BACKUP="/var/backups/codex-bridge/nginx-8443-to-t610-$(date -u +%Y%m%d-%H%M%SZ)"
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

    # Compatibility ingress only. Public :8443 lands here, then Frida forwards
    # every request to the canonical bare-443 CodexBridge served by T610.
    # The upstream must keep the original Host/SNI so OAuth/MCP identities stay
    # https://${HOST} without :8443.
    location /agent/ws {
        proxy_pass https://${HOST}/agent/ws;
        proxy_http_version 1.1;
        proxy_set_header Upgrade \$http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host ${HOST};
        proxy_set_header X-Forwarded-Host ${HOST};
        proxy_set_header X-Forwarded-Proto https;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_ssl_server_name on;
        proxy_ssl_name ${HOST};
        proxy_connect_timeout 10s;
        proxy_read_timeout 3600s;
        proxy_send_timeout 3600s;
    }

    location / {
        proxy_pass https://${HOST};
        proxy_http_version 1.1;
        proxy_set_header Host ${HOST};
        proxy_set_header X-Forwarded-Host ${HOST};
        proxy_set_header X-Forwarded-Proto https;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_ssl_server_name on;
        proxy_ssl_name ${HOST};
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

# 3) Validate public :8443 now mirrors canonical 443 identity and content.
echo "== validate public :8443 compatibility path =="
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

# MCP initialize must announce same app/version on both paths.
echo "== validate MCP initialize bare 443 vs :8443 =="
PAYLOAD='{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"compat-probe","version":"1"}}}'
BARE_MCP="$(curl -fsS --connect-timeout 8 --max-time 20 -H 'content-type: application/json' -H 'accept: application/json, text/event-stream' -d "$PAYLOAD" "https://${HOST}/mcp")"
COMPAT_MCP="$(curl -fsS --connect-timeout 8 --max-time 20 -H 'content-type: application/json' -H 'accept: application/json, text/event-stream' -d "$PAYLOAD" "https://${HOST}:8443/mcp")"
python3 - "$BARE_MCP" "$COMPAT_MCP" <<'PY'
import json,sys

def parse(s):
    # MCP may be JSON or SSE; extract JSON line if needed.
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
Public behavior now:
  https://$HOST/*        -> canonical T610 443
  https://$HOST:8443/*   -> Frida compatibility proxy -> canonical T610 443
OAuth/MCP metadata on both paths must advertise only https://$HOST (no :8443).
EOF

git add "$RESULT"
if ! git diff --cached --quiet; then
  git commit -m "results: route 8443 compatibility ingress to T610 443"
  git push origin development
fi
