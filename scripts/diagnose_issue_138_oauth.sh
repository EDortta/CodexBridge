#!/usr/bin/env bash
# Read-only OAuth transport latency probe. Never handles credentials or tokens.
set -euo pipefail
BASE_URL="${1:-https://codexbridge.inovacaosistemas.com.br}"
BASE_URL="${BASE_URL%/}"
for endpoint in /health /.well-known/oauth-authorization-server /.well-known/oauth-protected-resource/mcp; do
  printf '%s ' "$endpoint"
  curl --silent --show-error --output /dev/null --max-time 20 \
    --write-out 'http=%{http_code} dns=%{time_namelookup}s tcp=%{time_connect}s tls=%{time_appconnect}s ttfb=%{time_starttransfer}s total=%{time_total}s\n' \
    "$BASE_URL$endpoint"
done
echo 'Compare DNS/TCP/TLS/TTFB/total. Credential verification and database timings are available as oauth_authorize_timing in sanitized Gateway logs.'
