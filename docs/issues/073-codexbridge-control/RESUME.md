# RESUME — WK-20260901-gh73-control-plane-domain (epic #73)

- work_id: WK-20260901-gh73-control-plane-domain
- data: 2026-09-01
- branch: `feature/gh-73/control-plane-domain` (commit `13583f8`), worktree
  `../CodexBridge--gh-73-control`. Pushed; **PR #74** open against
  `development`. NOT merged.

## Next Step (DO THIS FIRST)

Start Stage 2 (fleet visibility: node discovery, `Runner.probe()`, gateway
handshake, `/nodes` routes) on a branch cut from
`feature/gh-73/control-plane-domain` — do not wait for PR #74 to merge, but
rebase Stage 2 if review changes the Stage 1 schema.

## Current state

- Stage 1 (domain and contracts) delivered on the branch: migration
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

- `pytest -q` → 757 passed, 7 skipped (branch baseline was 746/7).
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

No deploy. `0009` never applied to any real gateway database. No gateway/agent
runtime code consumes the new tables yet. PR #74 not reviewed.
