-- WK-20260810-api-foundation / issue #12
--
-- Cross-cutting persistence for the mobile API: a monotonic revision to compare
-- against for optimistic concurrency, and a record of completed writes so an
-- offline retry replays instead of repeating.
--
-- Apply with `python3 scripts/apply_migrations.py`. Each file runs exactly once,
-- tracked in `schema_migrations`, which is why the statements below carry no
-- `IF NOT EXISTS` guard on the ALTER: SQLite has no such form, and writing one
-- made this whole script a syntax error on the default database.

-- Optimistic concurrency. The existing timestamps cannot serve as validators:
-- none of started_at/completed_at moves when approval_state, approval_reason or
-- last_error changes, so an ETag derived from them would match on both sides of
-- a concurrent approval and every stale write would be accepted.
--
-- Portable across SQLite and Postgres: single ADD COLUMN, literal default, no
-- IF NOT EXISTS.
alter table tasks add column revision integer not null default 1;

-- Idempotent replay of write commands.
--
-- The primary key is (key, endpoint, actor_id), not key alone: the same
-- Idempotency-Key from a different actor, or aimed at a different endpoint, is a
-- different operation. Collapsing them would let one client's retry return
-- another client's response.
create table if not exists idempotency_records (
  key varchar(255) not null,
  endpoint varchar(255) not null,
  actor_id varchar(255) not null,
  request_fingerprint varchar(64) not null,
  status_code integer not null,
  response_json text not null,
  created_at timestamp with time zone not null,
  expires_at timestamp with time zone not null,
  primary key (key, endpoint, actor_id)
);

-- `purge_expired` scans by expires_at.
create index if not exists idempotency_records_expires_at_idx
  on idempotency_records (expires_at);
