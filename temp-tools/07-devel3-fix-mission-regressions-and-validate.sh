#!/usr/bin/env bash
set -u -o pipefail

ROOT="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
cd "$ROOT" || exit 1
mkdir -p temp-tools/results
STAMP="$(date -u +%Y%m%d-%H%M%SZ)"
HOST="$(hostname 2>/dev/null || echo unknown-host)"
OUT="temp-tools/results/${STAMP}-${HOST}-fix-mission-regressions-and-validate.txt"
PROMPT="temp-tools/results/${STAMP}-${HOST}-fix-mission-regressions.prompt.txt"

cat >"$PROMPT" <<'EOF'
You are fixing the remaining regressions from CodexBridge issue #43 on the CURRENT development checkout. Do the fixes, not a plan.

Current validated facts from the previous devel3 run:
- Migration tests are GREEN: 22 passed.
- Mission-focused suite has 6 failures.
- Contract suite has 1 failure.
- Full suite has 17 failures, 1486 passed, 9 skipped.
- `gateway/app/services/mission_types.py` and `contract/1.19.0/` exist locally and are part of the intended #43 implementation; do not delete them.
- `migrations/0017_durable_missions.sql` is the canonical migration. The accidental `.old.sql` duplicate was removed.

Fix these failures while preserving compatibility and existing security invariants:

Mission failures:
- tests/integration/test_missions.py::test_stage_groups_state_into_three_phases[expired-done]
- tests/integration/test_missions.py::test_stage_groups_state_into_three_phases[lost-done]
- tests/integration/test_missions.py::test_timeline_reports_creation_and_state_changes_oldest_first
- tests/integration/test_missions.py::test_timeline_pages_by_cursor
- tests/integration/test_missions.py::test_the_cancel_reason_appears_on_the_timeline
- tests/integration/test_missions.py::test_explain_on_a_blocked_mission_reports_it

Contract failure:
- tests/contract/test_openapi_document.py::test_reported_contract_version_matches_the_document

Other full-suite regressions:
- tests/integration/test_api_conventions.py::test_real_gateway_leaves_mcp_error_shape_untouched
- tests/integration/test_artifacts.py::test_the_default_artifacts_root_follows_the_working_directory
- tests/integration/test_probes.py::test_api_version_is_rate_limited_with_the_contract_shape
- tests/integration/test_probes.py::test_health_and_ready_are_never_rate_limited
- tests/integration/test_probes.py::test_ready_is_cached_so_a_flood_cannot_drain_the_connection_pool
- tests/integration/test_sessions.py::test_resume_marks_the_session_resuming_and_tells_the_executor
- tests/integration/test_sessions.py::test_restart_marks_the_session_restarting_and_tells_the_executor
- tests/integration/test_sessions.py::test_restart_of_a_finished_session_re_queues_it
- tests/integration/test_store_and_mcp.py::test_mcp_cancel_of_a_pending_control_state_writes_cancelled[paused]
- tests/integration/test_store_and_mcp.py::test_startup_recovery_marks_pending_control_states_as_lost[paused]

Important compatibility requirement:
The durable Mission aggregate is new, but legacy Task/Session states such as `expired`, `lost`, `paused`, `resuming`, `restarting`, etc. must keep their existing external semantics where current APIs/tests require them. Do not "solve" regressions by narrowing old state vocabulary or deleting tests. Where Mission has a smaller canonical state machine, use explicit compatibility projection/mapping rather than corrupting Task/Session semantics.

Timeline requirement:
Mission timeline must be append-only, ordered, cursor-page correctly, and include creation/state/cancel/explain events expected by the existing public contract. Do not fall back to raw unredacted audit payloads.

Contract requirement:
The active OpenAPI document and published/pinned contract artifact/version index must agree on 1.19.0 if 1.19.0 remains the intended additive public contract. Fix the source/artifact mismatch using the repository's established publishing mechanism if available; do not handwave the failing test.

Full-suite regressions outside Mission:
Treat them as likely integration regressions introduced by the #43 changes or environment-sensitive assumptions surfaced by them. Fix code only when the regression is real. Do not weaken unrelated behavior. In particular, preserve MCP error shape, probe rate-limit semantics, artifact-root semantics, and Session control-state behavior.

Security invariants remain mandatory:
- no generic shell exposure
- no local path leakage through Mission/MCP/client surfaces
- no credential/provider secret leakage
- Node/Project authorization remains fail-closed
- approval gates remain intact

Execution rules:
1. Inspect git status and the failing code/tests first.
2. Modify the checkout directly.
3. Do not commit, push, reset, checkout, or alter credentials.
4. Do not install or upgrade global dependencies in this run.
5. Do not delete or weaken tests merely to obtain green.
6. Run focused tests as you fix them.
7. Then run:
   python3 -m pytest -q tests/unit/test_apply_migrations.py tests/unit/test_schema_guard.py
   python3 -m pytest -q tests/integration/test_missions.py tests/unit/test_mission_types.py
   python3 -m pytest -q tests/contract
   python3 -m pytest -q tests/integration/test_api_conventions.py tests/integration/test_artifacts.py tests/integration/test_probes.py tests/integration/test_sessions.py tests/integration/test_store_and_mcp.py
   python3 -m pytest -q
8. Refresh docs/codemap.md only after code/tests stabilize.
9. Leave `gateway/app/services/mission_types.py`, `contract/1.19.0/`, and all required #43 implementation files present for the operator to add to git.

At the end print exactly:
MIGRATION_TESTS:
MISSION_TESTS:
CONTRACT_TESTS:
REGRESSION_TESTS:
FULL_SUITE:
UNTRACKED_REQUIRED_FILES:
BLOCKERS:
FILES_CHANGED:
EOF

{
  echo "=== CodexBridge #43 regression repair ==="
  echo "timestamp: $(date -Is)"
  echo "host: $HOST"
  echo "branch: $(git branch --show-current)"
  echo "head-before: $(git rev-parse HEAD)"
  echo
  echo "--- status before ---"
  git status --short
  echo
  echo "--- codex version ---"
  codex --version || true
  echo
  echo "--- Codex repair run ---"
  codex exec --dangerously-bypass-approvals-and-sandbox - <"$PROMPT"
  CODEX_EXIT=$?
  echo "[codex exit=$CODEX_EXIT]"
  echo
  echo "--- validation after Codex ---"
  run_test() {
    local name="$1"; shift
    echo "=== $name ==="
    "$@"
    local rc=$?
    echo "[$name exit=$rc]"
    return 0
  }
  run_test migration-tests python3 -m pytest -q tests/unit/test_apply_migrations.py tests/unit/test_schema_guard.py
  run_test mission-tests python3 -m pytest -q tests/integration/test_missions.py tests/unit/test_mission_types.py
  run_test contract-tests python3 -m pytest -q tests/contract
  run_test regression-tests python3 -m pytest -q tests/integration/test_api_conventions.py tests/integration/test_artifacts.py tests/integration/test_probes.py tests/integration/test_sessions.py tests/integration/test_store_and_mcp.py
  run_test full-suite python3 -m pytest -q
  echo
  echo "--- refresh codemap ---"
  governancekit --root . map
  echo "[codemap exit=$?]"
  echo
  echo "--- required file tracking ---"
  for p in gateway/app/services/mission_types.py contract/1.19.0 migrations/0017_durable_missions.sql; do
    if git ls-files --error-unmatch "$p" >/dev/null 2>&1; then
      echo "TRACKED $p"
    elif [ -e "$p" ]; then
      echo "UNTRACKED $p"
    else
      echo "MISSING $p"
    fi
  done
  echo
  echo "--- status after ---"
  git status --short
} >"$OUT" 2>&1

printf '%s\n' "$OUT"
exit 0
