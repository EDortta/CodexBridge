-- WK-20260902-issue-materialize / issue #78, Commit 1 of 2
--
-- Today an epic/issue planned in ChatGPT (over the MCP tools A1/A2 added)
-- lives only as `EpicModel`/`IssueModel` rows in this gateway's own database.
-- The operator's actual deliverable -- a versioned markdown file under the
-- PROJECT's own `docs/issues/` -- is a second, disconnected concept: the
-- executor already resolves `docs:NNN`/bare-`NNN` issue references by
-- globbing that directory (`agent/codex_bridge_agent/instructions.py`), but
-- nothing writes to it. This migration adds the two columns that let the
-- gateway remember, for a row it owns, what got published and how stale that
-- publication might be -- nothing about writing the file itself, which is
-- Commit 2 of this same work_id.
--
-- `materialized_path` is the file/folder path the EXECUTOR reported after
-- writing it (relative to the project root), never a path the gateway
-- invents: the gateway does not know a project's real filesystem layout
-- (`docs/architecture.md`), and this column is deliberately no exception.
--
-- `materialized_revision` is a copy of the row's own `revision` column AS OF
-- the moment it was published -- not a git commit count, not the CURRENT
-- `revision`. Comparing the two at read time is what lets an operator tell
-- "drafted, never published" (`materialized_path IS NULL`) apart from
-- "published, N edits ago" (`revision - materialized_revision = N`) without
-- this migration inventing a third, redundant timestamp.
--
-- Deliberately NOT `provider`/`external_id`: those two columns are the seam
-- another track of this same orchestration is building a forge (GitHub)
-- integration on top of. Overloading them for "written to this repo's own
-- working tree" would make a populated `external_id` ambiguous between "this
-- mirrors a GitHub issue" and "this was materialized as a local file" --
-- exactly the kind of conflation `docs/control-plane.md` warns against for
-- the node/project/authorization split, one layer up.
--
-- Portability: plain `alter table ... add column`, no default expression
-- needed (both columns are nullable, absent = "never published"). Style
-- follows 0009 (comment explaining why each column exists, ALTER statements
-- first because SQLite does not roll back DDL on a later failure).
--
-- Apply with `python3 scripts/apply_migrations.py`.

alter table epics add column materialized_path varchar(1024);
alter table epics add column materialized_revision integer;

alter table issues add column materialized_path varchar(1024);
alter table issues add column materialized_revision integer;
