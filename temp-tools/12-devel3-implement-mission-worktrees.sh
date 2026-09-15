#!/usr/bin/env bash
set -u

ROOT="/home/esteban/Sync/Projects/AI/CodexBridge"
cd "$ROOT" || exit 1

STAMP="$(date -u +%Y%m%d-%H%M%SZ)"
OUT_DIR="temp-tools/results"
mkdir -p "$OUT_DIR"
PROMPT_FILE="$OUT_DIR/${STAMP}-devel3-issue49-worktrees.prompt.txt"
RESULT_FILE="$OUT_DIR/${STAMP}-devel3-issue49-worktrees.txt"

cat >"$PROMPT_FILE" <<'PROMPT'
Implement GitHub issue #49 in EDortta/CodexBridge. This is an implementation run, not a planning-only run.

Objective: every development Mission attempt must have an isolated, recoverable Git workspace and concurrent Missions must not corrupt each other's work.

Read the repository's GovernanceKit/project instructions first and obey them. Do not weaken, bypass, edit, or disable GovernanceKit. If a governance rule denies the run, stop and report it. We are running during the normal authorized work window.

Current baseline: development is green with 1520 passed, 9 skipped. Durable Mission (#43) and issue-to-Mission orchestration (#44) are complete. Contract latest is 1.20.0. Preserve those semantics.

Implement #49 completely using existing architecture and naming conventions. Requirements:
- Define durable workspace ownership per Mission attempt: repository/project, node/executor, base branch, immutable base commit, mission branch, worktree identity/path metadata, owner mission/attempt, lifecycle state and timestamps.
- Never expose arbitrary local filesystem paths through public/MCP/operator input. Workspace location is executor-derived from authorized project configuration and stable Mission/attempt identity.
- Before mutation inspect repository root, HEAD/base revision, dirty tracked state, untracked state and existing worktrees. Fail closed rather than overwrite or clean operator work.
- Never use git reset --hard, git clean, force checkout, force push, or automatic deletion of unknown/unmerged work.
- A Mission attempt must not mutate the shared project checkout. Create/use an isolated git worktree for implementation. Branch/worktree names must be deterministic, bounded and safe from operator-controlled shell/path injection.
- Prevent two incompatible active attempts from owning the same mutable workspace/branch. Persist ownership so gateway/executor restart can recover it. Make acquisition idempotent for the same attempt.
- Parallel Missions may use distinct worktrees when project policy permits.
- Record the base commit before implementation. Detect if expected base/ownership changed before mutation/delivery and surface a typed conflict rather than guessing.
- Define lifecycle and safe cleanup for completed, failed, cancelled and abandoned attempts. Cleanup must never delete operator work, dirty worktrees, unmerged commits, or an ownership record needed for recovery. Unsafe cleanup must leave the workspace intact and record why.
- Integrate workspace preparation into the existing Mission/Task dispatch path at the narrowest shared domain boundary; do not build a second orchestration system.
- Add append-only Mission events for meaningful workspace acquisition/conflict/recovery/cleanup decisions.
- Keep GitHub/provider concerns outside the workspace domain.
- Update migrations/schema guard/models/services/protocol/API/MCP only where actually needed. Bump the public contract only if the public shape changes.
- Add focused unit/integration tests covering deterministic naming, traversal/injection rejection, dirty shared checkout protection, isolated worktree creation, idempotent reacquisition, concurrent Mission isolation/conflict, restart recovery, base commit persistence, and safe cleanup refusal.
- Update docs/security/threat model/codemap if required by current repository governance.
- Do not commit or push. Do not install packages. Do not touch unrelated local noise (.claude-flow, .swarm, handoff files, coordination-status, ruvector.db).

Before finishing, run the focused tests you added/changed and then the full pytest suite. Report changed files, migration/contract changes, test counts, and any remaining blocker. Do not claim completion if tests are red.
PROMPT

{
  echo "TIMESTAMP=$STAMP"
  echo "HOST=$(hostname)"
  echo "BRANCH=$(git branch --show-current)"
  echo "HEAD_BEFORE=$(git rev-parse HEAD)"
  echo "STATUS_BEFORE"
  git status --short
  echo
  echo "=== CODEX ==="
} >"$RESULT_FILE"

codex exec --dangerously-bypass-approvals-and-sandbox "$(cat "$PROMPT_FILE")" 2>&1 | tee -a "$RESULT_FILE"
CODEX_RC=${PIPESTATUS[0]}

{
  echo
  echo "=== AFTER ==="
  echo "CODEX_RC=$CODEX_RC"
  echo "HEAD_AFTER=$(git rev-parse HEAD)"
  echo "STATUS_AFTER"
  git status --short
  echo "DIFF_STAT"
  git diff --stat
  echo "DIFF_NAME_ONLY"
  git diff --name-only
} >>"$RESULT_FILE"

printf '\nResult: %s\n' "$RESULT_FILE"
exit "$CODEX_RC"
