# RESUME — WK-20260902-gh73-authorization-plane (epic #73)

- work_id: WK-20260902-gh73-authorization-plane
- data: 2026-09-02
- Stage 1 (domain/contracts): **PR #74 merged** into `development` as `80e5d2f`.
- Stage 2 (fleet visibility): merged onto this lineage (`2ed550f`).
- Stage 3, report half (node proposes): merged onto this lineage (`a57a8d9`).
- Stage 3, adoption half (panel decides): merged onto this lineage (`a1cf4d7`,
  PRs #91/#92 — first real writes to `project_authorizations`).
- Stage 4 (authorization plane enforcement): **this session**, branch
  `feature/gh-73/authorization-plane`, worktree
  `../CodexBridge--WK-20260902-gh73-authorization-plane`. Committed locally,
  **not pushed, no PR opened** (out of this session's scope — commit and stop).

## Next Step (DO THIS FIRST)

Open the PR for `feature/gh-73/authorization-plane` against
`feature/gh-73/discovery-adoption`, get it reviewed — flag the `is_admin()`
finding below explicitly in the PR description, it is a judgment call a
reviewer should confirm, not rubber-stamp — then check the epic's own issue
body for whatever Stage 5 (or the next unstarted stage) is.

## Current state

- `store.effective_task_modes(session, executor, project)` is now the ONLY
  place that decides which `TaskMode`s an executor may run against a
  project — `store.create_task` calls it at the exact spot its old inline
  `allowed_modes` check lived. A pair with no `workspace_bindings` row is
  governed by `allowed_modes` alone, forever (not a grace period); a bound
  pair is `allowed_modes` intersected with `capabilities_to_modes(...)` of
  its active `project_authorizations` row.
- `agent/codex_bridge_agent/service.py:_handle_dispatch` gained its own,
  independent mirror: refuses a dispatch whose mode this node's own
  configuration (`allow_workspace_write`/`allow_git_delivery`, via the new
  `_configured_capabilities` helper shared with `_build_announcement`)
  never offered, with a typed `capability_not_configured:<mode>` error —
  defense in depth, not duplication (same reasoning `git_delivery.py`
  already applies to the branch pattern).
- `POST /api/v1/nodes/{nodeId}/projects/{projectId}/authorize` and
  `.../revoke` — new `gateway/app/api/routes/authorizations.py`.
  `store.grant_project_authorization` (get-or-create-or-reactivate,
  OVERWRITES capabilities rather than merging — different from adoption's
  own merge-only `_grant_project_authorization`) and `store.
  revoke_project_authorization` (marks `revoked_at`, never deletes).
- New administrative action `permissions.NODES_AUTHORIZATIONS_MANAGE`
  (`codexbridge.admin`). Granting `modify`/`deliver` crosses a second gate
  inside `permissions.is_allowed`: `principal.can_approve_sensitive or
  "admin" in principal.roles`.
- **Finding, not silently patched**: the plan asked for the same shape
  `DECISIONS_DECIDE`'s second gate has —
  `principal.can_approve_sensitive or principal.is_admin()`. Implemented
  literally, that gate is TAUTOLOGICAL here: `NODES_AUTHORIZATIONS_MANAGE`'s
  own base scope already IS `codexbridge.admin`, and `is_admin()` returns
  `True` for ANY principal whose token merely carries that scope (`"admin"
  in principal.roles or "codexbridge.admin" in principal.scopes`) — so
  `has_scope(action.scope)` and `is_admin()` are the same predicate for
  this one action, and `can_approve_sensitive` would never be the deciding
  factor. `DECISIONS_DECIDE`'s own scope (`codexbridge.task.approve`) is
  disjoint from `codexbridge.admin`, which is why the identical code is
  meaningful THERE and not here. Fixed by checking `"admin" in
  principal.roles` directly instead of calling `is_admin()` — documented at
  length in `permissions.is_allowed`'s own docstring and in
  `docs/napkin-lessons.md`'s 2026-09-02 entry. Proven by
  `tests/integration/test_authorization_routes.py::
  test_granting_modify_without_can_approve_sensitive_or_admin_role_is_refused`,
  which fails against the naive `is_admin()` version.
- **Pre-existing gap, NOT fixed by this PR (out of scope, flagged for the
  operator)**: `POST /api/v1/discovered-resources/{id}/adopt`'s own
  `grantCapabilities` (Stage 3, C3) can already grant `modify`/`deliver`
  under `NODES_DISCOVERIES_DECIDE` with NO second gate at all — any
  principal with the bare `codexbridge.admin` scope can grant sensitive
  capability through the adoption route today, unrelated to whether this
  PR's own `authorize` route enforces `can_approve_sensitive`. Worth a
  follow-up if the operator wants the same ladder applied there.
- Contract bumped **1.12.0 → 1.14.0** (`probes.API_CONTRACT_VERSION` and
  `docs/api/codex-bridge.openapi.yaml`'s `info.version`) — skipping 1.13.0,
  claimed by another not-yet-merged branch of this same orchestration.

## Changed files

`gateway/app/api/routes/authorizations.py` (new),
`tests/unit/test_effective_task_modes.py` (new),
`tests/integration/test_authorization_routes.py` (new),
`gateway/app/services/store.py`, `gateway/app/api/permissions.py`,
`gateway/app/api/routes/probes.py`, `gateway/app/main.py`,
`agent/codex_bridge_agent/service.py` (`shared/protocol.py` untouched — its
`Capability`/`CAPABILITY_MODES`/`capabilities_to_modes` from Stage 1 already
had everything this PR needed),
`tests/unit/test_agent_service.py`, `tests/integration/test_auth.py`,
`docs/api/README.md`, `docs/api/codex-bridge.openapi.yaml`,
`docs/control-plane.md`, `docs/project-onboarding.md`, `docs/codemap.md`,
`docs/napkin-lessons.md`.

## Checks

- `.venv/bin/python -m pytest -q` → **884 passed, 7 skipped, 0 failed**
  (branch baseline before this PR: 858/7).
- `tests/contract/` → all green (26 passed), including the OpenAPI
  route/version-parity gates and the codemap freshness gate (regenerated
  with `governancekit --root . map`).
- Pytest collection needed the sibling `awt` `.env` moved aside first
  (`Settings` uses `extra="forbid"`, per this session's own instructions —
  restored immediately after the run, never committed, `.env` is
  gitignored).

## NOT validated

No deploy, no real gateway/executor pair exercised end-to-end over a live
WebSocket with a real `project_authorizations` grant in effect (all coverage
is against an in-memory SQLite `AsyncSession` or a `DummyWebSocket`/fake
runner). No MySQL run of this PR's own migrations — there are none; this PR
adds no schema, only reads/writes the Stage 1 `project_authorizations` table
that already exists.

## Watch for

The `is_admin()` finding above is a judgment call this session made
unilaterally (deviating from the plan's literal `principal.is_admin()`
instruction) because implementing it literally would have shipped a gate
that looks like a control but never binds. Flag it in the PR description
explicitly rather than letting a reviewer discover the deviation from a
diff alone.
