#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="$(git rev-parse --show-toplevel)"
cd "$ROOT"

STAMP="$(date -u +%Y%m%d-%H%M%SZ)"
HOST="$(hostname -s 2>/dev/null || hostname)"
RESULT_DIR="temp-tools/results"
RESULT_FILE="$RESULT_DIR/${STAMP}-${HOST}-finalize-mission-required-files.txt"
mkdir -p "$RESULT_DIR"
exec > >(tee "$RESULT_FILE") 2>&1

echo "=== CodexBridge #43 required-file finalization ==="
echo "timestamp: $(date -Iseconds)"
echo "host: $HOST"
echo "branch: $(git branch --show-current)"
echo "head-before: $(git rev-parse HEAD)"
echo

if [[ "$(git branch --show-current)" != "development" ]]; then
  echo "ERROR: expected development branch"
  exit 1
fi

required=(
  "gateway/app/services/mission_types.py"
  "tests/unit/test_mission_types.py"
  "contract/1.19.0"
)

for path in "${required[@]}"; do
  if [[ ! -e "$path" ]]; then
    echo "ERROR: missing required path: $path"
    exit 1
  fi
  echo "PRESENT $path"
done

echo
echo "--- stage only required #43 files ---"
git add -- \
  gateway/app/services/mission_types.py \
  tests/unit/test_mission_types.py \
  contract/1.19.0

echo
git status --short -- \
  gateway/app/services/mission_types.py \
  tests/unit/test_mission_types.py \
  contract/1.19.0

if git diff --cached --quiet; then
  echo "No staged changes; required files may already be tracked."
else
  echo
echo "--- focused verification ---"
  python3 -m pytest -q tests/unit/test_mission_types.py tests/contract/test_openapi_document.py

  echo
echo "--- commit ---"
  git commit -m "feat(missions): track durable Mission state machine and contract 1.19"
fi

echo
echo "--- push development ---"
git push origin development

echo
echo "--- final state ---"
echo "head-after: $(git rev-parse HEAD)"
git status --short

echo
echo "RESULT_FILE=$RESULT_FILE"
