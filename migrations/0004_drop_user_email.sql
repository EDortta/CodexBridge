-- WK-20260813-mobile-auth / issue #4, council round 2
--
-- Remove the operator's e-mail from the three credential tables.
--
-- `security-standards.md` §2 names e-mail among the fields that are never
-- logged or stored, and adds that PII is never stored plaintext in a synced
-- directory. The default `CODEX_BRIDGE_DATABASE_URL` is
-- `sqlite+aiosqlite:///./codex_bridge.db`, a file inside the checkout, and this
-- checkout lives under `~/Sync`. `oauth_refresh_tokens` is a table issue #4
-- itself created, so the field was being newly written, not inherited.
--
-- Nothing is lost. Every row already carries `user_id`, which is the key
-- `users.json` is indexed by and the one the code looked up first; the e-mail
-- was a second, personal copy of an identifier the row already had, and its
-- only reader was a fallback lookup that could never fire for a row this
-- gateway wrote.
--
-- Apply with `python3 scripts/apply_migrations.py`. This one runs against a
-- database the previous migration already touched, so it is the case
-- `gateway/app/db/schema_guard.py` refuses to start on when it has not run:
-- the columns are `not null` with no default, and the code no longer supplies
-- them, so the first sign-in against an unmigrated database would fail on an
-- integrity error rather than at boot.
--
-- SQLite has supported `alter table ... drop column` since 3.35 (2021-03);
-- this project's floor is 3.37. None of these columns is indexed, which is the
-- other condition SQLite places on the statement.

alter table oauth_authorization_codes drop column user_email;

alter table oauth_access_tokens drop column user_email;

alter table oauth_refresh_tokens drop column user_email;
