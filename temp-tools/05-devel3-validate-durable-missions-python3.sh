#!/usr/bin/env bash
set -u -o pipefail

ROOT="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
cd "$ROOT"
mkdir -p temp-tools/results
STAMP="$(date -u +%Y%m%d-%H%M%SZ)"
HOST="$(hostname 2>/dev/null || printf unknown)"
OUT="temp-tools/results/${STAMP}-${HOST}-validate-durable-missions-python3.txt"

exec > >(tee "$OUT") 2>&1

echo "=== CodexBridge durable Mission validation (python3) ==="
echo "timestamp: $(date --iso-8601=seconds 2>/dev/null || date)"
echo "host: $HOST"
echo "branch: $(git branch --show-current 2>/dev/null || true)"
echo "head: $(git rev-parse HEAD 2>/dev/null || true)"
echo

echo "--- implementation files tracking check ---"
for p in \
  gateway/app/services/mission_types.py \
  contract/1.19.0 \
  migrations/0017_durable_missions.sql; do
  if git ls-files --error-unmatch "$p" >/dev/null 2>&1; then
    echo "TRACKED $p"
  elif [ -e "$p" ]; then
    echo "UNTRACKED $p"
  else
    echo "MISSING $p"
  fi
done

echo
run_step() {
  local name="$1"; shift
  echo "=== $name ==="
  "$@"
  local rc=$?
  echo
  echo "[$name exit=$rc]"
  echo
  return $rc
}

MIG=0; MISS=0; CONTRACT=0; FULL=0; MAP=0
run_step "migration-tests" python3 -m pytest -q tests/unit/test_apply_migrations.py tests/unit/test_schema_guard.py || MIG=$?
run_step "mission-focused" python3 -m pytest -q tests/integration/test_missions.py tests/integration/test_start_development_task.py tests/integration/test_smoke.py || MISS=$?
run_step "contract-tests" python3 -m pytest -q tests/contract || CONTRACT=$?
run_step "full-suite" python3 -m pytest -q || FULL=$?
run_step "codemap-refresh" governancekit --root . map || MAP=$?

echo "--- status after ---"
git status --short

echo
printf 'MIGRATION_TESTS=%s\n' "$MIG"
printf 'MISSION_FOCUSED=%s\n' "$MISS"
printf 'CONTRACT_TESTS=%s\n' "$CONTRACT"
printf 'FULL_SUITE=%s\n' "$FULL"
printf 'CODEMAP_REFRESH=%s\n' "$MAP"
printf 'RESULT_FILE=%s\n' "$OUT"

# Always return success so the result file survives and can be committed/uploaded.
exit 0
