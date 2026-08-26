-- WK-20260826-gh13-events / issue #13
--
-- Notification-subscription preferences for CodexBridgeMobile.
--
-- Issue #13's event stream itself adds NO schema: `audit_events` is already
-- this gateway's durable event log, its autoincrement `id` is already the
-- resume cursor, and the four entity tables already carry the `project_id`
-- authorization needs (see gateway/app/services/store.py:_event_project_expression).
-- Adding a projection table would have meant a backfill of every historical row
-- and two answers to "which project is this event in", one of which can go
-- stale. This file therefore creates one table, and it is the preferences one.
--
-- Numbered 0009 with no 0008 in this branch on purpose: 0008 belongs to the
-- artifacts work developed in parallel (issue #11). `scripts/apply_migrations.py`
-- applies files in filename order and records each one in `schema_migrations`
-- independently, so a gap costs nothing and re-numbering after the fact would
-- rename a file an already-migrated database has recorded as applied.
--
-- Apply with `python3 scripts/apply_migrations.py`. Each file runs exactly once.

create table if not exists notification_preferences (
  -- The `user_id` from users.json, never an email: an audit/preference table
  -- keyed by a personal identifier is a personal-data store with a different
  -- retention question attached (docs/api/README.md, security-standards.md §2).
  user_id varchar(255) primary key,
  -- JSON list of MobileEventType values, validated against the closed
  -- vocabulary in gateway/app/services/event_types.py before it is written.
  event_types_json text not null default '[]',
  -- Recorded intent only. This build has no push transport, and nothing reads
  -- this column to decide delivery. The client is told so by
  -- `pushDeliveryAvailable` in the preferences response body; `GET /api/version`
  -- has no push capability flag. See gateway/app/api/routes/notifications.py.
  push_enabled boolean not null default false,
  updated_at timestamptz not null
);

-- Issue #13 is what turns `audit_events` into a read path for the first time.
-- Until now it was written and never queried except by
-- `purge_expired_audit_events`, so the primary key was the only index it
-- needed. Both event endpoints run `entity_type in (...) and event_type in
-- (...) and id > $cursor order by id limit n`, once per poll of every open
-- stream, and the tail read (`id > cursor` near the head) is the overwhelmingly
-- common shape.
--
-- Leading on `entity_type` and then `id` serves exactly that: the deliverable
-- entity types are four of the six values the column holds, and within each the
-- rows are already ordered by the cursor. `event_type` is deliberately not in
-- the index — it would triple its width to filter a set the entity type has
-- already narrowed to something small.
--
-- Built without `concurrently`. `scripts/apply_migrations.py` runs each file in
-- a transaction and `create index concurrently` cannot run inside one; this
-- deployment's `audit_events` is small enough that the write lock is measured in
-- milliseconds. An operator whose table has grown large should build this index
-- by hand with `concurrently` before applying the file, which then no-ops on the
-- `if not exists`.
create index if not exists audit_events_entity_type_id_idx
  on audit_events (entity_type, id);
