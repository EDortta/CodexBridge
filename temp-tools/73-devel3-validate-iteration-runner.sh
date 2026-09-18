#!/usr/bin/env bash
set -uo pipefail

REPO_ROOT="$(git rev-parse --show-toplevel)"
cd "$REPO_ROOT"

STAMP="$(date -u +%Y%m%d-%H%M%SZ)"
OUT="temp-tools/results/${STAMP}-validate-iteration-runner.txt"
mkdir -p temp-tools/results
exec > >(tee "$OUT") 2>&1
source temp-tools/lib/result-publisher.sh

GLOBAL_TIMEOUT_SECONDS=120
FAIL=0

step() {
  local name="$1"
  shift
  echo
  echo "== $name =="
  timeout 90s "$@"
  local rc=$?
  echo "step_exit_code=$rc"
  [ "$rc" -eq 0 ] || FAIL=1
  return 0
}

main() {
  echo "== Validate CodexBridge Iteration Runner =="
  echo "utc=$(date -u +%FT%TZ)"
  echo "global_timeout_seconds=$GLOBAL_TIMEOUT_SECONDS"

  step "python compile" python3 -m py_compile tools/iteration_runner.py
  step "unit tests" pytest -q tests/unit/test_iteration_runner.py
  step "manifest syntax" python3 -m json.tool .codexbridge/iteration.json
  echo
  echo "== checkout status before runner dry-run =="
  git status --short || true
  step "dry run (paused or busy checkout must not execute)" python3 tools/iteration_runner.py --dry-run

  echo
  echo "== cron readiness =="
  command -v git
  command -v python3
  command -v timeout
  mkdir -p "$HOME/.local/state/codexbridge-iteration-runner"
  test -w "$HOME/.local/state/codexbridge-iteration-runner"
  echo "state_dir=$HOME/.local/state/codexbridge-iteration-runner"

  if [ "$FAIL" -ne 0 ]; then
    echo "ITERATION_RUNNER_VALIDATION_FAILED"
    return 1
  fi

  echo "ITERATION_RUNNER_VALIDATION_READY"
}

main &
PID=$!
if ! timeout "${GLOBAL_TIMEOUT_SECONDS}s" tail --pid="$PID" -f /dev/null; then
  echo "ERROR: validation global timeout after ${GLOBAL_TIMEOUT_SECONDS}s"
  kill "$PID" 2>/dev/null || true
  wait "$PID" 2>/dev/null || true
  exit 124
fi
wait "$PID"
