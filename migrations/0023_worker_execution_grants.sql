-- Separate, operator-issued execution permission; intake leases never grant execution.
-- Serialized by the existing worker_lease_serialization row.
create table if not exists worker_execution_grants (
  id varchar(128) primary key,
  worker_id varchar(128) not null references worker_identities(id),
  project_id varchar(128) not null references projects(id),
  node_id varchar(128) not null references nodes(id),
  repository varchar(255) not null,
  modes_json text not null,
  authorized_by varchar(255) not null,
  enabled_at timestamptz not null,
  expires_at timestamptz not null,
  revoked_at timestamptz null
);
create index if not exists worker_execution_grants_scope_idx
  on worker_execution_grants (worker_id, project_id, node_id);
