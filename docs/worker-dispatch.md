# Worker admission → Gateway dispatch: eligibility contract

**Status:** first implementation slice, candidate normalization only. The
Git-SSH → Worker → Gateway admission path was verified live on 2026-11-06
(with three PASS evidence manifests in `development-evidences`); the
smoke request was removed from `codexbridge-control`. No new request is
dispatched by this change.

## One execution plane

The Worker observes immutable requests by Git SSH and forwards them to
`/control/worker-intake/requests`. It does **not** execute them. The
Gateway must dispatch via the existing Mission/TaskModel → Executor →
Agent protocol. It must never invent a second shell executor in the Worker.

## Candidate, not permission

`gateway/app/services/worker_dispatch_candidate.py` converts a validated
transport request to a **non-authorizing, immutable** candidate:

- `analyze` → existing `TaskMode.ANALYZE`; `test` → `TaskMode.TEST`.
- `verify` and `build` are **not enabled**. They have no approved
  one-to-one mapping to current TaskMode/capability semantics.
- Only **one explicitly selected Node** is accepted for this first cut.
  `targets.mode=all` or multiple Nodes require a separate scheduling model.
- `parameters` stays empty; no shell command, arbitrary instruction,
  file patch or delivery request can arrive from the control branch.
- Always require an active workspace binding; allow no push/delivery.

## Mandatory gates BEFORE TaskModel creation

1. Re-read the admitted `(project_id, request_id)` ledger entry and verify
   canonical payload digest, exact worker identity and `admitted` state.
2. Verify the operator-issued Worker project lease is still active.
3. Resolve the **operator-approved** project/repository association and
   independently verify the immutable source commit belongs to the approved
   repository/branch. Never infer forge authority from the JSON envelope.
4. Resolve the selected Node to an enabled Node and authenticated Executor.
   Never use a user-supplied executor ID.
5. Require an **active** WorkspaceBinding and ProjectAuthorization for that
   Node, then reuse `store.require_active_node_project_authorization` and
   `store.create_task(require_active_binding=True)`.
6. Obtain a **separate, attributable operator execution approval**. Worker
   project activation only permits *intake*, not execution. Preserve human
   decision/audit events.
7. Persist a unique request→Mission/Task correlation **atomically before
   dispatch**; replay must return the prior identity and never create a new
   task. Crash and concurrent pollers may not produce duplicate execution.
8. Require the Executor to independently enforce its allowed project/mode
   and verify the pinned commit before doing work. If any check fails, deny.
9. Publish sanitized state/receipt/evidence; never raw credentials, local
   workspace paths, or source contents in the evidence manifest.

**Next slice:** model operator execution approval and durable correlation,
then wire the Gateway into the existing mission scheduler. No deployment,
SSH access, daemon restart, or new control-branch request is part of this PR.

## Execution grant implementation (2026-11-10)

The independent eight-hour authorization is exposed by admin-only
`POST /control/worker-execution-grants` and
`POST /control/worker-execution-grants/{grant_id}/revoke`.
The required JSON request is
`{"workerId":"w1","projectId":"codexbridge","nodeId":"devel3","repository":"EDortta/CodexBridge","modes":["analyze","test"]}`.
Before granting, the Gateway verifies operator admin identity, bound repository,
enabled project/Node/Executor, active workspace binding, capabilities and
project allowed modes. The transactional grant service also requires an
active operator-issued intake lease, serializes grants, refuses conflicting
active scopes and never extends a reissued grant. Revocation blocks future
starts; it does not claim to stop already-running work. Apply migration 0023
as part of the normal release process before enabling this route.

**This does not authorize a task by itself:** dispatch still requires admitted
request digest, exact source commit and approved repository, node eligibility,
new grant, and durable idempotent Mission correlation. Until those checks and
the dispatch bridge are implemented there is no automatic Worker execution.
