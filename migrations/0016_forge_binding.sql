-- WK-20260902-forge-binding, issue #79/#80 (PR B4)
--
-- Two independent additions, one migration because both are small and both
-- belong to the same feature (a project's forge binding, and the Decision
-- Center learning to project forge_operations alongside tasks).
--
-- 1. forge_operations.revision -- ForgeOperationModel had no equivalent of
--    TaskModel.revision (migrations/0002_api_foundation.sql) when
--    0015_forge_operations.sql shipped, because nothing outside
--    tests/integration/test_forge_wiring.py read a forge operation through
--    an API that needed optimistic concurrency. `/api/v1/decisions` now
--    projects forge_operations rows too (gateway/app/api/routes/
--    decisions.py), and that endpoint's ETag/If-Match contract
--    (docs/api/README.md) needs the same monotonic counter tasks already
--    have -- so this is the same column, same default, same "bumped by
--    every mutator" contract, just added a migration late because the need
--    arrived late. See ForgeOperationModel's own docstring for why it does
--    not simply reuse TaskModel's row.
--
-- 2. scm_associations(project_id, provider) unique index -- issue #73 (via
--    0009_control_plane.sql) modeled a project's relationship to a
--    repository as an association, not an attribute, and the table shipped
--    with a unique index on (project_id, remote_url) but not on
--    (project_id, provider). gateway/app/services/forge_routing.py's
--    project_forge_binding needs exactly ONE row to answer "what is this
--    project bound to" for a given provider; without this index, a second
--    registration call (gateway/app/mcp/server.py's bind_project_forge
--    tool) could silently create a second row for the same project instead
--    of updating the declared one, and project_forge_binding would then
--    have to guess which one is current. The table is empty in every
--    existing deployment (control-plane.md: "vazia e sem código até hoje"),
--    so adding this index needs no data cleanup first.
--
-- Apply with `python3 scripts/apply_migrations.py`.

alter table forge_operations add column revision integer not null default 1;

create unique index if not exists scm_associations_project_provider_idx
  on scm_associations (project_id, provider);
