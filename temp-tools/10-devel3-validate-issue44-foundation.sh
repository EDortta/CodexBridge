#!/usr/bin/env bash
set -u

ROOT="$(git rev-parse --show-toplevel 2>/dev/null || true)"
if [[ -z "$ROOT" ]]; then
  echo "ERROR: run inside CodexBridge repository" >&2
  exit 2
fi
cd "$ROOT"

STAMP="$(date -u +%Y%m%d-%H%M%SZ)"
OUT="temp-tools/results/${STAMP}-devel3-issue44-foundation.txt"
mkdir -p temp-tools/results

exec > >(tee "$OUT") 2>&1

echo "ISSUE: #44 issue-to-Mission workflow foundation"
echo "TIMESTAMP_UTC: $STAMP"
echo "HOST: $(hostname)"
echo "BRANCH: $(git branch --show-current)"
echo "HEAD: $(git rev-parse HEAD)"
echo

echo "== WORKTREE =="
git status --short

echo

echo "== REQUIRED FILES =="
for f in migrations/0017_durable_missions.sql migrations/0018_mission_issue_snapshots.sql gateway/app/models/entities.py; do
  if [[ -f "$f" ]]; then echo "OK $f"; else echo "MISSING $f"; fi
done

echo

echo "== MIGRATION 0018 CONTENT =="
sed -n '1,240p' migrations/0018_mission_issue_snapshots.sql 2>/dev/null || true

echo

echo "== MODEL IMPORT SMOKE =="
python3 - <<'PY'
try:
    import gateway.app.models.entities as entities
    print("MODEL_IMPORT: OK")
    print("MissionModel:", hasattr(entities, "MissionModel"))
    print("IssueModel:", hasattr(entities, "IssueModel"))
    print("MissionIssueSnapshotModel:", hasattr(entities, "MissionIssueSnapshotModel"))
except Exception as exc:
    print("MODEL_IMPORT: FAIL", type(exc).__name__, str(exc))
PY
MODEL_RC=${PIPESTATUS[0]:-0}

echo

echo "== MIGRATION TESTS =="
python3 -m pytest -q tests/test_migrations.py tests/integration/test_migrations.py 2>&1
MIG_RC=$?

echo

echo "== MISSION FOCUSED TESTS =="
python3 -m pytest -q tests/unit/test_mission_types.py tests/integration/test_missions.py 2>&1
MISSION_RC=$?

echo

echo "== CONTRACT / GOVERNANCE FRESHNESS =="
python3 -m pytest -q tests/test_docs_and_governance.py 2>&1
DOC_RC=$?

echo

echo "RESULT_CODES: model=$MODEL_RC migrations=$MIG_RC missions=$MISSION_RC docs=$DOC_RC"
echo "RESULT_FILE: $OUT"

# This runner is diagnostic only. Never mutate source, install dependencies,
# reset branches, commit, push, or bypass GovernanceKit.
exit 0
