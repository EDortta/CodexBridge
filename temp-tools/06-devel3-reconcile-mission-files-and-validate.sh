#!/usr/bin/env bash
set -u -o pipefail

ROOT="$(git rev-parse --show-toplevel)" || exit 1
cd "$ROOT" || exit 1
mkdir -p temp-tools/results
STAMP="$(date -u +%Y%m%d-%H%M%SZ)"
HOST="$(hostname -s 2>/dev/null || hostname)"
OUT="temp-tools/results/${STAMP}-${HOST}-reconcile-mission-files-and-validate.txt"

exec > >(tee "$OUT") 2>&1

echo "=== CodexBridge Mission reconciliation + validation ==="
echo "timestamp: $(date -Is)"
echo "host: $HOST"
echo "branch: $(git branch --show-current)"
echo "head: $(git rev-parse HEAD)"
echo

echo "--- status before ---"
git status --short

echo

echo "--- remove accidental duplicate migration candidate ---"
if [ -f migrations/0017_durable_missions.old.sql ]; then
  rm -f migrations/0017_durable_missions.old.sql
  echo "removed migrations/0017_durable_missions.old.sql"
else
  echo "no old duplicate migration present"
fi

echo

echo "--- required Mission implementation files ---"
for p in gateway/app/services/mission_types.py migrations/0017_durable_missions.sql contract/1.19.0; do
  if [ -e "$p" ]; then
    echo "PRESENT $p"
  else
    echo "MISSING $p"
  fi
done

echo

echo "--- ensure declared runtime dependency is available ---"
if python3 - <<'PY'
import importlib.util, sys
sys.exit(0 if importlib.util.find_spec('aiosmtplib') else 1)
PY
then
  echo "aiosmtplib already available"
else
  echo "aiosmtplib missing; installing project dependencies from pyproject.toml"
  python3 -m pip install --user -e .
  echo "pip install exit=$?"
fi

run_section() {
  name="$1"; shift
  echo
  echo "=== $name ==="
  "$@"
  rc=$?
  echo "[$name exit=$rc]"
  return 0
}

run_section migration-tests python3 -m pytest -q tests/unit/test_apply_migrations.py tests/unit/test_schema_guard.py
run_section mission-focused python3 -m pytest -q tests/integration/test_missions.py tests/integration/test_start_development_task.py
run_section contract-tests python3 -m pytest -q tests/contract
run_section full-suite python3 -m pytest -q
run_section codemap-refresh governancekit --root . map

echo
echo "--- status after ---"
git status --short

echo
echo "IMPORTANT_FILES_TO_COMMIT_IF_PRESENT:"
for p in gateway/app/services/mission_types.py contract/1.19.0 migrations/0017_durable_missions.sql docs/codemap.md "$OUT"; do
  [ -e "$p" ] && echo "$p"
done

echo
echo "RESULT_FILE=$OUT"
exit 0
