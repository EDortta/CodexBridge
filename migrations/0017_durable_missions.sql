-- Issue #43 — durable Mission aggregate.
--
-- Mission is operator intent and is distinct from TaskModel execution attempts.
-- This migration upgrades an existing pre-Mission database; fresh databases get
-- the same shape from SQLAlchemy metadata.
--
-- Portability: uses plain CREATE TABLE / CREATE INDEX / ALTER TABLE ADD COLUMN
-- and INSERT ... SELECT forms supported by both SQLite and PostgreSQL.
-- Apply with `python3 scripts/apply_migrations.py`.

create table missions (
  id varchar(128) primary key,
  project_id varchar(128) not null references projects(id),
  objective text not null,
  source_ref varchar(512) null,
  requested_mode varchar(64) not null,
  requested_policy varchar(32) null,
  selected_node_id varchar(128) null references nodes(id),
  selected_executor_id varchar(128) null references executors(id),
  selected_engine varchar(32) null,
  state varchar(64) not null,
  priority varchar(32) not null,
  run_when_available boolean not null default true,
  expires_at timestamptz null,
  timeout_seconds integer null,
  delivery_json text null,
  final_outcome varchar(64) null,
  active_task_id varchar(128) null references tasks(id),
  created_at timestamptz not null,
  updated_at timestamptz not null,
  started_at timestamptz null,
  completed_at timestamptz null,
  requested_by_user_id varchar(255) null,
  requested_by_email varchar(255) null,
  last_error text null,
  revision integer not null default 1
);

-- The referenced table now exists, so both SQLite and PostgreSQL can preserve
-- the Task -> Mission relationship while keeping TaskModel as attempt machinery.
alter table tasks add column mission_id varchar(128) references missions(id);

create table mission_attempts (
  id varchar(128) primary key,
  mission_id varchar(128) not null references missions(id),
  task_id varchar(128) not null references tasks(id),
  attempt_number integer not null,
  reason varchar(64) null,
  created_at timestamptz not null,
  completed_at timestamptz null,
  outcome varchar(64) null
);

create table mission_events (
  id varchar(128) primary key,
  mission_id varchar(128) not null references missions(id),
  event_type varchar(128) not null,
  state varchar(64) null,
  task_id varchar(128) null references tasks(id),
  actor_id varchar(255) null,
  payload_json text not null default '{}',
  created_at timestamptz not null
);

create index missions_project_created_idx on missions (project_id, created_at);
create index missions_state_idx on missions (state);
create index missions_active_task_idx on missions (active_task_id);
create index tasks_mission_id_idx on tasks (mission_id);
create unique index mission_attempts_mission_number_idx on mission_attempts (mission_id, attempt_number);
create unique index mission_attempts_task_idx on mission_attempts (task_id);
create index mission_events_mission_created_idx on mission_events (mission_id, created_at, id);

-- Backfill every existing task into a one-attempt Mission. Existing task ids
-- become Mission ids deliberately: this preserves the old public Mission URL/id
-- for deployments where Mission used to be a TaskModel view.
insert into missions (
  id, project_id, objective, source_ref, requested_mode, requested_policy,
  selected_node_id, selected_executor_id, selected_engine, state, priority,
  run_when_available, expires_at, timeout_seconds, delivery_json, final_outcome,
  active_task_id, created_at, updated_at, started_at, completed_at,
  requested_by_user_id, requested_by_email, last_error, revision
)
select
  t.id,
  t.project_id,
  t.instruction,
  t.issue_ref,
  t.mode,
  t.policy_level,
  e.node_id,
  t.executor_id,
  t.engine,
  case t.state
    when 'queued' then 'queued'
    when 'waiting_executor' then 'waiting_executor'
    when 'running' then 'running'
    when 'awaiting_approval' then 'waiting_human'
    when 'pausing' then 'paused'
    when 'paused' then 'paused'
    when 'resuming' then 'paused'
    when 'restarting' then 'paused'
    when 'completed' then 'completed'
    when 'failed' then 'failed'
    when 'cancelled' then 'cancelled'
    when 'expired' then 'expired'
    when 'lost' then 'lost'
    else 'blocked'
  end,
  t.priority,
  t.run_when_available,
  t.expires_at,
  t.timeout_seconds,
  t.delivery_json,
  case
    when t.state = 'completed' then 'completed'
    when t.state in ('failed', 'expired', 'lost') then t.state
    when t.state = 'cancelled' then 'cancelled'
    else null
  end,
  t.id,
  t.created_at,
  coalesce(t.completed_at, t.started_at, t.created_at),
  t.started_at,
  t.completed_at,
  t.requested_by_user_id,
  t.requested_by_email,
  t.last_error,
  t.revision
from tasks t
left join executors e on e.id = t.executor_id;

update tasks set mission_id = id where mission_id is null;

insert into mission_attempts (
  id, mission_id, task_id, attempt_number, reason, created_at, completed_at, outcome
)
select
  'backfill-01-attempt-' || t.id,
  t.id,
  t.id,
  1,
  'backfill',
  t.created_at,
  t.completed_at,
  case
    when t.state = 'completed' then 'completed'
    when t.state in ('failed', 'expired', 'lost') then t.state
    when t.state = 'cancelled' then 'cancelled'
    else null
  end
from tasks t;

-- Two deterministic events preserve append-only history and deterministic
-- ordering when timestamps are equal. The numeric id prefix makes
-- mission.created sort before mission.attempt_created in both databases.
insert into mission_events (
  id, mission_id, event_type, state, task_id, actor_id, payload_json, created_at
)
select
  'backfill-01-created-' || t.id,
  t.id,
  'mission.created',
  case t.state
    when 'queued' then 'queued'
    when 'waiting_executor' then 'waiting_executor'
    when 'running' then 'running'
    when 'awaiting_approval' then 'waiting_human'
    when 'pausing' then 'paused'
    when 'paused' then 'paused'
    when 'resuming' then 'paused'
    when 'restarting' then 'paused'
    when 'completed' then 'completed'
    when 'failed' then 'failed'
    when 'cancelled' then 'cancelled'
    when 'expired' then 'expired'
    when 'lost' then 'lost'
    else 'blocked'
  end,
  t.id,
  t.requested_by_user_id,
  '{}',
  t.created_at
from tasks t;

insert into mission_events (
  id, mission_id, event_type, state, task_id, actor_id, payload_json, created_at
)
select
  'backfill-02-attempt-' || t.id,
  t.id,
  'mission.attempt_created',
  case t.state
    when 'queued' then 'queued'
    when 'waiting_executor' then 'waiting_executor'
    when 'running' then 'running'
    when 'awaiting_approval' then 'waiting_human'
    when 'pausing' then 'paused'
    when 'paused' then 'paused'
    when 'resuming' then 'paused'
    when 'restarting' then 'paused'
    when 'completed' then 'completed'
    when 'failed' then 'failed'
    when 'cancelled' then 'cancelled'
    when 'expired' then 'expired'
    when 'lost' then 'lost'
    else 'blocked'
  end,
  t.id,
  t.requested_by_user_id,
  '{}',
  t.created_at
from tasks t;
