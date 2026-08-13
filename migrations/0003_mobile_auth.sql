-- WK-20260813-mobile-auth / issue #4
--
-- Session lifecycle for CodexBridgeMobile: a refresh token that can be rotated,
-- and revocation that actually takes effect on a token already issued.
--
-- Apply with `python3 scripts/apply_migrations.py`. Each file runs exactly once,
-- tracked in `schema_migrations`, which is why the ALTERs below carry no
-- `IF NOT EXISTS` guard: SQLite has no such form, and writing one makes the
-- whole script a syntax error on the default database.

-- Revocation. Until now an access token was valid until it expired and nothing
-- could take it back: `get_oauth_access_token` filtered on expiry alone, so a
-- lost device stayed authorized for the full TTL. Nullable and with no default,
-- so every token that already exists stays valid — a migration that revoked the
-- installed base would sign out ChatGPT and the operator at deploy time.
alter table oauth_access_tokens add column revoked_at timestamp with time zone;

-- The grant an access token belongs to: one sign-in, plus every refresh rotated
-- from it. Revoking a grant revokes the whole chain in one statement, which is
-- what "sign out this device" has to mean. Null for tokens issued by the
-- browser OAuth flow, which has no refresh chain to revoke.
alter table oauth_access_tokens add column grant_id varchar(128);

-- Refresh tokens.
--
-- Stored as a sha256 hash, like the access tokens and the authorization codes:
-- a database read must not hand back a usable credential.
--
-- `consumed_at` is what makes rotation detectable. A refresh token is single
-- use, so presenting a consumed one means either a replay or a stolen copy, and
-- the only safe reading is theft. That presentation revokes the whole grant
-- rather than being answered with a fresh pair.
--
-- This file once carried a note asking every future author to keep semicolons
-- out of prose, because the runner split on the statement separator before it
-- stripped comment lines. That rule now lives in the runner instead:
-- scripts/apply_migrations.py strips comments first, and
-- tests/unit/test_apply_migrations.py holds it there.
create table if not exists oauth_refresh_tokens (
  token_hash varchar(128) not null,
  grant_id varchar(128) not null,
  client_id varchar(255) not null,
  user_id varchar(255) not null,
  user_email varchar(255) not null,
  scopes_json text not null default '[]',
  expires_at timestamp with time zone not null,
  created_at timestamp with time zone not null,
  consumed_at timestamp with time zone,
  revoked_at timestamp with time zone,
  primary key (token_hash)
);

-- Revocation and rotation both look a grant up by id.
create index if not exists oauth_refresh_tokens_grant_id_idx
  on oauth_refresh_tokens (grant_id);

-- Revoking a grant also has to reach its access tokens.
create index if not exists oauth_access_tokens_grant_id_idx
  on oauth_access_tokens (grant_id);
