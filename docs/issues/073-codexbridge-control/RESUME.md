# RESUME — WK-20260901-gh73-fleet-visibility (epic #73)

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

## Current state

- Stage 2 (fleet visibility) delivered on `feature/gh-73/fleet-visibility`:
  `NodeAnnouncement` on the `hello` message, `Runner.probe()` +
  `RunnerPool.probe_all()`, `store.record_node_announcement`, and
  `GET /api/v1/nodes` + `/{id}` with health derived by
  `shared.protocol.node_health`. No migration — Stage 1's columns sufficed.
- A **security fix** rode along: the websocket receive loop trusted
  `AgentEnvelope.executor_id` (client-written) instead of the id authenticated
  at the handshake, so a node could announce itself as another node or forge
  another node's liveness. Guard now sits once, before the dispatch.
- Stage 1 (domain and contracts) merged as `80e5d2f`: migration
  `0009_control_plane.sql`, entities, `schema_guard` entries, and the
  `Capability` vocabulary in `shared/protocol.py`, documented in
  `docs/control-plane.md`.
- Capability is **derived** from `TaskMode` (`CAPABILITY_MODES`), so
  `allowed_modes` stays the single enforcement point. `DiscoveryRoot`
  `auto_authorize` refuses `modify`/`deliver` at parse time.
- Stages 2–7 of the epic: not started.

## Changed files (13583f8)

`migrations/0009_control_plane.sql`, `gateway/app/models/entities.py`,
`gateway/app/db/schema_guard.py`, `shared/protocol.py`,
`docs/control-plane.md`, `docs/codemap.md`, `docs/required-reading.md`,
`tests/unit/test_apply_migrations.py`, `tests/unit/test_capability_vocabulary.py`.

## Checks

- `pytest -q` → **799 passed, 7 skipped** (Stage 2; branch baseline 757/7).
- The two identity-exploit tests were verified failing against the pre-fix
  source (vulnerable lines restored by file copy, not `git stash`).
- Stage 1: 757 passed, 7 skipped (baseline was 746/7).
- `0009` applied against SQLite **and** a real PostgreSQL 16 (throwaway
  container, removed afterwards; no other project's Postgres touched).
- Three mutations proved the tests bite: widening `Capability.READ` to include
  `edit`; widening `AUTO_AUTHORIZABLE_CAPABILITIES` to include `modify`;
  reversing the migration's statement order.
- Codemap regeneration command is `governancekit --root . map`.

## Decisions carried forward

1. `projects.path` was **kept**, against the plan: dropping it in the same
   migration that creates the replacement destroys the only copy of the path
   for any project absent from today's `registry.json`; the backfill depends
   on `executors.metadata_json` and is not expressible in portable SQL. The
   reason is written into the migration file.
2. `alter table executors` runs first in `0009` — SQLite does not roll back
   DDL, so hitting a wrong database leaves the schema intact, not half-built.
3. The migration grants nothing: `project_authorizations` is born empty, even
   for projects the node already ran.

## NOT validated

No deploy. `0009` never applied to any real gateway database. No real agent has
connected to a real gateway with the Stage 2 build. `inventoryObservedAt` is
exposed but reserved for Stage 3 and stays `null`. `GET /api/v1/nodes` is
unpaginated. Contract is at 1.9.0 and collides by design with PRs #61/#62.

## Watch for

Stage 2 was implemented by two subagents sharing ONE worktree; one ran `git
stash` and transiently reverted the other's uncommitted work. Give each agent
its own worktree, or forbid repository-wide git commands in the prompt — see
`docs/napkin-lessons.md`, 2026-09-01.
