# RESUME — WK-20260902-gh73-control-ui (epic #73)

- work_id: WK-20260901-gh73-fleet-visibility
- data: 2026-09-01
- Stage 1: **PR #74 merged** into `development` as `80e5d2f`.
- Stage 2: **PR #75 merged** into `development` on 2026-09-02, and on `main`.
  Contract `1.9.0`. Not deployed.

## Next Step (DO THIS FIRST)

Start Stage 3 (project discovery and adoption: scan the configured roots,
correlate candidates, write `discovered_resources`, and the adopt/ignore
decision) on a branch cut from **`development`** — Stage 2 is merged, so cutting
from `feature/gh-73/fleet-visibility` would now branch from behind. Stage 2 left
the node reporting only a `discovery_root_count`; Stage 3 is what makes the
roots produce rows.
- work_id: WK-20260902-gh73-discovery-adoption
- work_id: WK-20260902-gh73-authorization-plane
- work_id: WK-20260902-gh73-control-ui
- data: 2026-09-02
- Stage 1 (domain/contracts): PR #74 merged into `development` as `80e5d2f`.
- Stage 2 (fleet visibility), Stage 3 (discovery report + adoption), Stage 4
  (authorization plane enforcement): merged onto this lineage before this
  session (`2ed550f`, `a57a8d9`, `a1cf4d7`, `e450c85`, `ac79a47`).
- Stage 5, first cut (this session): branch `feature/gh-73/control-ui`,
  worktree `../CodexBridge--WK-20260902-gh73-control-ui`, base
  `feature/gh-73/authorization-plane`. Committed locally, **not pushed, no PR
  opened** (commit and stop, same as every prior stage in this lineage).

## Next Step (DO THIS FIRST)

Open the PR for `feature/gh-73/control-ui`, get it reviewed, then decide with
the operator whether the next stage is (a) a real `POST /api/v1/nodes/invite`
+ `scripts/enroll_node.py` (the gap this session found and did not build —
see "Watch for" below), or (b) the epic's own Stage 6 (Missions/Decisions/
Audit/Settings convergence).

## Current state

- `GET /api/v1/nodes/{nodeId}/discovered-resources` (cursor-paginated,
  `?state=` filter), `POST /api/v1/discovered-resources/{id}/adopt`,
  `POST .../{id}/deny` — `gateway/app/api/routes/discovery.py`.
- `store.adopt_discovered_resource`/`deny_discovered_resource` are the ONLY
  functions with write access to `projects`/`workspace_bindings`/
  `scm_associations`/`project_authorizations` starting from a
  `discovered_resources` row. Both require `permissions.
  NODES_DISCOVERIES_DECIDE` (`codexbridge.admin`), reachable only by an
  OAuth-authenticated principal — never by a node's `machine_token`.
- Auto-grant: a candidate whose `root_path` matches a `DiscoveryRoot` with
  `auto_authorize` on the node's own `ExecutorRegistration` grants
  automatically (`granted_by="root-config:<path>"`), capped to `read`/`test`
  at parse time. An explicit `grantCapabilities` in the adopt body grants
  with `granted_by="operator:<user_id>"` and may include `modify`/`deliver`.
  Both can apply in the same call — merged into one `project_authorizations`
  row (`;`-joined `granted_by`), since the table allows only one non-revoked
  row per `(node_id, project_id)`.
- **Defect fixed, found by the previous PR and left for this one**:
  `discovered_resources.resource_key` was `varchar(255)` but held a path up
  to 2048 chars — silent on SQLite, a hard failure on MySQL (`aiomysql` is a
  declared dependency). `migrations/0014_discovery_resource_key_hash.sql`:
  `resource_key` becomes `hash_resource_key(path)` (sha256 hex, 64 chars);
  the real path moves to a new, unindexed `resource_path` column. A
  pre-migration row self-heals its `resource_key` the next time its node
  reports the same path (matched by `resource_path`, not `resource_key`).
- Contract bumped **1.9.0 → 1.12.0** (`probes.API_CONTRACT_VERSION` and
  `docs/api/codex-bridge.openapi.yaml`'s `info.version`) — skipping
  1.10.0/1.11.0/1.13.0, claimed by other branches of this same orchestration
  not yet merged onto this one.
- `resourcePath`/`rootPath` are returned ONLY by the three routes above — the
  one pre-registered exception to "no response exposes a server filesystem
  path" (`docs/control-plane.md`, `docs/api/README.md`, `docs/threat-model.md`
  all updated to say so explicitly).

## Changed files

`migrations/0014_discovery_resource_key_hash.sql` (new),
`gateway/app/api/routes/discovery.py` (new),
`gateway/app/services/discovery_types.py` (new),
`tests/integration/test_discovery_routes.py` (new),
`gateway/app/models/entities.py`, `gateway/app/services/store.py`,
`gateway/app/api/permissions.py`, `gateway/app/api/routes/probes.py`,
`gateway/app/db/schema_guard.py`, `gateway/app/main.py`, `shared/security.py`,
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
- `gateway/app/api/routes/control_ui.py` (new): three working screens —
  `GET /control` (fleet), `GET /control/nodes/{nodeId}` (capabilities/
  engines, paginated discovered candidates with Adopt/Deny, authorizations
  with Grant/Revoke), `GET /control/invite` (explanation only — see below).
  HTML in the gateway's own process, the `/oauth/authorize` precedent — no
  template engine, no second deployable.
- Reads call the exact DTO functions the JSON routes already use
  (`routes.nodes._node_dto`, `routes.discovery._discovered_resource_dto`,
  `routes.authorizations._authorization_dto`); writes are `fetch()` against
  the real `/api/v1/**` routes. No business logic duplicated.
- Auth: HTTP Basic, re-verified per request via the same `authenticate_async`
  `/oauth/authorize` uses, gated by the same `permissions.is_allowed`
  catalogue as `/api/v1/**`. A page that needs to write (node detail) mints
  an ordinary, short-lived `oauth_access_tokens` row per render (same table,
  same scope cap as mobile sign-in) embedded inline for that page's own
  `fetch()` calls — never in a URL, never audited on mint. Full reasoning in
  `control_ui.py`'s own module docstring and `docs/control-plane.md`'s
  "Stage 5" section.
- Three new `store.py` read-only helpers, used only by this module:
  `count_decidable_discovered_resources`, `list_active_authorizations_for_node`,
  `get_project_names` (name only, never `ProjectModel.path`).
- **Finding, not silently patched**: the plan's fourth screen
  (`GET /control/invite`) was specified to call `POST /api/v1/nodes/invite`
  and print a `scripts/enroll_node.py` command. Neither exists in this
  codebase — confirmed by grep and by `docs/project-onboarding.md`, which
  already documented node registration as a manual two-file procedure. Built
  as an honest explanation screen instead of a form that posts to nothing.
  See `docs/napkin-lessons.md`'s 2026-09-02 "um plano de UI pode descrever um
  endpoint que nunca foi construído" entry and `control_ui.py`'s own
  docstring, "`/control/invite`".
- `x-contract-excluded-paths` gained three entries (`/control`,
  `/control/nodes/{nodeId}`, `/control/invite`) — HTML, not part of the
  mobile contract, same posture as `/oauth/*`. `API_CONTRACT_VERSION` **not**
  bumped: no `/api` route changed.

## Changed files

`gateway/app/api/routes/control_ui.py` (new),
`tests/integration/test_control_ui.py` (new),
`gateway/app/services/store.py`, `gateway/app/main.py`,
`docs/api/README.md`, `docs/api/codex-bridge.openapi.yaml`,
`docs/control-plane.md`, `docs/operations.md`, `docs/codemap.md`,
`docs/napkin-lessons.md`, `deploy/nginx/frida-codex-bridge.conf`.

## Checks

- `.venv/bin/python -m pytest -q` → **906 passed, 7 skipped, 0 failed**
  (branch baseline before this PR: 886/7).
- `tests/contract/` → all green (26 passed), codemap regenerated with
  `governancekit --root . map`.
- Pytest collection needed the sibling `awt` `.env` moved aside first, same
  as every prior session in this lineage — restored immediately after,
  never committed.

## NOT validated

No deploy, no real browser exercised against a live gateway (all coverage is
`TestClient` + in-memory SQLite). No manual check that the nginx block
proposed in `docs/operations.md` actually reverse-proxies correctly on
`frida` — applying it is the operator's own action, not done by this session.

## Watch for

`GET /control/invite` does not do what its name promises — it explains why
instead. Building the real flow (a token-issuing endpoint with its own
security posture, plus `scripts/enroll_node.py`) is real backend work
belonging to its own PR/stage, flagged here rather than fabricated inside a
UI PR.
