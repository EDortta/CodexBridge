# RESUME — WK-20260902-gh73-discovery-adoption (epic #73)

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
- data: 2026-09-02
- Stage 1 (domain/contracts): **PR #74 merged** into `development` as `80e5d2f`.
- Stage 2 (fleet visibility): merged onto this lineage (`2ed550f`).
- Stage 3, report half (node proposes): merged onto this lineage (`a57a8d9`,
  branch `feature/gh-73/discovery-report`).
- Stage 3, adoption half (panel decides): **this session**, branch
  `feature/gh-73/discovery-adoption`, worktree
  `../CodexBridge--WK-20260902-gh73-discovery-adoption`. Committed locally,
  **not pushed, no PR opened** (out of this session's scope — commit and stop).

## Next Step (DO THIS FIRST)

Open the PR for `feature/gh-73/discovery-adoption` against
`feature/gh-73/discovery-report` (or wherever the operator wants it based),
get it reviewed, then start Stage 4 of the epic (whatever "fleet enable/disable
and node lifecycle actions" or the next unstarted stage is — check the epic's
own issue body, not this file, for the authoritative stage list).

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
  declared dependency). `migrations/0013_discovery_resource_key_hash.sql`:
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

`migrations/0013_discovery_resource_key_hash.sql` (new),
`gateway/app/api/routes/discovery.py` (new),
`gateway/app/services/discovery_types.py` (new),
`tests/integration/test_discovery_routes.py` (new),
`gateway/app/models/entities.py`, `gateway/app/services/store.py`,
`gateway/app/api/permissions.py`, `gateway/app/api/routes/probes.py`,
`gateway/app/db/schema_guard.py`, `gateway/app/main.py`, `shared/security.py`,
`docs/api/README.md`, `docs/api/codex-bridge.openapi.yaml`,
`docs/control-plane.md`, `docs/threat-model.md`, `docs/codemap.md`,
`tests/unit/test_discovery_store.py`, `tests/integration/test_agent_ws_discovery.py`,
`tests/integration/test_auth.py`.

## Checks

- `.venv/bin/python -m pytest -q` → **858 passed, 7 skipped, 0 failed**
  (branch baseline before this PR: 829/7).
- `tests/contract/` → all green (26 passed), including the OpenAPI route/
  version-parity gates and the codemap freshness gate (regenerated with
  `governancekit --root . map`).
- `tests/unit/test_apply_migrations.py` → all green; `0013` applies cleanly
  to a `0009`-shaped legacy SQLite database and self-heals a pre-0013 row on
  next report (dedicated tests in `tests/unit/test_discovery_store.py`).
- The local dev `codex_bridge.db` (gitignored) needed `scripts/
  apply_migrations.py --mark-applied` for 0001–0009 (it was bootstrapped by
  `create_all`, never tracked in the ledger) and a real run of `0013` before
  `test_probes.py`'s real-app tests (which hit that file directly) went
  green — noted here in case another agent's session hits the same
  `SchemaOutOfDate` against the same file.

## NOT validated

No deploy, no real MySQL run of `0013` (only SQLite — same caveat `0009`'s own
RESUME already carried; a throwaway Postgres/MySQL verification is worth doing
before this ships to a MySQL-backed environment). No real node has adopted a
real discovered resource end-to-end through a live gateway. `POST .../adopt`
and `.../deny` carry no `revision`/`ETag` — reconsider if a future stage needs
optimistic concurrency on `discovered_resources` beyond the decidable-state
check already enforced.

## Watch for

Two subagents sharing one worktree caused a `git stash` incident on 2026-09-01
(`docs/napkin-lessons.md`). This session ran in its own dedicated worktree
with no sibling agent inside it — no repeat.
