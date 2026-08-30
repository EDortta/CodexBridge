-- WK-20260830-chatgpt-entry-provider-and-delivery
--
-- Adds the columns `start_development_task` (the new conversational MCP tool)
-- needs to record which agent CLI ran a task and whether it was authorized to
-- commit and push. Deliberately four columns on the existing `tasks` table,
-- not a new entity: council finding F01 already treats mission/session/
-- decision as the same `TaskModel` row, and adding an aggregate here would
-- hand issue #43 a second identity space to reconcile instead of one.
--
-- `engine` has a `not null default 'codex'` so every row written before this
-- migration reads back as what it always was: a `codex exec` task.
-- `issue_ref` and `delivery_json` record what was *requested*;
-- `delivery_result_json` records what *happened* — kept separate so "did it
-- push, what branch, what commit" is a column read, not a JSON parse of
-- `result_json`, and so `restart_finished_task` can clear the outcome
-- without touching the request.
--
-- Apply with `python3 scripts/apply_migrations.py`.
alter table tasks add column engine varchar(32) not null default 'codex';
alter table tasks add column issue_ref varchar(512);
alter table tasks add column delivery_json text;
alter table tasks add column delivery_result_json text;
