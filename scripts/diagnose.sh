#!/usr/bin/env bash
set -euo pipefail

BASE="${1:-http://127.0.0.1:8080}"

# `/healthz` and `/health` both answer "the process is up" and CANNOT report a
# database outage — by design, so that a dependency blip does not restart a
# healthy process. This script used to probe only `/healthz`, which meant the
# operator's own diagnostic reported healthy during a total database outage.
# `/ready` is the one that can say no.

echo "== live (process up; says nothing about dependencies) =="
curl -fsS "${BASE}/health" || true
echo
echo "== ready (dependencies; 503 names what is down) =="
curl -sS -o /tmp/codexbridge-ready.$$ -w 'HTTP %{http_code}\n' "${BASE}/ready" || true
cat /tmp/codexbridge-ready.$$ 2>/dev/null || true
rm -f /tmp/codexbridge-ready.$$
echo
echo "== version and capabilities =="
curl -fsS "${BASE}/api/version" || true
echo
echo "== healthz (pre-existing infrastructure probe) =="
curl -fsS "${BASE}/healthz" || true
echo
echo "== metrics head =="
curl -fsS "${BASE}/metrics" | head -n 20 || true
