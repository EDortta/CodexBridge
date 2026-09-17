#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(git rev-parse --show-toplevel)"
cd "$REPO_ROOT"
STAMP="$(date -u +%Y%m%d-%H%M%SZ)"
RESULT="temp-tools/results/${STAMP}-diagnose-t610-443-from-frida.txt"
mkdir -p temp-tools/results
exec > >(tee "$RESULT") 2>&1

HOST="codexbridge.inovacaosistemas.com.br"
FRIDA_SSH=(ssh -p 2200 -o StrictHostKeyChecking=accept-new esteban@"$HOST")
T610_SSH=(ssh -p 22 -o StrictHostKeyChecking=accept-new esteban@"$HOST")

cat <<EOF
== Diagnose T610 443 as seen from Frida ==
utc=$(date -u +%FT%TZ)
public_host=$HOST

Topology assumed for this diagnostic only:
- devel3 is remote; its 192.168.71.x similarity is irrelevant.
- Frida and T610 are physically on the same LAN.
- public SSH $HOST:2200 -> Frida.
- public SSH $HOST:22   -> T610.
- public HTTPS $HOST:443 is expected to be the T610 path.
- public HTTPS $HOST:8443 is expected to be the Frida path.

This script makes NO nginx changes.
EOF

echo "== identify both machines =="
"${FRIDA_SSH[@]}" 'printf "frida_hostname="; hostname; printf "frida_ipv4="; hostname -I | tr "\n" " "; echo'
"${T610_SSH[@]}" 'printf "t610_hostname="; hostname; printf "t610_ipv4="; hostname -I | tr "\n" " "; echo'

# Get only RFC1918-ish addresses from T610. Do not infer that devel3 shares them.
T610_IPS="$("${T610_SSH[@]}" 'hostname -I' | tr ' ' '\n' | awk '/^(10\.|192\.168\.|172\.(1[6-9]|2[0-9]|3[01])\.)/ {print}' | tr '\n' ' ')"
echo "t610_private_candidates=$T610_IPS"

if [[ -z "${T610_IPS// }" ]]; then
  echo "ERROR: no private T610 IPv4 candidates discovered"
  exit 1
fi

echo "== inspect what T610 is actually listening on =="
"${T610_SSH[@]}" 'set -o pipefail; sudo ss -ltnp 2>/dev/null | grep -E "(:443|:80|:8080|:8443)[[:space:]]" || true; echo; if command -v nginx >/dev/null 2>&1; then echo nginx_present=yes; sudo nginx -t 2>&1 || true; else echo nginx_present=no; fi'

echo "== inspect T610 nginx references to CodexBridge/443 =="
"${T610_SSH[@]}" 'if command -v nginx >/dev/null 2>&1; then sudo nginx -T 2>&1 | grep -n -B8 -A30 -E "codexbridge\.inovacaosistemas\.com\.br|listen[[:space:]]+443|server_name" | head -n 500 || true; fi'

echo "== compare public 443/8443 fingerprints from devel3 =="
for u in "https://$HOST" "https://$HOST:8443"; do
  echo "-- $u --"
  curl -skS -D - -o /tmp/cb-body.$$ --connect-timeout 8 --max-time 15 "$u/health" | sed -n '1,20p' || true
  echo "body=$(head -c 300 /tmp/cb-body.$$ 2>/dev/null | tr '\n' ' ')"
  rm -f /tmp/cb-body.$$
done

echo "== test Frida -> every T610 private candidate with Host/SNI preserved =="
for ip in $T610_IPS; do
  echo "-- candidate=$ip --"
  "${FRIDA_SSH[@]}" "set +e; tmp=\$(mktemp); hdr=\$(mktemp); curl -skS --resolve '$HOST:443:$ip' -D \"\$hdr\" -o \"\$tmp\" --connect-timeout 5 --max-time 12 'https://$HOST/health'; rc=\$?; echo curl_rc=\$rc; sed -n '1,25p' \"\$hdr\"; printf 'body='; head -c 500 \"\$tmp\" | tr '\\n' ' '; echo; rm -f \"\$hdr\" \"\$tmp\"; exit 0"
done

echo "== test plain TCP reachability from Frida to T610 candidates =="
for ip in $T610_IPS; do
  "${FRIDA_SSH[@]}" "timeout 3 bash -c '</dev/tcp/$ip/443' >/dev/null 2>&1 && echo tcp_${ip}_443=open || echo tcp_${ip}_443=closed"
done

echo "== inspect certificate/vhost selected by T610 LAN candidates from Frida =="
for ip in $T610_IPS; do
  echo "-- candidate=$ip --"
  "${FRIDA_SSH[@]}" "timeout 8 openssl s_client -connect '$ip:443' -servername '$HOST' </dev/null 2>/dev/null | openssl x509 -noout -subject -issuer -ext subjectAltName 2>/dev/null || true"
done

cat <<'EOF'

DIAGNOSTIC_INTERPRETATION:
- HTTP 400 with tcp=open means Frida can physically reach that T610 address; the problem is application/vhost selection, not LAN reachability.
- A certificate for codexbridge.inovacaosistemas.com.br plus HTTP 400 points to nginx/request handling on T610.
- A different certificate or no TLS indicates the candidate is not the canonical T610 HTTPS listener.

CODEXBRIDGE_T610_443_FROM_FRIDA_DIAGNOSTIC_COMPLETE
EOF

git add "$RESULT"
if ! git diff --cached --quiet; then
  git commit -m "results: diagnose T610 443 from Frida"
  git push origin development
fi
