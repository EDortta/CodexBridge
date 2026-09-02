-- WK-20260901-control-plane-nodes-and-engines / issue #73, Stage 1
--
-- The domain the "CodexBridge Control" epic (#73) needs, added alongside the
-- existing entities rather than on top of them. Three of #73's rules decided
-- the shape here, and each one rules out the smaller change that would
-- otherwise have been tempting:
--
--   1. "A project MUST NOT be structurally owned by a node or by GitHub."
--      So the Project<->machine relation is its own table (`workspace_bindings`)
--      and the Project<->repository relation is another (`scm_associations`).
--      A column on `projects` would have made one node and one remote
--      structurally privileged, which is exactly what #73 forbids and what
--      makes "the same project on Frida and on T610 at different paths"
--      unrepresentable.
--
--   2. "Discovery is not authorization" / "a node cannot grant itself project
--      authorization merely by reporting a discovery." So what a node reports
--      lands in `discovered_resources`, and what it may DO lives in
--      `project_authorizations` — two tables, because they are written by two
--      different actors (the node announces; the operator, or a standing
--      root-config grant, authorizes) and confusing them is the whole failure
--      mode #73 names.
--
--   3. "Do not collapse these into a single `enabled` boolean." So
--      `discovered_resources.state` carries all five values from
--      `shared.protocol.DiscoveredState`, and `workspace_bindings.state`
--      tracks the observed world separately from the operator's decision.
--
-- `nodes` is seeded 1:1 from `executors` at the bottom of this file, so every
-- existing deployment comes up with its fleet already described and no
-- operator action. `executors` keeps its identity, its machine token and its
-- foreign key from `tasks` — #73 warns against "conflating node, executor,
-- engine and project into one entity", and renaming the executor into a node
-- would have done the conflation in the other direction.
--
-- NOT dropped here: `projects.path`. It stops being authoritative the moment
-- `workspace_bindings` is populated, but dropping it in the same migration
-- that creates its replacement would destroy the only copy of a path for any
-- project no longer present in `registry.json` — the backfill runs in
-- `store.upsert_registry` (which is where the executor/project association
-- actually lives, inside `executors.metadata_json`) and cannot be expressed
-- in portable SQL. Removal is a follow-up migration once bindings are
-- verified in production. Recorded here so nobody reads its survival as an
-- oversight.
--
-- Portability: `alter table ... add column` with a constant default, plain
-- `create table`/`create index`, and one `insert ... select` — all valid on
-- both SQLite and PostgreSQL. Style follows 0005/0008, not 0001 (which is
-- Postgres-only by accident).
--
-- Apply with `python3 scripts/apply_migrations.py`.

-- FIRST statement on purpose. `alter table` on a table that does not exist is
-- the most likely way this file meets a database it does not belong to, and
-- SQLite does not roll back DDL — so putting it first means such a failure
-- leaves the schema untouched instead of half-created. The runner's own
-- "PARTIALLY APPLIED" warning is the failure mode being avoided here.
--
-- One connection identity per node today, but the column is deliberately not
-- unique: #73's model must allow a node to run more than one executor process
-- later without a schema change.
alter table executors add column node_id varchar(128);

create index if not exists executors_node_id_idx on executors (node_id);

-- A registered CodexBridge installation. Identity is the operator-assigned
-- label, never a hostname or IP: #73 requires node identity to "survive
-- reconnects and must not be inferred from mutable hostname/IP alone".
create table if not exists nodes (
  id varchar(128) primary key,
  display_name varchar(255) not null,
  enabled boolean not null default true,
  -- Coarse platform facts only (`platform.system()`/`platform.machine()`).
  -- Never `platform.node()`: `docs/api/README.md`'s "fields that must never
  -- ship" excludes executor hostnames from every response.
  os varchar(64) null,
  arch varchar(64) null,
  agent_version varchar(64) null,
  -- Last announced engine capability set and when it was observed. Freshness
  -- is derived from the timestamp at read time (#42: "persist last-known
  -- capabilities with freshness timestamp"; "stale capability data is
  -- visibly marked"), never stored as a boolean that a restart would strand.
  capabilities_json text not null default '{}',
  capabilities_observed_at timestamptz null,
  inventory_observed_at timestamptz null,
  health_reason varchar(255) null,
  created_at timestamptz not null
);

-- A logical Project as it exists on one node's disk. This is the entity that
-- answers #73's "on which nodes can project X run right now?".
create table if not exists workspace_bindings (
  id varchar(128) primary key,
  node_id varchar(128) not null references nodes(id),
  project_id varchar(128) not null references projects(id),
  -- Sensitive operational data. #73: absolute paths "must only be returned to
  -- appropriately authorized operator surfaces; they must not leak through
  -- public/client contexts that do not need them." Exposed only by the
  -- admin-scoped node/binding endpoints; never by ProjectStatus, Session,
  -- Mission or any MCP tool.
  local_path varchar(2048) not null,
  head varchar(255) null,
  dirty boolean null,
  state varchar(32) not null default 'active',
  last_scan_at timestamptz null,
  created_at timestamptz not null,
  updated_at timestamptz not null
);

create unique index if not exists workspace_bindings_node_project_idx
  on workspace_bindings (node_id, project_id);
create index if not exists workspace_bindings_project_idx
  on workspace_bindings (project_id);

-- Project <-> source-control association. `provider` is the seam that keeps
-- #73's "the domain model must permit GitLab, other SCMs, and local-only
-- projects later" true without a breaking change; `confidence` exists because
-- #73 forbids inferring a trusted association from a coincidental name match,
-- so an unconfirmed guess has somewhere to live that is not "associated".
create table if not exists scm_associations (
  id varchar(128) primary key,
  project_id varchar(128) not null references projects(id),
  provider varchar(32) not null default 'github',
  remote_url varchar(2048) not null,
  repo_identity varchar(512) null,
  confidence varchar(32) not null default 'observed',
  created_at timestamptz not null,
  updated_at timestamptz not null
);

create unique index if not exists scm_associations_project_remote_idx
  on scm_associations (project_id, remote_url);

-- What a node may actually do to a project. Separate from the binding on
-- purpose: a binding says "this workspace exists here", an authorization says
-- "and this is what may be done to it". `granted_by` distinguishes a standing
-- grant from a discovery root (`root-config:<path>`, revoked by editing that
-- root) from an explicit operator decision (`operator:<user_id>`), which is
-- what makes the automatic half auditable rather than invisible.
create table if not exists project_authorizations (
  id varchar(128) primary key,
  node_id varchar(128) not null references nodes(id),
  project_id varchar(128) not null references projects(id),
  capabilities_json text not null default '[]',
  granted_by varchar(255) not null,
  granted_at timestamptz not null,
  revoked_at timestamptz null
);

create unique index if not exists project_authorizations_node_project_idx
  on project_authorizations (node_id, project_id);

-- Something a node can see that Control has not necessarily adopted. `kind`
-- is varchar rather than a two-value check because #73 explicitly leaves room
-- for "processes/services and other machine-local resources" beyond project
-- candidates.
create table if not exists discovered_resources (
  id varchar(128) primary key,
  node_id varchar(128) not null references nodes(id),
  kind varchar(32) not null default 'project',
  -- The node's own identifier for the candidate (a suggested project_id for a
  -- project candidate). Not a foreign key: a candidate exists precisely
  -- BEFORE there is a `projects` row to point at.
  resource_key varchar(255) not null,
  project_id varchar(128) null references projects(id),
  -- Evidence, not conclusion: path, HEAD, dirty flag, observed remote. What
  -- the node saw, so an operator can decide rather than be told.
  evidence_json text not null default '{}',
  state varchar(32) not null default 'discovered',
  root_path varchar(2048) null,
  first_seen_at timestamptz not null,
  last_seen_at timestamptz not null,
  decided_by varchar(255) null,
  decided_at timestamptz null
);

create unique index if not exists discovered_resources_node_kind_key_idx
  on discovered_resources (node_id, kind, resource_key);
create index if not exists discovered_resources_state_idx
  on discovered_resources (state);

-- Seed one node per existing executor, preserving the executor's own id as the
-- node id. Every deployment therefore boots with its fleet already described,
-- and `executors.node_id` is never null in practice after this migration even
-- though the column is nullable (nullable so this ALTER is portable; the
-- application treats a null node_id as "pre-#73 row" and repairs it at
-- startup).
insert into nodes (id, display_name, enabled, created_at)
select e.id, e.display_name, e.enabled, current_timestamp
from executors e
where not exists (select 1 from nodes n where n.id = e.id);

update executors set node_id = id where node_id is null;
