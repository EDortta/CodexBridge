-- WK-20260814-epics-issues-api / issue #8
--
-- Provider-neutral planning entities for CodexBridgeMobile: epics and issues,
-- owned by this gateway rather than mirrored from GitHub. `provider` on both
-- tables is the seam a future external sync would use ("local" is the only
-- value this build writes); it exists now so that seam does not require a
-- breaking schema change later.
--
-- Apply with `python3 scripts/apply_migrations.py`. Each file runs exactly
-- once, tracked in `schema_migrations`, which is why the statements below
-- carry no `IF NOT EXISTS` guard on anything but table/index creation: SQLite
-- has no such form for ALTER, and this file only ever creates tables here, so
-- that constraint does not bite.

create table if not exists epics (
  id varchar(128) primary key,
  project_id varchar(128) not null references projects(id),
  provider varchar(32) not null default 'local',
  external_id varchar(255) null,
  title varchar(255) not null,
  description text null,
  status varchar(32) not null,
  created_by_user_id varchar(255) not null,
  created_by_email varchar(255) null,
  updated_by_user_id varchar(255) null,
  updated_by_email varchar(255) null,
  created_at timestamptz not null,
  updated_at timestamptz not null,
  revision integer not null default 1
);

-- The list endpoint filters by project and orders newest first.
create index if not exists epics_project_id_created_at_idx
  on epics (project_id, created_at desc);

create table if not exists issues (
  id varchar(128) primary key,
  project_id varchar(128) not null references projects(id),
  epic_id varchar(128) null references epics(id),
  provider varchar(32) not null default 'local',
  external_id varchar(255) null,
  title varchar(255) not null,
  description text null,
  status varchar(32) not null,
  priority varchar(32) not null,
  labels_json text not null default '[]',
  assignee_user_id varchar(255) null,
  assignee_email varchar(255) null,
  dependencies_json text not null default '[]',
  blocked_reason text null,
  created_by_user_id varchar(255) not null,
  created_by_email varchar(255) null,
  updated_by_user_id varchar(255) null,
  updated_by_email varchar(255) null,
  created_at timestamptz not null,
  updated_at timestamptz not null,
  revision integer not null default 1
);

create index if not exists issues_project_id_created_at_idx
  on issues (project_id, created_at desc);

-- GET /api/v1/projects/{projectId}/issues filters by epic within a project.
create index if not exists issues_epic_id_idx
  on issues (epic_id);
