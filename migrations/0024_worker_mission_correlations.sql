-- Durable non-executing reservation. A reservation never starts a Task.
-- Existing worker_lease_serialization guard serializes competing reservations.
create table if not exists worker_mission_correlations (
  project_id varchar(128) not null,
  request_id varchar(128) not null,
  worker_id varchar(128) not null references worker_identities(id),
  payload_sha256 varchar(64) not null,
  source_commit varchar(40) not null,
  grant_id varchar(128) not null references worker_execution_grants(id),
  node_id varchar(128) not null references nodes(id),
  repository varchar(255) not null,
  mode varchar(32) not null,
  state varchar(32) not null,
  mission_id varchar(128) null references missions(id),
  task_id varchar(128) null references tasks(id),
  created_at timestamptz not null,
  primary key (project_id, request_id),
  foreign key (project_id, request_id) references worker_requests(project_id, request_id)
);
create unique index if not exists worker_mission_correlations_mission_unique
  on worker_mission_correlations (mission_id);
create unique index if not exists worker_mission_correlations_task_unique
  on worker_mission_correlations (task_id);
