#!/usr/bin/env bash
# Temporary operator-assisted tool for CodexBridge.
# Safe posture: does not commit, push, reset, clean, checkout, or print secrets.

set -u

ROOT="$(git rev-parse --show-toplevel 2>/dev/null || true)"
if [[ -z "$ROOT" ]]; then
  echo "ERROR: run this script from inside the CodexBridge repository." >&2
  exit 2
fi
cd "$ROOT"

mkdir -p temp-tools/results
STAMP="$(date +%Y%m%d-%H%M%S)"
HOST="$(hostname -s 2>/dev/null || hostname)"
OUT="temp-tools/results/${STAMP}-${HOST}-refresh-codemap-and-test.txt"

# Everything after this point is copied to the dated result file and to screen.
exec > >(tee -a "$OUT") 2>&1

section() {
  printf '\n\n===== %s =====\n' "$1"
}

run() {
  local label="$1"
  shift
  section "$label"
  printf '$'
  printf ' %q' "$@"
  printf '\n'
  "$@"
  local rc=$?
  printf '\n[exit=%s] %s\n' "$rc" "$label"
  return 0
}

section "CodexBridge devel3 collection"
echo "timestamp: $(date --iso-8601=seconds 2>/dev/null || date)"
echo "host: $HOST"
echo "repo: $ROOT"
echo "output: $OUT"

section "Repository state before changes"
git status --short --branch || true
echo "HEAD: $(git rev-parse HEAD 2>/dev/null || echo unknown)"
echo "branch: $(git branch --show-current 2>/dev/null || echo unknown)"
echo "remote names:"
git remote 2>/dev/null || true

auto_version() {
  local cmd="$1"
  shift
  if command -v "$cmd" >/dev/null 2>&1; then
    "$cmd" "$@" 2>&1 | head -20
  else
    echo "$cmd: NOT FOUND"
  fi
}

section "Tool versions"
auto_version python3 --version
auto_version governancekit --version
auto_version codex --version
auto_version claude --version
auto_version gh --version

section "Refresh docs/codemap.md"
if command -v governancekit >/dev/null 2>&1; then
  governancekit --root . map
  GK_RC=$?
  echo "governancekit map exit: $GK_RC"
else
  GK_RC=127
  echo "governancekit is not installed/in PATH; codemap was NOT regenerated."
fi

section "Codemap diff after refresh"
git status --short docs/codemap.md tests/integration/test_smoke.py 2>/dev/null || true
git diff --stat -- docs/codemap.md 2>/dev/null || true
git diff -- docs/codemap.md 2>/dev/null | head -400 || true

# Prefer the repository virtualenv when present, otherwise use python3 -m pytest.
if [[ -x .venv/bin/pytest ]]; then
  PYTEST=(.venv/bin/pytest)
elif command -v pytest >/dev/null 2>&1; then
  PYTEST=(pytest)
else
  PYTEST=(python3 -m pytest)
fi

run "Contract suite" "${PYTEST[@]}" tests/contract -q
run "Focused ChatGPT/MCP execution tests" "${PYTEST[@]}" \
  tests/integration/test_start_development_task.py \
  tests/integration/test_mcp_epics_issues.py \
  tests/integration/test_forge_mcp_tools.py \
  tests/integration/test_forge_wiring.py \
  tests/integration/test_smoke.py -q
run "Full test suite" "${PYTEST[@]}" -q

section "Repository state after tests"
git status --short --branch || true
echo "HEAD: $(git rev-parse HEAD 2>/dev/null || echo unknown)"

section "Result file"
echo "$OUT"
echo
printf 'NEXT ACTION: add docs/codemap.md (if changed) and %s to git, push them, then tell ChatGPT the commit/branch.\n' "$OUT"

# Do not fail the shell just because a diagnostic test failed: the result file
# is the artifact we need in that case.
exit 0
