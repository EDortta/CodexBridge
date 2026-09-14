#!/usr/bin/env bash
set -u

ROOT="$(git rev-parse --show-toplevel)" || exit 1
cd "$ROOT" || exit 1
mkdir -p temp-tools/results
STAMP="$(date -u +%Y%m%d-%H%M%SZ)"
HOST="$(hostname -s 2>/dev/null || hostname)"
RESULT="temp-tools/results/${STAMP}-${HOST}-issue-to-mission-workflow.txt"
PROMPT="temp-tools/results/${STAMP}-${HOST}-issue-to-mission-workflow.prompt.txt"

exec > >(tee -a "$RESULT") 2>&1

echo "=== CodexBridge #44 issue-to-Mission implementation ==="
echo "timestamp: $(date -Is)"
echo "host: $HOST"
echo "branch: $(git branch --show-current)"
echo "head-before: $(git rev-parse HEAD)"
echo
echo "--- status before ---"
git status --short

cat > "$PROMPT" <<'EOF'
You are implementing CodexBridge issue #44 on the CURRENT development checkout. Implement the feature; do not stop at planning.

Source issue #44: "Implement issue-to-mission development workflow".

Objective:
Allow an operator to select an issue and tell CodexBridge to resolve it as one governed, durable Mission.

Existing foundations already present and MUST be reused rather than duplicated:
- durable Mission aggregate from #43 is complete and green;
- provider-neutral local issue/epic APIs and MCP tooling from #78 exist;
- SCM/GitHub binding and executor-owned external operations from #79/#80 exist;
- start_development_task / node routing baseline exists;
- Mission, Task/Session, Bridge Node, Executor and Engine are distinct concepts;
- security rules: no generic shell, no path leakage, no provider secrets to coding agents, authorization fail-closed, approval gates preserved.

Required workflow:
1. Resolve project and source issue through the provider-neutral issue integration already in the repo. Do not hard-wire GitHub as the domain owner.
2. Snapshot the execution-relevant source issue state: source identity/provider/ref, revision/version signal when available, title, body/description, comments that matter to execution, labels and dependency references supported by the existing model/provider layer.
3. Persist that snapshot or an immutable canonical representation tied to the Mission so later issue edits do not silently rewrite the Mission's planning basis.
4. Build Mission objective/constraints from the issue snapshot while preserving the durable Mission identity.
5. Route through existing planning/review policy and node/project authorization. Do not bypass policy to make the workflow convenient.
6. Schedule/route the first execution attempt using the existing Mission/Task machinery.
7. Ensure delivery evidence remains attached to the Mission/attempt and can later be linked back to the source issue.
8. Detect material source-issue change after Mission creation. Surface a clear replan/decision condition; do not silently continue on stale intent.
9. Never close the source issue solely because the agent process/task exited successfully. Closure/update must remain an explicit policy-controlled external operation with delivery evidence.

Idempotency requirement:
Repeated equivalent operator requests for the same project + source issue + intent must not create duplicate active Missions. Use the repository's existing idempotency/concurrency conventions; do not invent an unsafe global singleton rule. A genuinely new run after a completed/cancelled Mission should remain possible by explicit intent/revision/key.

API/MCP/operator behavior:
- Add the narrowest operator-facing REST and/or MCP entrypoint consistent with existing architecture so a caller can say effectively `resolve issue X for project Y`.
- ChatGPT and future MOBO clients must use the same domain service/store path.
- Responses must return traceable mission_id, source issue identity/snapshot metadata, current state and relevant task/attempt identifiers without exposing local filesystem paths, commands or provider secrets.
- Preserve current API compatibility. If public contract changes, bump/publish the next contract version using established repository scripts/conventions and update tests/docs/codemap.

Data model / persistence:
- Prefer adding explicit source snapshot fields/table/entity only if needed for durability and immutability. Do not overload TaskModel.
- If schema changes are needed, add the NEXT migration after current migrations and cover upgrade from existing databases. Never rely on create_all as migration.
- Keep append-only Mission timeline events for creation/material issue change/replan conditions.

Testing acceptance:
Add or repair tests proving at least:
- one request creates one durable Mission linked to the source issue snapshot;
- repeated equivalent request is idempotent and returns/reuses the same active Mission rather than duplicating it;
- a second deliberate run can be created when policy/idempotency key/revision says it is new intent;
- snapshot survives issue changes and restart/database reload;
- material source change while running is detected and produces waiting-human/blocked/replan decision semantics rather than silently mutating objective;
- source issue is NOT auto-closed merely because execution completes;
- project/node authorization remains enforced;
- response/MCP surfaces do not leak local paths, raw commands or provider credentials;
- existing Mission, Session, issue, SCM/forge and contract tests remain green.

Implementation rules:
- inspect current code/tests/docs before editing;
- modify the checkout directly;
- do not commit, push, reset, checkout another branch, or alter credentials;
- do not weaken/delete tests to obtain green;
- do not install/upgrade global dependencies;
- reuse existing provider-neutral issue and SCM abstractions;
- use terminology from issue #81: Mission, Bridge Node, Executor, Engine, Project, Workspace, SCM provider/repository host; avoid introducing new operator-facing jargon.

Run focused tests while working, then at minimum:
python3 -m pytest -q tests/integration/test_missions.py tests/integration/test_mcp_epics_issues.py tests/integration/test_forge_wiring.py tests/integration/test_start_development_task.py 2>/dev/null || true
python3 -m pytest -q tests/unit/test_apply_migrations.py tests/unit/test_schema_guard.py
python3 -m pytest -q tests/contract
python3 -m pytest -q

governancekit --root . map

At the end print exactly:
ISSUE_TO_MISSION:
IDEMPOTENCY:
SNAPSHOT_AND_DRIFT:
AUTHORIZATION:
CONTRACT:
MIGRATION:
FOCUSED_TESTS:
CONTRACT_TESTS:
FULL_SUITE:
BLOCKERS:
FILES_CHANGED:
EOF

echo
echo "--- codex version ---"
codex --version

echo
echo "--- Codex implementation run ---"
codex exec -s workspace-write -C "$ROOT" "$(cat "$PROMPT")"
CODEX_RC=$?

echo
echo "--- status after Codex ---"
git status --short

echo
echo "--- focused #44 tests ---"
python3 -m pytest -q tests/integration/test_missions.py tests/integration/test_mcp_epics_issues.py tests/integration/test_forge_wiring.py tests/integration/test_start_development_task.py
FOCUSED_RC=$?

echo
echo "--- migration/schema tests ---"
python3 -m pytest -q tests/unit/test_apply_migrations.py tests/unit/test_schema_guard.py
MIGRATION_RC=$?

echo
echo "--- contract tests ---"
python3 -m pytest -q tests/contract
CONTRACT_RC=$?

echo
echo "--- full suite ---"
python3 -m pytest -q
FULL_RC=$?

echo
echo "--- codemap refresh ---"
governancekit --root "$ROOT" map
CODEMAP_RC=$?

echo
echo "--- final status ---"
git status --short

echo
echo "RESULT_CODES codex=${CODEX_RC} focused=${FOCUSED_RC} migration=${MIGRATION_RC} contract=${CONTRACT_RC} full=${FULL_RC} codemap=${CODEMAP_RC}"
echo "RESULT_FILE=$RESULT"
exit 0
