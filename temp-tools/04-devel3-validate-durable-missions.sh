#!/usr/bin/env bash
set -u -o pipefail

ROOT="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
cd "$ROOT" || exit 1
mkdir -p temp-tools/results
STAMP="$(date -u +%Y%m%d-%H%M%SZ)"
HOST="$(hostname -s 2>/dev/null || hostname)"
OUT="temp-tools/results/${STAMP}-${HOST}-validate-durable-missions.txt"

exec > >(tee "$OUT") 2>&1

printf '=== CodexBridge durable Mission validation ===\n'
printf 'timestamp: %s\n' "$(date -Is)"
printf 'host: %s\n' "$HOST"
printf 'branch: %s\n' "$(git branch --show-current)"
printf 'head: %s\n' "$(git rev-parse HEAD)"
printf '\n--- status before ---\n'
git status --short

run_step() {
  local name="$1"; shift
  printf '\n=== %s ===\n' "$name"
  "$@"
  local rc=$?
  printf '\n[%s exit=%s]\n' "$name" "$rc"
  return "$rc"
}

MIG=0
FOCUSED=0
CONTRACT=0
FULL=0
CODEMAP=0

run_step migration-tests python -m pytest -q tests/unit/test_apply_migrations.py tests/unit/test_schema_guard.py || MIG=$?
run_step mission-focused python -m pytest -q tests/integration/test_missions.py tests/integration/test_start_development_task.py tests/integration/test_smoke.py || FOCUSED=$?
run_step contract-tests python -m pytest -q tests/contract || CONTRACT=$?
run_step full-suite python -m pytest -q || FULL=$?
run_step codemap-refresh governancekit --root . map || CODEMAP=$?

printf '\n--- status after ---\n'
git status --short
printf '\nMIGRATION_TESTS=%s\n' "$MIG"
printf 'MISSION_FOCUSED=%s\n' "$FOCUSED"
printf 'CONTRACT_TESTS=%s\n' "$CONTRACT"
printf 'FULL_SUITE=%s\n' "$FULL"
printf 'CODEMAP_REFRESH=%s\n' "$CODEMAP"
printf 'RESULT_FILE=%s\n' "$OUT"

# Always leave the result artifact available for commit/upload even on failure.
exit 0
