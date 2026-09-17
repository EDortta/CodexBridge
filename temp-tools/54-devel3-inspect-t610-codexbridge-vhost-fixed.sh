#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(git rev-parse --show-toplevel)"
cd "$REPO_ROOT"

STAMP="$(date -u +%Y%m%d-%H%M%SZ)"
OUT="temp-tools/results/${STAMP}-t610-codexbridge-vhost-fixed.txt"
mkdir -p temp-tools/results
exec > >(tee "$OUT") 2>&1

HOST="codexbridge.inovacaosistemas.com.br"
T610=(ssh -p 22 -o StrictHostKeyChecking=accept-new esteban@"$HOST")
FRIDA=(ssh -p 2200 -o StrictHostKeyChecking=accept-new esteban@"$HOST")

cat <<EOF
== Inspect T610 CodexBridge vhost and 400 response (fixed) ==
utc=$(date -u +%FT%TZ)
host=$HOST

Purpose:
- inspect the real T610 nginx vhost for CodexBridge;
- explain the HTTP 400 from local/public/Frida access;
- make NO configuration changes.
EOF

echo "== T610 identity and nginx binary =="
"${T610[@]}" 'set -e; echo hostname=$(hostname); echo nginx_bin=$(command -v nginx || true); test -x /usr/sbin/nginx && echo nginx_usr_sbin=yes || true; sudo /usr/sbin/nginx -v 2>&1 || true'

echo "== T610 effective nginx config: CodexBridge server block context =="
"${T610[@]}" 'sudo /usr/sbin/nginx -T 2>&1' \
  | grep -nE -C 12 'server_name[[:space:]]+codexbridge\.inovacaosistemas\.com\.br|listen[[:space:]].*443|proxy_protocol|large_client_header_buffers|client_header_buffer_size|return[[:space:]]+400|error_page[[:space:]]+400|proxy_pass|ssl_certificate' \
  | sed -n '1,1200p' || true

echo "== T610 sites-enabled entries (including symlinks) =="
"${T610[@]}" 'sudo ls -l /etc/nginx/sites-enabled 2>/dev/null || true; sudo find -L /etc/nginx/sites-enabled -maxdepth 1 -mindepth 1 -print 2>/dev/null | sort || true'

echo "== T610 CodexBridge vhost source =="
"${T610[@]}" 'for f in /etc/nginx/sites-available/020-codexbridge.conf /etc/nginx/sites-enabled/020-codexbridge.conf; do if sudo test -e "$f"; then echo "### $f"; sudo sed -n "1,260p" "$f"; fi; done' || true

echo "== T610 local HTTPS probes with forced SNI/name -> 127.0.0.1 =="
for path in / /health /.well-known/oauth-authorization-server /.well-known/oauth-protected-resource/mcp; do
  echo "--- $path"
  "${T610[@]}" bash -s -- "$HOST" "$path" <<'REMOTE'
set +e
host="$1"
path="$2"
rm -f /tmp/cb54-body /tmp/cb54-head
curl -skS --http1.1 --resolve "${host}:443:127.0.0.1" \
  -H "Host: ${host}" -H 'User-Agent: cb54' -H 'Accept: */*' \
  -D /tmp/cb54-head -o /tmp/cb54-body "https://${host}${path}"
rc=$?
echo "curl_rc=$rc"
sed -n '1,30p' /tmp/cb54-head 2>/dev/null || true
head -c 700 /tmp/cb54-body 2>/dev/null || true
echo
REMOTE
done

echo "== T610 local HTTP/2 /health probe =="
"${T610[@]}" bash -s -- "$HOST" <<'REMOTE'
set +e
host="$1"
rm -f /tmp/cb54-h2-body /tmp/cb54-h2-head
curl -skS --http2 --resolve "${host}:443:127.0.0.1" \
  -H "Host: ${host}" -H 'User-Agent: cb54' -H 'Accept: */*' \
  -D /tmp/cb54-h2-head -o /tmp/cb54-h2-body "https://${host}/health"
echo "curl_rc=$?"
sed -n '1,30p' /tmp/cb54-h2-head 2>/dev/null || true
head -c 700 /tmp/cb54-h2-body 2>/dev/null || true
echo
REMOTE

echo "== certificate/SNI served by T610 local 443 =="
"${T610[@]}" "echo | openssl s_client -connect 127.0.0.1:443 -servername '$HOST' 2>/dev/null | openssl x509 -noout -subject -issuer -ext subjectAltName 2>/dev/null || true"

echo "== T610 recent nginx access/error logs =="
"${T610[@]}" 'sudo sh -c '\''for f in /var/log/nginx/access.log /var/log/nginx/error.log /var/log/nginx/*access*.log /var/log/nginx/*error*.log; do [ -r "$f" ] || continue; echo "### $f"; tail -n 120 "$f"; done'\''' | tail -n 900 || true

echo "== Frida -> T610 192.168.71.50 with exact SNI/Host =="
"${FRIDA[@]}" bash -s -- "$HOST" <<'REMOTE'
set +e
host="$1"
rm -f /tmp/cb54-frida-body /tmp/cb54-frida-head
curl -skS --http1.1 --resolve "${host}:443:192.168.71.50" \
  -H "Host: ${host}" -H 'User-Agent: cb54' -H 'Accept: */*' \
  -D /tmp/cb54-frida-head -o /tmp/cb54-frida-body "https://${host}/health"
echo "curl_rc=$?"
sed -n '1,30p' /tmp/cb54-frida-head 2>/dev/null || true
head -c 700 /tmp/cb54-frida-body 2>/dev/null || true
echo
REMOTE

echo "== public 443 and 8443 /health from devel3 =="
for url in "https://${HOST}/health" "https://${HOST}:8443/health"; do
  echo "--- $url"
  set +e
  curl -skS --http1.1 -H 'User-Agent: cb54' -H 'Accept: */*' -D - -o /tmp/cb54-public "$url"
  echo "curl_rc=$?"
  head -c 700 /tmp/cb54-public 2>/dev/null || true
  echo
  set -e
done

echo "CODEXBRIDGE_T610_VHOST_DIAGNOSTIC_COMPLETE"

git add "$OUT"
if ! git diff --cached --quiet; then
  git commit -m "results: inspect T610 CodexBridge vhost after quoting fix"
  git push origin development
fi
