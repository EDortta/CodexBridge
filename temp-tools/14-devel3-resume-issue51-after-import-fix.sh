#!/usr/bin/env bash
set -euo pipefail

ROOT="$(git rev-parse --show-toplevel)"
cd "$ROOT"

if [[ "$(git branch --show-current)" != "development" ]]; then
  echo "ERROR: run this from branch development" >&2
  exit 2
fi

mkdir -p temp-tools/results
STAMP="$(date -u +%Y%m%d-%H%M%SZ)"
RESULT="temp-tools/results/${STAMP}-devel3-issue51-resume.txt"
exec > >(tee "$RESULT") 2>&1

echo "== issue #51 resume after focused-test import failure =="
echo "head_before=$(git rev-parse HEAD)"
echo "status_before:"
git status --short

python3 - <<'PY'
from pathlib import Path

p = Path("tests/unit/test_mission_completion.py")
s = p.read_text()
needle = "    completion_policy_from_project_config,\n"
if needle not in s:
    anchor = "    build_completion_evidence,\n"
    if anchor not in s:
        raise SystemExit("test_mission_completion.py: import anchor not found")
    s = s.replace(anchor, anchor + needle, 1)
    p.write_text(s)
    print("fixed: added completion_policy_from_project_config import")
else:
    print("ok: completion_policy_from_project_config already imported")
PY

echo "== focused tests =="
pytest -q tests/unit/test_mission_completion.py tests/integration/test_issue_resolution.py

echo "== refresh codemap =="
governancekit --root . map

echo "== contract/docs tests =="
pytest -q tests/contract/test_docs_match_the_runtime.py tests/contract/test_openapi_document.py

echo "== full suite =="
pytest -q

echo "== stage only issue #51 files =="
git add \
  gateway/app/services/mission_completion.py \
  gateway/app/services/store.py \
  gateway/app/api/routes/missions.py \
  tests/unit/test_mission_completion.py \
  tests/integration/test_issue_resolution.py \
  docs/codemap.md \
  "$RESULT"

git diff --cached --check

if git diff --cached --quiet; then
  echo "ERROR: no #51 changes staged" >&2
  exit 3
fi

git commit -m "feat(missions): enforce completion evidence gate for #51"
git push origin development

echo "head_after=$(git rev-parse HEAD)"
echo "RESULT=$RESULT"
echo "ISSUE51=READY_FOR_REVIEW"
