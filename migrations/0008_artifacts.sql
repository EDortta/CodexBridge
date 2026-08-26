-- WK-20260826-gh11-artifacts / issue #11
--
-- The artifact catalogue, its Android build metadata, and the short-lived
-- bearer credentials that authorize a download.
--
-- `artifacts.storage_path` is an internal field: a path relative to
-- `CODEX_BRIDGE_ARTIFACTS_ROOT`, never serialized into any response
-- (docs/api/README.md, "Fields that must never ship"). Only
-- gateway/app/services/artifact_storage.py turns it into a real file, and that
-- module is what confines it to the root.
--
-- `android_builds` is keyed by `artifact_id` rather than by an id of its own:
-- an Android build is an artifact plus this metadata, so a second identifier
-- would give the mobile client two ids for one thing. GET
-- /api/v1/builds/android/{buildId} therefore takes the artifact's id.
--
-- `artifact_download_tokens` stores a SHA-256 of the token, never the token —
-- the same treatment oauth_access_tokens gets, for the same reason: whoever
-- reads this table must not be able to download anything with what they find.
--
-- Apply with `python3 scripts/apply_migrations.py`. Each file runs exactly
-- once, tracked in `schema_migrations`.

create table if not exists artifacts (
  id varchar(128) primary key,
  project_id varchar(128) not null references projects(id),
  type varchar(32) not null,
  name varchar(255) not null,
  version varchar(64) null,
  size_bytes integer not null,
  sha256 varchar(64) not null,
  origin varchar(32) not null,
  content_type varchar(255) not null default 'application/octet-stream',
  storage_path varchar(512) not null,
  created_at timestamptz not null,
  -- Past this instant the gateway refuses to mint a download token or serve
  -- the bytes; the catalogue still lists the row so a client can explain why.
  -- Null means "kept until an operator removes it".
  retained_until timestamptz null
);

-- The list endpoint filters by project and orders by creation, newest first —
-- the same access shape every other collection in this API has.
create index if not exists artifacts_project_id_created_at_idx
  on artifacts (project_id, created_at desc);

create table if not exists android_builds (
  artifact_id varchar(128) primary key references artifacts(id),
  package_name varchar(255) not null,
  version_name varchar(64) not null,
  version_code integer not null,
  environment varchar(32) not null,
  min_sdk_version integer null,
  changelog text null,
  -- SHA-256 certificate fingerprint, 32 colon-separated hex pairs. Public by
  -- construction; it is what lets an operator refuse an APK signed by anything
  -- other than their own key before installing it.
  signing_fingerprint varchar(128) not null
);

create index if not exists android_builds_package_name_version_code_idx
  on android_builds (package_name, version_code desc);

create table if not exists artifact_download_tokens (
  token_hash varchar(128) primary key,
  artifact_id varchar(128) not null references artifacts(id),
  user_id varchar(255) not null,
  created_at timestamptz not null,
  expires_at timestamptz not null
);

-- Expired rows are swept opportunistically when a token is minted; the index is
-- what keeps that sweep from scanning the table.
create index if not exists artifact_download_tokens_expires_at_idx
  on artifact_download_tokens (expires_at);
