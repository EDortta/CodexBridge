-- Centrally authorized Worker project activation windows.
-- Creating rows is NOT available to workers; a future operator-authenticated
-- action must authorize creation and enforce fleet-wide limits transactionally.
create table if not exists worker_project_leases (
  id varchar(128) primary key,
  worker_id varchar(128) not null references worker_identities(id),
  project_id varchar(128) not null,
  repository varchar(255) not null,
  control_branch varchar(128) not null,
  authorized_by varchar(255) not null,
  enabled_at timestamptz not null,
  expires_at timestamptz not null,
  revoked_at timestamptz null
);
create index if not exists worker_project_leases_lookup_idx
  on worker_project_leases (worker_id, project_id, expires_at);
