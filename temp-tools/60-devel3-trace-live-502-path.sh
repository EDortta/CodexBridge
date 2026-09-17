#!/usr/bin/env bash
set -uo pipefail

REPO_ROOT="$(git rev-parse --show-toplevel)"
cd "$REPO_ROOT"

STAMP="$(date -u +%Y%m%d-%H%M%SZ)"
OUT="temp-tools/results/${STAMP}-trace-live-502-path.txt"
mkdir -p temp-tools/results

# Always publish the result, success or failure.
if [ -f temp-tools/lib/result-publisher.sh ]; then
  # shellcheck source=/dev/null
  source temp-tools/lib/result-publisher.sh "$OUT"
fi

exec > >(tee "$OUT") 2>&1

HOST="codexbridge.inovacaosistemas.com.br"
TRACE="cb60-${STAMP}"
T610=(ssh -p 22 -o StrictHostKeyChecking=accept-new esteban@dom1.inovacaosistemas.com.br)
FRIDA=(ssh -p 2200 -o StrictHostKeyChecking=accept-new esteban@frida.inovacaosistemas.com.br)

finish_fallback() {
  rc=$?
  if ! declare -F publish_result >/dev/null 2>&1; then
    git add "$OUT" 2>/dev/null || true
    if ! git diff --cached --quiet 2>/dev/null; then
      git commit -m "results: ${STAMP}-trace-live-502-path" 2>/dev/null || true
      git push origin development 2>/dev/null || true
    fi
  fi
  exit "$rc"
}
trap finish_fallback EXIT

cat <<EOF
== Trace live CodexBridge 502 path ==
utc=$(date -u +%FT%TZ)
trace=$TRACE

Known-good fact to preserve:
- T610 local https://$HOST/health already returned status=ok after nginx -s reload.

Goal:
- identify which machine answers external :443 and :8443;
- capture exact nginx upstream error on T610 and Frida;
- make NO configuration changes.
EOF

echo "== baseline process/config state =="
"${T610[@]}" "echo '-- T610 --'; hostname; sudo /usr/sbin/nginx -t; sudo ss -ltnp | grep -E ':(443|18081) ' || true; sudo grep -nE 'server_name|proxy_pass|listen 443' /etc/nginx/sites-available/020-codexbridge.conf 2>/dev/null || true"
"${FRIDA[@]}" "echo '-- Frida --'; hostname; sudo /usr/sbin/nginx -t; sudo ss -ltnp | grep -E ':(443|18080|18082) ' || true; sudo grep -nE 'server_name|proxy_pass|listen 443' /etc/nginx/sites-enabled/codexbridge-https 2>/dev/null || true; sudo grep -nE 'listen|allow|deny|proxy_pass' /etc/nginx/conf.d/codexbridge-t610-internal.conf 2>/dev/null || true"

echo "== prove private hop and T610 local canonical path immediately before external probes =="
"${T610[@]}" "echo '-- private hop --'; curl -sS -D- --connect-timeout 5 --max-time 10 -H 'Host: $HOST' http://192.168.71.248:18082/health; echo; echo '-- local 443 --'; curl -sS -D- --http1.1 --resolve '$HOST:443:127.0.0.1' --connect-timeout 5 --max-time 10 https://$HOST/health"

echo "== snapshot log sizes before probes =="
T610_ACC_BEFORE="$("${T610[@]}" "sudo wc -l < /var/log/nginx/access.log 2>/dev/null || echo 0")"
T610_ERR_BEFORE="$("${T610[@]}" "sudo wc -l < /var/log/nginx/error.log 2>/dev/null || echo 0")"
FRIDA_ACC_BEFORE="$("${FRIDA[@]}" "sudo wc -l < /var/log/nginx/access.log 2>/dev/null || echo 0")"
FRIDA_ERR_BEFORE="$("${FRIDA[@]}" "sudo wc -l < /var/log/nginx/error.log 2>/dev/null || echo 0")"
printf 't610_access_before=%s\nt610_error_before=%s\nfrida_access_before=%s\nfrida_error_before=%s\n' "$T610_ACC_BEFORE" "$T610_ERR_BEFORE" "$FRIDA_ACC_BEFORE" "$FRIDA_ERR_BEFORE"

echo "== external probes from devel3 =="
for url in "https://${HOST}/health?trace=${TRACE}-443" "https://${HOST}:8443/health?trace=${TRACE}-8443"; do
  echo "-- $url"
  curl -sS -D- --http1.1 --connect-timeout 8 --max-time 20 \
    -H "User-Agent: $TRACE" \
    -H "X-CodexBridge-Trace: $TRACE" \
    "$url" || true
  echo
 done

sleep 1

echo "== T610 nginx log delta =="
"${T610[@]}" "A=$T610_ACC_BEFORE E=$T610_ERR_BEFORE bash -s" <<'REMOTE'
set -u
echo '--- access delta ---'
sudo tail -n +$((A+1)) /var/log/nginx/access.log 2>/dev/null | tail -120 || true
echo '--- error delta ---'
sudo tail -n +$((E+1)) /var/log/nginx/error.log 2>/dev/null | tail -120 || true
REMOTE

echo "== Frida nginx log delta =="
"${FRIDA[@]}" "A=$FRIDA_ACC_BEFORE E=$FRIDA_ERR_BEFORE bash -s" <<'REMOTE'
set -u
echo '--- access delta ---'
sudo tail -n +$((A+1)) /var/log/nginx/access.log 2>/dev/null | tail -120 || true
echo '--- error delta ---'
sudo tail -n +$((E+1)) /var/log/nginx/error.log 2>/dev/null | tail -120 || true
REMOTE

echo "== targeted recent errors mentioning CodexBridge upstreams =="
"${T610[@]}" "echo '-- T610 errors --'; sudo tail -200 /var/log/nginx/error.log 2>/dev/null | grep -E '192\\.168\\.71\\.248|18082|upstream|connect\\(\\) failed|SSL|certificate' | tail -80 || true"
"${FRIDA[@]}" "echo '-- Frida errors --'; sudo tail -200 /var/log/nginx/error.log 2>/dev/null | grep -E '192\\.168\\.71\\.50|18082|upstream|connect\\(\\) failed|SSL|certificate' | tail -80 || true"

echo "CODEXBRIDGE_LIVE_502_TRACE_COMPLETE"
