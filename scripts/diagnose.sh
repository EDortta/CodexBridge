#!/usr/bin/env bash
set -euo pipefail

echo "== health =="
curl -fsS "${1:-http://127.0.0.1:8080}/healthz" || true
echo
echo "== metrics head =="
curl -fsS "${1:-http://127.0.0.1:8080}/metrics" | head -n 20 || true

