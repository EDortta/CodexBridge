-- WK-20260902-gh76-enrollment-minimal / issue #76 (minimal cut), boundary with #73
--
-- What #76 names as the actual defect: admitting a machine today means
-- hand-editing `registry.json`, inventing a token in clear text, and
-- restarting the gateway; `/agent/ws` closes `4404` for anyone not in that
-- file; "revoking" access means deleting the line and restarting, while a
-- socket that is already open keeps working regardless. Three separate
-- promises that were never actually kept by the file alone: a real secret, a
-- controllable admission, and a revocation that revokes something. This
-- migration adds the columns and the table that make the three real; the API
-- that writes them lands in `gateway/app/api/routes/enrollment.py`,
-- `gateway/app/services/store.py` and `gateway/app/services/agent_hub.py`.
--
--   1. `executors.machine_token_hash` -- the credential stops living as clear
--      text in `executors.metadata_json` (which is what `registry.json`
--      seeds it as today, and what `POST /api/v1/nodes/enroll` never will).
--      `/agent/ws` compares `shared.security.hash_token(presented)` against
--      this column instead of a clear-text value pulled out of the JSON blob
--      -- the same `hash_token`/`secure_compare` pair every OAuth token in
--      this schema already uses (`oauth_access_tokens.token_hash`,
--      `oauth_refresh_tokens.token_hash`). A `registry.json`-seeded executor
--      has no value here until the application backfills it from its own
--      `metadata_json` at startup (`store.upsert_registry`) -- see that
--      function for why the column is nullable rather than backfilled here in
--      SQL: the source value is inside a JSON text column, not expressible as
--      a portable `update ... set`.
--
--   2. `nodes.admission_state` -- today `NodeModel`/`ExecutorModel` carry only
--      `enabled`, a single boolean with no room to say WHY a node cannot be
--      dispatched to: disabled by an operator's ordinary toggle, or revoked
--      because its credential must never work again. `admission_state` is the
--      distinction; `enabled` keeps meaning what it always meant (may this
--      node be given work right now) and stays flipped alongside a revoke as
--      a matter of course, not as the enforcement mechanism itself --
--      `/agent/ws` gates the handshake on `admission_state == 'revoked'`
--      specifically, so this cut touches no other executor's behaviour.
--      `'invited'`/`'suspended'` are states issue #76 anticipates and this cut
--      does not use; only `'enrolled'` and `'revoked'` are written today.
--      Backfilled to `'enrolled'` for every row that exists already -- an
--      operator who admitted a machine by hand before this migration ran did
--      exactly what this migration now calls "enrolled", and nothing about
--      that machine's standing changes underneath it.
--
--   3. `node_invites` -- what makes admission an API call instead of a file
--      edit plus a restart. Bearer, one-time, short TTL (15 minutes, enforced
--      by the application, not by this schema): decision was to protect the
--      invite with its lifetime, not by binding it to a claimed hostname,
--      because a hostname is exactly the "mutable, spoofable" identity
--      `migrations/0009_control_plane.sql` already refused to trust for node
--      identity. Only `token_hash` is ever stored -- the raw value is
--      returned once, in the HTTP response body, and is never written to
--      `audit_events` or to any log. `consumed_by_node_id` is nullable and
--      set only once `POST /api/v1/nodes/enroll` has actually created the
--      node the invite authorized; it is not a foreign key ON DELETE target
--      the invite depends on, so it stays null for every invite nobody ever
--      redeemed.
--
-- Portability: `alter table ... add column` with a constant default, plain
-- `create table`/`create index` -- same subset 0009 restricted itself to, and
-- for the same reason (valid on both SQLite and PostgreSQL).
--
-- Apply with `python3 scripts/apply_migrations.py`.

-- FIRST statement on purpose, same reasoning as 0009's opening comment:
-- `alter table` on a table this file does not belong to is the most likely
-- way it meets the wrong database, and SQLite does not roll back DDL, so
-- putting the riskiest statement first leaves the schema untouched if it is
-- wrong instead of half-migrated.
alter table executors add column machine_token_hash varchar(128);

create index if not exists executors_machine_token_hash_idx
  on executors (machine_token_hash);

-- Constant default, so this single statement both defines the column for
-- every row inserted from here on AND backfills every row that already
-- exists -- unlike `executors.node_id` in 0009, whose backfill value (`=
-- id`) could not be expressed as a static `default` clause and needed a
-- separate `update`. Both are "no operator action required"; only the
-- mechanism differs, because the value being backfilled here is a constant.
alter table nodes add column admission_state varchar(32) not null default 'enrolled';

-- An issued, not-yet-redeemed (or already-redeemed, or expired) enrollment
-- invite. `id` is a separate surrogate key from `token_hash` on purpose,
-- unlike `oauth_access_tokens`/`oauth_refresh_tokens` (where the hash IS the
-- primary key): an invite is looked up by id from the operator surface that
-- issued it (list/audit) as often as it is looked up by the token a would-be
-- node presents, and those are two different callers with two different keys
-- available to them.
create table if not exists node_invites (
  id varchar(128) primary key,
  token_hash varchar(128) not null,
  created_by varchar(255) not null,
  created_at timestamptz not null,
  expires_at timestamptz not null,
  consumed_at timestamptz null,
  consumed_by_node_id varchar(128) null references nodes(id),
  display_name_hint varchar(255) null
);

-- Enforced uniqueness, not just an index for speed: a `token_hash` collision
-- (practically a SHA-256 collision) must fail loudly at the database rather
-- than let `POST /api/v1/nodes/enroll` match the wrong invite.
create unique index if not exists node_invites_token_hash_idx
  on node_invites (token_hash);
