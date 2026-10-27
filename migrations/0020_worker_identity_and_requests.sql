-- Worker transport identity and durable request admission foundation.
-- No endpoint or dispatch is enabled by this migration.
-- A Worker is not an Executor. Credentials are hashed and scoped to a
-- gateway-managed logical worker identity.
create table if not exists worker_identities (
  id varchar(128) primary key,
  token_hash varchar(128) not null unique,
  enabled boolean not null default false,
  created_at timestamptz not null,
  revoked_at timestamptz null
);

-- A request ID is unique PER project, not globally. Fingerprints protect
-- against replay of the same name with a different payload.
create table if not exists worker_requests (
  project_id varchar(128) not null,
  request_id varchar(128) not null,
  worker_id varchar(128) not null references worker_identities(id),
  payload_sha256 varchar(64) not null,
  source_commit varchar(40) not null,
  operation varchar(32) not null,
  state varchar(32) not null,
  received_at timestamptz not null,
  primary key (project_id, request_id)
);
create index if not exists worker_requests_worker_idx
  on worker_requests (worker_id, received_at);
