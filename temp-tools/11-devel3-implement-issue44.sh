#!/usr/bin/env bash
set -u
ROOT="$(git rev-parse --show-toplevel 2>/dev/null || true)"
[[ -n "$ROOT" ]] || { echo "ERROR: run inside CodexBridge" >&2; exit 2; }
cd "$ROOT"
STAMP="$(date -u +%Y%m%d-%H%M%SZ)"
OUT="temp-tools/results/${STAMP}-devel3-issue44-implementation.txt"
PROMPT_FILE="temp-tools/results/${STAMP}-devel3-issue44-implementation.prompt.txt"
mkdir -p temp-tools/results

cat > "$PROMPT_FILE" <<'PROMPT'
Implement GitHub issue #44 in the current CodexBridge development checkout. This is an implementation run, not a planning exercise.

Context already established and do not redo it:
- Durable Mission aggregate/state machine (#43) is complete and green.
- Provider-neutral/local issue integration and executor-owned forge operations already exist.
- migrations/0018_mission_issue_snapshots.sql has been added as the persistence foundation.
- Prior after-hours Codex attempts were blocked by GovernanceKit; do not weaken or edit GovernanceKit.
- Preserve unrelated untracked local noise (.claude-flow, .swarm, handoff files, coordination-status, ruvector.db).

Implement the smallest coherent #44 slice that satisfies the issue acceptance criteria:
1. Add the SQLAlchemy model corresponding to mission_issue_snapshots and integrate it with existing model conventions.
2. Add provider-neutral issue snapshot construction with deterministic canonical hashing. Snapshot identity/provider/ref/revision/title/body or description/comments/labels/dependencies/status needed for planning. Never mutate a stored snapshot.
3. Add a shared domain/store service for resolve-issue-as-Mission. It must use the same path for REST/MCP rather than duplicating orchestration.
4. Idempotency: repeated equivalent project + source issue + intent requests reuse the same active Mission; support an explicit new run when the existing public contract has a suitable convention, otherwise design the narrowest explicit flag.
5. Build Mission objective/constraints from the immutable snapshot, record source issue linkage, append Mission events, and route/schedule the first implementation attempt through existing Mission/Task machinery and authorization policy.
6. Detect material issue drift by comparing the current canonical snapshot with the Mission planning snapshot. Never silently rewrite the plan. Surface a legal Mission replan/waiting-human/blocked condition and append evidence to the timeline.
7. Delivery evidence must attach to Mission/attempt. Agent/task process success alone MUST NOT close the source issue. External update/close remains policy-controlled executor-owned forge work.
8. Add the narrow REST and MCP operator entrypoint needed for: resolve issue X for project Y. Do not expose local paths, commands, tokens, or secrets.
9. Update public contract/version/docs/codemap only if the repository's existing compatibility rules require it.
10. Add focused tests for immutable snapshot, idempotency, explicit rerun, drift, authorization/security, source linkage/evidence, and no auto-close.

Inspect current code and conventions before editing. Reuse existing IssueModel, MissionModel, mission transition service, authorization, store, MCP issue tools, forge routing, schemas and contract patterns. Do not hard-wire GitHub into the Mission domain.

Do not commit, push, reset, install global/user dependencies, delete unrelated files, or change GovernanceKit. If a real material governance/security blocker occurs, stop and report it precisely. Otherwise implement and test.

After implementation run the focused #44 tests you add, existing Mission tests, migration/schema tests using paths that actually exist in this checkout, contract tests, codemap/governance freshness tests using paths that actually exist, then the full pytest suite if feasible.

Finish with a concise structured summary containing: IMPLEMENTED, FILES_CHANGED, MIGRATION, FOCUSED_TESTS, MISSION_TESTS, CONTRACT_TESTS, FULL_SUITE, BLOCKERS, NEXT.
PROMPT

{
  echo "ISSUE: #44 issue-to-Mission implementation"
  echo "TIMESTAMP_UTC: $STAMP"
  echo "HOST: $(hostname)"
  echo "BRANCH: $(git branch --show-current)"
  echo "HEAD_BEFORE: $(git rev-parse HEAD)"
  echo "WORKTREE_BEFORE:"
  git status --short
  echo
  echo "== CODEX =="
} | tee "$OUT"

if command -v codex >/dev/null 2>&1; then
  codex exec --dangerously-bypass-approvals-and-sandbox "$(cat "$PROMPT_FILE")" 2>&1 | tee -a "$OUT"
  CODEX_RC=${PIPESTATUS[0]}
else
  echo "ERROR: codex CLI not found" | tee -a "$OUT"
  CODEX_RC=127
fi

{
  echo
  echo "== WORKTREE AFTER =="
  git status --short
  echo "HEAD_AFTER: $(git rev-parse HEAD)"
  echo "CODEX_RC: $CODEX_RC"
  echo "RESULT_FILE: $OUT"
  echo "PROMPT_FILE: $PROMPT_FILE"
} | tee -a "$OUT"

# Always leave evidence for inspection. Never commit/push here: ChatGPT reviews
# the diff and test output first, then supplies a narrow finalize runner.
exit 0
