-- WK-20260821-gh-10-conversations / issue #10
--
-- Contextual conversations and messaging: threads linked to at least one
-- product entity (project, session/decision/mission, or issue — see
-- gateway/app/services/conversation_types.py for the closed vocabulary and
-- why `artifact` is not among them yet). `context_json` on `conversations`
-- is a JSON list, not a join table, for the same reason
-- `issues.dependencies_json` is: the scope here is "record and surface",
-- not a full graph API.
--
-- Apply with `python3 scripts/apply_migrations.py`. Each file runs exactly
-- once, tracked in `schema_migrations`; no `IF NOT EXISTS` guard is needed
-- on anything but table/index creation, since this file only creates tables.

create table if not exists conversations (
  id varchar(128) primary key,
  project_id varchar(128) not null references projects(id),
  title varchar(255) null,
  context_json text not null,
  created_by_user_id varchar(255) not null,
  created_by_email varchar(255) null,
  created_at timestamptz not null,
  -- Null until the first message. See ConversationModel's docstring for why
  -- there is no `revision`/`ETag` on this table: nothing here is ever
  -- PATCHed, so nothing here can go stale under a concurrent write.
  last_activity_at timestamptz null
);

-- The list endpoint filters by project and orders by creation, never by
-- last_activity_at — see routes/conversations.py's module docstring.
create index if not exists conversations_project_id_created_at_idx
  on conversations (project_id, created_at desc);

create table if not exists conversation_messages (
  id varchar(128) primary key,
  conversation_id varchar(128) not null references conversations(id),
  author_user_id varchar(255) not null,
  author_email varchar(255) null,
  body text not null,
  attachments_json text not null default '[]',
  created_at timestamptz not null
);

-- GET .../messages reads oldest-first, scoped to one conversation.
create index if not exists conversation_messages_conversation_id_created_at_idx
  on conversation_messages (conversation_id, created_at asc);

create table if not exists conversation_read_states (
  conversation_id varchar(128) not null references conversations(id),
  user_id varchar(255) not null,
  last_read_at timestamptz not null,
  primary key (conversation_id, user_id)
);
