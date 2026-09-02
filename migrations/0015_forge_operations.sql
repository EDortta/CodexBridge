-- WK-20260902-forge-wiring-and-gate / issue #80, #79 (PR B3)
--
-- Persistence for one forge operation (open/comment/close/list an issue on
-- GitHub via `gh`) and the human approval gate a forge WRITE must clear
-- before it is ever dispatched to an executor. `0010`/`0011` are reserved for
-- other tracks of this orchestration -- this migration is `0012` by explicit
-- instruction, not the next free number.
--
-- `forge_operations` is deliberately its OWN table, not a column added to
-- `tasks`. See `gateway/app/models/entities.py::ForgeOperationModel`'s own
-- docstring for the full reasoning; the short version is that `tasks`'
-- columns (`mode`, `instruction`, `engine`, `timeout_seconds`, `session_id`,
-- `delivery_json`) all encode a coding-agent session, which a forge
-- operation is not, and `shared.policy.forge_operation_policy_level` is
-- explicit that a forge write's SENSITIVE classification has no bypass
-- field the way `tasks.delivery_json`'s push pre-authorization does --
-- forcing the two into one table would need one of them to grow an escape
-- hatch that must never exist.
--
-- Portability: plain `create table`/`create index`, `varchar`, `text`,
-- `timestamptz`, no `alter table` on an existing table -- follows 0009's
-- own style (itself following 0005/0008), valid on SQLite and PostgreSQL.
--
-- Apply with `python3 scripts/apply_migrations.py`.

create table if not exists forge_operations (
  id varchar(128) primary key,
  project_id varchar(128) not null references projects(id),
  executor_id varchar(128) not null references executors(id),
  -- `shared.protocol.ForgeOperationKind` value: issue_open/issue_comment/
  -- issue_list/issue_close. Not a foreign key or a check constraint --
  -- the enum is the single source of truth (shared/protocol.py), the same
  -- posture `tasks.mode`/`tasks.engine` already take toward their own enums.
  kind varchar(32) not null,
  repo_identity varchar(200) not null,
  -- The full `ForgeOperationRequest`, serialized -- title/body/issue_number/
  -- state live here rather than as their own nullable columns, the same
  -- choice `tasks.delivery_json` already makes for `DeliveryRequest`.
  payload_json text not null default '{}',
  -- awaiting_approval | approved | dispatched | completed | failed |
  -- rejected | revision_requested. See ForgeOperationModel's docstring for
  -- the full lifecycle; not a check constraint for the same reason `tasks.state`
  -- has none -- `shared/protocol.py`/application code is the source of truth.
  state varchar(32) not null,
  -- `ForgeOutcome.to_dict()`, once a FORGE_OPERATION_RESULT resolves this row.
  result_json text null,
  requested_by_user_id varchar(255) null,
  requested_by_email varchar(255) null,
  approval_reason text null,
  created_at timestamptz not null,
  resolved_at timestamptz null
);

create index if not exists forge_operations_project_idx on forge_operations (project_id);
create index if not exists forge_operations_executor_idx on forge_operations (executor_id);
create index if not exists forge_operations_state_idx on forge_operations (state);
