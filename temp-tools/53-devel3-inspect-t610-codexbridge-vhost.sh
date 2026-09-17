#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(git rev-parse --show-toplevel)"
cd "$REPO_ROOT"

STAMP="$(date -u +%Y%m%d-%H%M%SZ)"
OUT="temp-tools/results/${STAMP}-t610-codexbridge-vhost.txt"
mkdir -p temp-tools/results
exec > >(tee "$OUT") 2>&1

HOST="codexbridge.inovacaosistemas.com.br"
T610=(ssh -p 22 -o StrictHostKeyChecking=accept-new esteban@"$HOST")
FRIDA=(ssh -p 2200 -o StrictHostKeyChecking=accept-new esteban@"$HOST")

cat <<EOF
== Inspect T610 CodexBridge vhost and 400 response ==
utc=$(date -u +%FT%TZ)
host=$HOST

Purpose:
- prove which nginx vhost on T610 answers codexbridge.inovacaosistemas.com.br:443;
- explain the HTTP 400 seen on both public 443 and Frida->T610 LAN access;
- make NO configuration changes.
EOF

echo "== T610 identity and nginx binary =="
"${T610[@]}" 'set -e; echo hostname=$(hostname); echo nginx_bin=$(command -v nginx || true); test -x /usr/sbin/nginx && echo nginx_usr_sbin=yes || true; sudo /usr/sbin/nginx -v 2>&1 || true'

echo "== T610 effective nginx config: relevant directives =="
"${T610[@]}" 'sudo /usr/sbin/nginx -T 2>&1' \
  | grep -nE -C 5 'server_name[[:space:]]+codexbridge\.inovacaosistemas\.com\.br|listen[[:space:]].*443|proxy_protocol|large_client_header_buffers|client_header_buffer_size|return[[:space:]]+400|error_page[[:space:]]+400|proxy_pass|ssl_certificate' \
  | sed -n '1,800p' || true

echo "== T610 enabled-site file names =="
"${T610[@]}" 'sudo find /etc/nginx -maxdepth 3 -type f \( -path "*/sites-enabled/*" -o -path "*/conf.d/*" \) -print 2>/dev/null | sort' || true

echo "== T610 files mentioning CodexBridge =="
"${T610[@]}" 'sudo grep -RIl --exclude="*.pem" --exclude="*.key" "codexbridge.inovacaosistemas.com.br" /etc/nginx 2>/dev/null | sort' || true

echo "== T610 local HTTPS probes with forced name -> 127.0.0.1 =="
"${T610[@]}" "set +e; for path in / /health /.well-known/oauth-authorization-server; do echo --- \\$path; curl -skS --http1.1 --resolve '$HOST:443:127.0.0.1' -D - -o /tmp/cb53-body 'https://$HOST'\"\$path\"; rc=\$?; echo curl_rc=\$rc; head -c 500 /tmp/cb53-body 2>/dev/null; echo; done"

echo "== T610 local HTTP/2 probe =="
"${T610[@]}" "set +e; curl -skS --http2 --resolve '$HOST:443:127.0.0.1' -D - -o /tmp/cb53-h2 'https://$HOST/health'; echo curl_rc=\$?; head -c 500 /tmp/cb53-h2 2>/dev/null; echo"

echo "== certificate/SNI served by T610 local 443 =="
"${T610[@]}" "echo | openssl s_client -connect 127.0.0.1:443 -servername '$HOST' 2>/dev/null | openssl x509 -noout -subject -issuer -ext subjectAltName 2>/dev/null || true"

echo "== T610 recent nginx errors around 400 =="
"${T610[@]}" 'sudo sh -c '\''for f in /var/log/nginx/error.log /var/log/nginx/*error*.log; do [ -r "$f" ] || continue; echo "### $f"; tail -n 120 "$f"; done'\''' | tail -n 500 || true

echo "== Frida -> T610 192.168.71.50 with exact Host/SNI, tiny headers =="
"${FRIDA[@]}" "set +e; curl -skS --http1.1 --resolve '$HOST:443:192.168.71.50' -H 'Host: $HOST' -H 'User-Agent: cb53' -H 'Accept: */*' -D - -o /tmp/cb53-frida 'https://$HOST/health'; echo curl_rc=\$?; head -c 500 /tmp/cb53-frida 2>/dev/null; echo"

echo "== public probe from devel3 with tiny headers =="
curl -skS --http1.1 -H 'User-Agent: cb53' -H 'Accept: */*' -D - -o /tmp/cb53-public "https://$HOST/health" || true
head -c 500 /tmp/cb53-public 2>/dev/null || true
echo

echo "CODEXBRIDGE_T610_VHOST_DIAGNOSTIC_COMPLETE"

git add "$OUT"
if ! git diff --cached --quiet; then
  git commit -m "results: inspect T610 CodexBridge vhost and 400 response"
  git push origin development
fi
