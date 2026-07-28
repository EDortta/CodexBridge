create table if not exists executors (
  id varchar(128) primary key,
  display_name varchar(255) not null,
  enabled boolean not null default true,
  last_seen_at timestamptz null,
  connected boolean not null default false,
  metadata_json text not null default '{}'
);

create table if not exists projects (
  id varchar(128) primary key,
  name varchar(255) not null,
  path varchar(2048) not null,
  enabled boolean not null default true,
  config_json text not null default '{}'
);

create table if not exists tasks (
  id varchar(128) primary key,
  executor_id varchar(128) not null references executors(id),
  project_id varchar(128) not null references projects(id),
  instruction text not null,
  mode varchar(64) not null,
  state varchar(64) not null,
  priority varchar(32) not null,
  run_when_available boolean not null default false,
  expires_at timestamptz not null,
  timeout_seconds integer not null,
  created_at timestamptz not null,
  requested_by_user_id varchar(255) null,
  requested_by_email varchar(255) null,
  started_at timestamptz null,
  completed_at timestamptz null,
  correlation_id varchar(128) not null,
  last_error text null,
  command_json text null,
  session_id varchar(255) null,
  result_json text null
);

create table if not exists task_logs (
  id integer primary key generated always as identity,
  task_id varchar(128) not null references tasks(id),
  offset integer not null,
  stream varchar(16) not null,
  line text not null,
  created_at timestamptz not null
);

create table if not exists audit_events (
  id integer primary key generated always as identity,
  entity_type varchar(64) not null,
  entity_id varchar(128) not null,
  event_type varchar(128) not null,
  payload_json text not null,
  created_at timestamptz not null
);

create table if not exists message_receipts (
  message_id varchar(128) primary key,
  executor_id varchar(128) not null,
  message_type varchar(128) not null,
  created_at timestamptz not null
);

create table if not exists oauth_authorization_codes (
  code_hash varchar(128) primary key,
  client_id varchar(255) not null,
  redirect_uri varchar(2048) not null,
  user_id varchar(255) not null,
  user_email varchar(255) not null,
  scopes_json text not null default '[]',
  code_challenge varchar(255) not null,
  code_challenge_method varchar(32) not null default 'S256',
  expires_at timestamptz not null,
  consumed_at timestamptz null,
  created_at timestamptz not null
);

create table if not exists oauth_access_tokens (
  token_hash varchar(128) primary key,
  client_id varchar(255) not null,
  user_id varchar(255) not null,
  user_email varchar(255) not null,
  scopes_json text not null default '[]',
  expires_at timestamptz not null,
  created_at timestamptz not null
);
