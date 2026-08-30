Parent: #63
Related: #51 (this is the "push branch" delivery mode #51 already lists), #64 (#41a), #65 (start_development_task)

## Objective
Let an operator pre-authorize commit and push in the same request that starts the work, so "resolve issue X, branch feature/uc-X, you can push" actually results in a pushed branch — without turning the sensitive-keyword policy gate into a bypass, and without ever reaching `main`.

## Scope
- `shared/protocol.py`: `DeliveryRequest` (`branch`, `allow_push`, `base_branch`, `remote`, `commit_subject`), `PUSHABLE_BRANCH_PATTERN` — defined once and imported by both gateway and executor, the same precedent `STOPPABLE_TASK_STATES` already sets against the two sides drifting apart.
- `shared/policy.py`: one new clause in `evaluate_task_policy`.
- `gateway/app/services/store.py`: `create_task` pre-authorization handling.
- New `agent/codex_bridge_agent/git_delivery.py`. `agent/codex_bridge_agent/git_tools.py` stays read-only, untouched.
- `migrations/0008_engine_and_delivery.sql` (shared with #64/#65): adds `engine`, `issue_ref`, `delivery_json` (what was requested), `delivery_result_json` (what happened — a separate column from `result_json`, so "did it push, what commit" is a column read, not a JSON parse). All four columns added to `gateway/app/db/schema_guard.py:REQUIRED_COLUMNS["tasks"]`, and `delivery_result_json` added to the reset list inside `store.restart_finished_task` (which today clears `result_json`/`command_json` but nothing else — a `delivery_result_json` left out of that list would make a restarted task report the *previous* run's commit sha).

## Requirements — policy interaction
`SENSITIVE_KEYWORDS` is not changed or weakened in any way. Instead: `evaluate_task_policy` gains a clause where `delivery.allow_push == true` forces `PolicyLevel.SENSITIVE` with reason `delivery_requests_push` — an intent to push is treated as structurally sensitive whether or not the word "push" appears in the instruction text. Then, in `store.create_task`, when `allow_push` is true **and** `branch` matches `PUSHABLE_BRANCH_PATTERN` **and** the requesting principal holds approval authority (`codexbridge.task.approve`, not just `codexbridge.task.submit` — push is an approval-class act and must not be reachable with a submit-only token):
1. the task is written `AWAITING_APPROVAL` with `policy_level='sensitive'`, exactly as today;
2. it is resolved in the same transaction through the **existing** `decide_task_approval(..., ApprovalDecision.APPROVED, reason="pre-authorized in request by <actor>")` path;
3. a `task.push_preauthorized` audit event is recorded with actor id, email, branch, base branch, and remote.

This reuses the already-tested approval machinery rather than adding a parallel bypass path — `task.approval_decision`, `approval_state`, and the actor trail come for free, and the decision is visible in `/api/v1/decisions` like every other one. If the branch fails the pattern or the principal lacks approval authority, **the task is not created**: typed `branch_not_pushable` / `approval_not_allowed`, refused at submission rather than queued to fail later. An instruction that merely mentions "push" with no `delivery` object attached is unaffected — existing keyword-triggered `AWAITING_APPROVAL` behavior is unchanged.

On the executor, the local policy re-evaluation in `_handle_dispatch` (which today unconditionally refuses anything `SENSITIVE`) is changed to accept `SENSITIVE` **only when** the dispatch payload carries `delivery.allow_push` **and** the branch again matches `PUSHABLE_BRANCH_PATTERN` — re-checked independently, so a compromised gateway cannot push to `main` by lying about the branch. Add a regression test pinning that `_sandbox_for` still returns `workspace-write` for `SENSITIVE` tasks; a naive hardening of "`SENSITIVE` → `read-only`" would silently turn every pre-authorized push task into a no-op — exactly issue #34's failure mode (exit 0, `no_changes: true`, no error anywhere).

## Requirements — the git delivery step
Runs in `_handle_dispatch`, after the runner returns and before the `task.result` frame is sent — outside the provider's sandbox (push needs network, which `workspace-write` does not have) and outside the reach of a `restart`. New machine-level kill switch `AgentSettings.allow_git_delivery: bool = False`, off by default, the same "last barrier on this machine" shape `allow_workspace_write` already has.

Exact sequence, each step a typed refusal rather than an exception:
1. `git rev-parse --show-toplevel` must equal `project_root`, else `not_repo_root`.
2. If current `HEAD` is `main`/`master` and no `branch` was given, `refuse_to_work_on_main`.
3. `git status --porcelain=v1 -z --untracked-files=all` produces the explicit list of changed paths — the **only** source of what gets staged. Empty → `skipped: no_changes`.
4. Deny-list scan over those paths (`.env*`, `.credentials/**`, `*.pem`, `*.key`, `id_rsa*`, `**/node_modules/**`, `codex_bridge.db`, `.git/**`) → `forbidden_path`, nothing staged. More than ~200 changed paths → `too_many_paths` (a change that size is not what was authorized).
5. `git switch -c <branch>` if it does not exist, `git switch <branch>` if it does. Branch creation is permitted **only** because `branch` + `allow_push` in the original request is the recorded human permission `git-delivery.md` requires; emit a log line so `task.branch_created` appears in the timeline.
6. **Stage by explicit path only:** `git add -- <p1> <p2> …`. Never `-A`, never `.`, never `commit -a`.
7. **Re-read `HEAD` immediately before committing** and compare against the value captured after step 5 — moved → `head_moved`, reporting both shas, nothing committed, nothing unstaged (the tree stays inspectable). This is the shared-working-tree gate `AGENTS.md`/`git-delivery.md` mandate unconditionally.
8. `git -c user.name=… -c user.email=… commit -m … -m …` — `-c` on the command line, never a `git config` write into the repo. Commit body carries `Task-Id:`, `Issue:`, `Engine:`, `Executor:`.
9. `git push --set-upstream <remote> <branch>`. **Never** `--force`, `--force-with-lease`, or a `+refs` refspec. Non-fast-forward → refused; **no** automatic fetch-and-rebase — that is a merge decision and stays human.
10. **Verify the post-condition**: `git rev-parse <remote>/<branch>` must equal the local commit sha, else `pushed: false, reason: push_verification_failed` — a command returning 0 is not proof.

`task.result.delivery` reports `{attempted, outcome, reason, branch, base_branch, created_branch, head_before, commit, remote, remote_sha, pushed, staged_paths, files_changed, insertions, deletions, commit_subject}`.

**Deliberate trade-off, stated here explicitly:** a task whose code succeeded but whose push was refused stays `COMPLETED` with `delivery.outcome: "refused"` plus a `task.delivery_refused` audit event — never `FAILED`. Marking it `FAILED` would make `restart` re-run the entire agent job to fix what is only a git problem. This is a field, not a state: **no 14th `TaskState` value is added** — the enum is closed, published, and the Flutter client switches on it (council finding **F02**).

## ARO
- **F14** (write-capable git credential newly in reach of the executor process): this changes the basis of an accepted risk in `docs/threat-model.md`, which must be updated in the same PR. What keeps it acceptable: push runs outside the provider sandbox in a step the provider cannot itself invoke; `allow_git_delivery` defaults `False` per executor; the branch pattern is enforced independently on both gateway and executor; the credential used is git's own on the executor host (ssh-agent / credential helper), never passed through any runner's environment allowlist.
- **F02** (closed `TaskState` enum): respected — see the delivery-outcome-as-field decision above.
- **F34** (this repo's own docs note `CodexRunner.cancel` can return `False` without killing the process): out of scope here but worth flagging — a cancelled task that still has a running git delivery step in flight is a real interaction this issue does not resolve; the git step should check for cancellation before committing, and that check should be added as part of implementation even though it is not separately tracked.

## Test plan
- `tests/unit/test_policy.py`: the four-cell matrix — keyword alone (unchanged: `AWAITING_APPROVAL`, no auto-resolve); `allow_push` with no keyword (forces `SENSITIVE`, auto-resolves to one recorded approval); `allow_push` targeting `main` (refused at submission, task never created); keyword **and** `allow_push` together (exactly one decision is recorded, not two).
- New `tests/unit/test_git_delivery.py` against a throwaway git repository created in the session scratchpad (an exception `docs/limits.md` already authorizes as a test fixture): refuses `main`; refuses a forbidden path; the `git add` argv contains `--` and never `-A` or a bare `.`; detects `HEAD` moving between the status read and the commit; no force flag appears in any argv; the push step verifies `remote_sha == commit_sha` before reporting success.
- `tests/unit/test_schema_guard.py`: the four new columns fail startup when absent.
- `tests/unit/test_apply_migrations.py`: `0008` applies cleanly on SQLite.
- New `tests/integration/test_delivery_end_to_end.py`: extend the in-memory socket harness `tests/integration/test_reconnect_replay_resolves.py` already provides with a deterministic fake runner that writes a file and returns `COMPLETED`; assert the delivery step committed and `tasks.delivery_result_json` holds the resulting sha.

## Definition of Done
- A pre-authorized push to a `feature/*` branch produces a real commit and a verified push, end to end, in the live smoke test.
- No path exists by which an instruction can reach `main`/`master` regardless of any flag combination.
- `docs/threat-model.md` and `docs/security.md` (policy evaluation order) are updated in the same PR.
