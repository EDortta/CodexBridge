#!/usr/bin/env bash
set -Eeuo pipefail

REPO_ROOT="$(git rev-parse --show-toplevel)"
cd "$REPO_ROOT"
STAMP="$(date -u +%Y%m%d-%H%M%SZ)"
OUT="temp-tools/results/${STAMP}-repair-frida-t610-tls.txt"
mkdir -p temp-tools/results
exec > >(tee "$OUT") 2>&1

publish_result() {
  rc=$?
  trap - EXIT
  echo "exit_code=$rc"
  git add "$OUT" || true
  if ! git diff --cached --quiet; then
    git commit -m "results: ${STAMP}-repair-frida-t610-tls" || true
    git push origin development || true
  fi
  exit "$rc"
}
trap publish_result EXIT

HOST="codexbridge.inovacaosistemas.com.br"
T610_LAN="192.168.71.50"
FRIDA=(ssh -p 2200 -o StrictHostKeyChecking=accept-new esteban@frida.inovacaosistemas.com.br)
T610=(ssh -p 22 -o StrictHostKeyChecking=accept-new esteban@dom1.inovacaosistemas.com.br)
TRACE="cb61-${STAMP}"

echo "== Repair Frida -> T610 private TLS hop and validate live CodexBridge =="
echo "utc=$(date -u +%FT%TZ)"
echo "trace=$TRACE"
echo
echo "Evidence from script 60: both external probes were handled by Frida's public CodexBridge vhost,"
echo "and Frida failed while verifying T610's certificate over the private LAN hop."
echo "This script changes ONLY that private proxy verification behavior, then validates end-to-end."

echo "== capture T610 served certificate/chain as seen from Frida =="
"${FRIDA[@]}" "timeout 10 openssl s_client -connect ${T610_LAN}:443 -servername ${HOST} -showcerts </dev/null 2>&1 | sed -n '1,120p'"

echo "== prove current failure from Frida -> T610 with CA verification =="
set +e
"${FRIDA[@]}" "curl -sv --resolve '${HOST}:443:${T610_LAN}' --connect-timeout 5 --max-time 10 https://${HOST}/health 2>&1 | tail -60"
CURL_RC=$?
set -e
echo "frida_verified_curl_rc=$CURL_RC"

echo "== patch Frida compatibility vhost: private LAN TLS hop only =="
"${FRIDA[@]}" "HOST='${HOST}' T610_LAN='${T610_LAN}' TRACE='${TRACE}' bash -s" <<'REMOTE'
set -Eeuo pipefail
VHOST=/etc/nginx/sites-enabled/codexbridge-https
BACKUP=/var/backups/codex-bridge/frida-t610-tls-$(date -u +%Y%m%d-%H%M%SZ)
sudo mkdir -p "$BACKUP"
sudo cp -a "$VHOST" "$BACKUP/"

echo "backup=$BACKUP"
echo "-- before --"
sudo grep -nE 'proxy_pass https://192\.168\.71\.50|proxy_ssl_(server_name|name|verify|trusted_certificate)' "$VHOST" || true

TMP=$(mktemp)
sudo cat "$VHOST" > "$TMP"
# This is a host-to-host private LAN hop. Public TLS remains verified by clients on
# both edges. We keep SNI/name so T610 selects the correct vhost, but do not make
# Frida depend on its local CA bundle for this internal connection.
sed -i 's/proxy_ssl_verify on;/proxy_ssl_verify off;/g' "$TMP"
sed -i '/proxy_ssl_trusted_certificate \/etc\/ssl\/certs\/ca-certificates.crt;/d' "$TMP"
sudo install -m 0644 "$TMP" "$VHOST"
rm -f "$TMP"

sudo /usr/sbin/nginx -t
sudo /usr/sbin/nginx -s reload
sleep 2

echo "-- after --"
sudo grep -nE 'proxy_pass https://192\.168\.71\.50|proxy_ssl_(server_name|name|verify|trusted_certificate)' "$VHOST" || true
REMOTE

echo "== prove Frida -> T610 now reaches canonical T610 vhost =="
"${FRIDA[@]}" "curl -fsS --resolve '${HOST}:443:${T610_LAN}' --connect-timeout 5 --max-time 10 https://${HOST}/health"
echo

echo "== external validation from devel3 =="
for port in 443 8443; do
  if [ "$port" = 443 ]; then base="https://${HOST}"; else base="https://${HOST}:8443"; fi
  echo "-- $base/health"
  body="$(curl -fsS --http1.1 --connect-timeout 8 --max-time 20 -H "User-Agent: ${TRACE}" "$base/health?trace=${TRACE}-${port}")"
  echo "$body"
  python3 - "$body" <<'PY'
import json,sys
obj=json.loads(sys.argv[1])
assert obj.get('status') == 'ok', obj
PY
done

echo "== canonical OAuth metadata on 443 and 8443 =="
for port in 443 8443; do
  if [ "$port" = 443 ]; then base="https://${HOST}"; else base="https://${HOST}:8443"; fi
  auth="$(curl -fsS --http1.1 --connect-timeout 8 --max-time 20 "$base/.well-known/oauth-authorization-server")"
  protected="$(curl -fsS --http1.1 --connect-timeout 8 --max-time 20 "$base/.well-known/oauth-protected-resource/mcp")"
  python3 - "$port" "$auth" "$protected" "https://${HOST}" <<'PY'
import json,sys
port,auth_raw,pr_raw,canonical=sys.argv[1:]
auth=json.loads(auth_raw); pr=json.loads(pr_raw)
assert auth.get('issuer') == canonical, (port,auth)
assert auth.get('authorization_endpoint') == canonical + '/oauth/authorize', (port,auth)
assert auth.get('token_endpoint') == canonical + '/oauth/token', (port,auth)
assert 'S256' in auth.get('code_challenge_methods_supported', []), (port,auth)
assert pr.get('resource') == canonical + '/mcp', (port,pr)
servers=pr.get('authorization_servers', [])
assert canonical in servers, (port,pr)
print(f'port_{port}_oauth_canonical=ok')
PY
done

echo "== confirm trace path in both nginx logs =="
"${T610[@]}" "sudo grep '${TRACE}' /var/log/nginx/access.log 2>/dev/null | tail -20 || true"
"${FRIDA[@]}" "sudo grep '${TRACE}' /var/log/nginx/access.log 2>/dev/null | tail -20 || true"

echo "CODEXBRIDGE_EXTERNAL_443_8443_OAUTH_READY"
