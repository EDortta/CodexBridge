#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="$(git rev-parse --show-toplevel)"
cd "$ROOT"

STAMP="$(date +%Y%m%d-%H%M%S)"
HOST="$(hostname -s 2>/dev/null || hostname)"
RESULT_DIR="$ROOT/temp-tools/results"
RESULT="$RESULT_DIR/${STAMP}-${HOST}-mission-aggregate.txt"
PROMPT_FILE="$RESULT_DIR/${STAMP}-${HOST}-mission-aggregate.prompt.txt"
mkdir -p "$RESULT_DIR"

exec > >(tee -a "$RESULT") 2>&1

printf '=== CodexBridge Mission aggregate implementation run ===\n'
printf 'timestamp: %s\n' "$(date --iso-8601=seconds 2>/dev/null || date)"
printf 'host: %s\n' "$HOST"
printf 'repo: %s\n' "$ROOT"
printf 'branch: %s\n' "$(git branch --show-current)"
printf 'head-before: %s\n' "$(git rev-parse HEAD)"
printf '\n'

if [[ "$(git branch --show-current)" != "development" ]]; then
  echo "ERROR: expected development branch. Refusing to edit another branch."
  exit 2
fi

if ! git diff --quiet || ! git diff --cached --quiet; then
  echo "ERROR: tracked working tree is not clean. Commit/stash tracked changes first."
  git status --short
  exit 3
fi

cat > "$PROMPT_FILE" <<'PROMPT'
You are implementing CodexBridge issue #43, the durable Mission aggregate, on the current development checkout.

Do the implementation, not another plan. Inspect the repository and its governance/required-reading files first. Preserve current security invariants and compatibility unless the issue explicitly requires a versioned contract change.

Goal:
Mission must become a durable operator-level entity DISTINCT from Task/Session. The current gateway/app/api/routes/missions.py explicitly says a mission is a TaskModel; that is the gap to remove.

Required behavior:
1. Persist a Mission entity independently of TaskModel. A Mission represents operator intent and survives gateway/executor restart.
2. A Mission can own multiple execution attempts/tasks/sessions without changing its operator-visible identity.
3. Persist at least: objective, project, source issue/ref when present, requested execution policy/mode, selected node/executor/engine where applicable, current state, timestamps, final outcome, and revision/concurrency data needed by existing API conventions.
4. Define Mission states and legal transitions centrally. Cover at least draft/planning/queued/scheduled/waiting-executor/running/testing/reviewing/waiting-human/blocked/paused/completed/failed/cancelled, or a justified canonical equivalent. Do not scatter transition rules across routes.
5. Record append-only Mission timeline events for material transitions and attempt creation/completion.
6. Retry/replan creates a new attempt/task associated with the same Mission; previous attempts remain inspectable/auditable.
7. Existing POST/GET/list/timeline/cancel/delivery Mission HTTP behavior must be migrated to the real aggregate, not silently removed. Maintain authorization, pagination, idempotency, optimistic concurrency, rate-limit conventions, redaction, and no local path leakage.
8. ChatGPT/MCP start_development_task and the REST mission launcher should converge on the same Mission model where operator intent is mission-shaped. Avoid creating two incompatible orchestration paths.
9. No generic shell, no arbitrary path supplied by ChatGPT, no weakening of Node/Project authorization or approval gates.
10. Add the next migration number based on the CURRENT migrations directory; do not reuse a number.
11. Update ORM models, store/services, schema guard, OpenAPI/contract artifact if the public HTTP contract changes, docs, and docs/codemap.md.
12. Preserve existing TaskModel as execution-attempt machinery if useful; do not force an unnecessary rewrite of the executor protocol.
13. Tests must prove:
   - Mission survives DB/session restart semantics (persistence, not in-memory state).
   - one Mission can have multiple attempts/tasks;
   - illegal state transitions are refused;
   - timeline is append-only and ordered;
   - retry/replan retains prior attempt history;
   - Mission API reads from Mission, not inferred Task state;
   - no local_path/command/provider-secret leakage;
   - legacy/current mission behavior required by mobile remains compatible or is deliberately versioned.

Important repository facts:
- issue #43 is the source requirement.
- issue #99 is the current execution checkpoint.
- the current implementation in gateway/app/api/routes/missions.py begins by stating that a Mission is a TaskModel; remove that architectural shortcut.
- Node routing/security from the recent ChatGPT entry implementation must remain fail-closed.
- terminology should prefer operator-facing Mission / Bridge Node / Executor / Engine; do not introduce new unexplained jargon.

Execution rules:
- Make the code changes yourself in this checkout.
- Run focused tests while iterating.
- Do not commit, push, reset, checkout another branch, or alter credentials.
- Do not weaken or delete failing tests just to get green.
- If a requirement conflicts with a documented invariant, preserve the invariant and implement the requirement compatibly; record the tradeoff in docs/code comments where appropriate.
- At the end, print a concise summary of files changed, migrations/contract version, tests run, and any genuine blocker that could not be resolved.
PROMPT

echo "--- codex version ---"
codex --version || true

echo "--- starting Codex implementation ---"
set +e
codex exec -s workspace-write -C "$ROOT" "$(cat "$PROMPT_FILE")"
CODEX_RC=$?
set -e
printf '\nCodex exit code: %s\n' "$CODEX_RC"

echo "--- status after implementation ---"
git status --short

echo "--- diff stat ---"
git diff --stat || true

echo "--- focused tests ---"
set +e
pytest -q tests/integration/test_missions.py tests/integration/test_start_development_task.py tests/unit/test_schema_guard.py tests/unit/test_apply_migrations.py
FOCUSED_RC=$?
set -e
printf 'focused tests exit code: %s\n' "$FOCUSED_RC"

echo "--- refresh codemap ---"
if command -v governancekit >/dev/null 2>&1; then
  governancekit --root "$ROOT" map
  MAP_RC=$?
else
  echo "governancekit not found"
  MAP_RC=127
fi
printf 'codemap exit code: %s\n' "$MAP_RC"

echo "--- contract tests ---"
set +e
pytest -q tests/contract
CONTRACT_RC=$?
set -e
printf 'contract tests exit code: %s\n' "$CONTRACT_RC"

echo "--- full test suite ---"
set +e
pytest -q
FULL_RC=$?
set -e
printf 'full suite exit code: %s\n' "$FULL_RC"

echo "--- final status ---"
git status --short
printf 'head-after: %s\n' "$(git rev-parse HEAD)"
printf '\nRESULT_FILE=%s\n' "${RESULT#$ROOT/}"
printf 'PROMPT_FILE=%s\n' "${PROMPT_FILE#$ROOT/}"
printf 'CODEX_RC=%s FOCUSED_RC=%s MAP_RC=%s CONTRACT_RC=%s FULL_RC=%s\n' "$CODEX_RC" "$FOCUSED_RC" "$MAP_RC" "$CONTRACT_RC" "$FULL_RC"

# Do not auto-commit. The operator uploads the timestamped result and the code
# only after seeing this summary, so ChatGPT can review the actual diff/test run.
exit 0
