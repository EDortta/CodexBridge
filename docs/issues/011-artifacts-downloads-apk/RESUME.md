# RESUME — WK-20260826-gh11-artifacts (issue #11, epic #1)

- work_id: WK-20260826-gh11-artifacts
- data: 2026-08-26
- branch: `feature/gh-11/artifacts-downloads-apk-metadata` (worktree
  `~/Sync/Projects/AI/CodexBridge--gh-11`; **not pushed, no PR**)

## Next Step (DO THIS FIRST)

Two operator decisions are open. Neither blocks the delivery; both were found by
the council and are deliberately **not** decided here.

1. **`schema_guard.REQUIRED_TABLES` is documentation, not a boot gate.**
   `gateway/app/main.py:startup` runs `Base.metadata.create_all` one statement
   before `check_schema`, and every table it demands is declared on `Base` — so
   a gateway started against a database that never ran 0006, 0007 or 0008
   creates the tables itself and starts clean. What it then runs is the
   `create_all` schema, **not** the shipped one: no indexes, no `content_type`
   default, and no `schema_migrations` row, so the next migration's bookkeeping
   starts from a wrong premise. Nothing warns. This is pre-existing and affects
   every table-only migration, not just #11's. Moving `check_schema` ahead of
   `create_all` (or narrowing `create_all`) changes how every migration in this
   project is gated, which is your call, not one issue's. Five files that
   promised the boot failure have been corrected to say what actually happens,
   and `tests/unit/test_schema_guard.py::test_required_tables_cannot_fire_at_boot_today`
   fails the day someone makes the gate real, so the prose cannot drift back.

2. **`CODEX_BRIDGE_ARTIFACTS_ROOT` must be set on the deployment.** Unset, the
   default resolves `data/artifacts` against the process working directory at
   import — `/opt/codex-bridge/data/artifacts` under the systemd unit. A wrong
   root makes every download answer a typed `404` that names no path, which is
   silent by design. Now documented in `docs/installation.md` step 4,
   `docs/operations.md` (a symptom entry) and `.env.example`, and pinned by
   contract tests.

Then: review the two commits, and if you want it merged, push and open the PR.
Deploy needs `python3 scripts/apply_migrations.py` — **not run, not authorised.**

## Current state

Implemented, committed on the feature branch, **not pushed, not deployed**.
Six endpoints under `/api/v1`:

| endpoint | what it is |
|---|---|
| `GET /api/v1/artifacts` | catalogue, project-scoped, cursor-paginated, `?project` `?type` `?origin` |
| `GET /api/v1/artifacts/{artifactId}` | one artifact, with `android` when it is an APK |
| `POST /api/v1/artifacts/{artifactId}/download-token` | mints a short-lived bearer credential for one artifact |
| `GET /api/v1/artifacts/{artifactId}/download` | streams the bytes to the holder of that credential; `Range` → 206/416 |
| `GET /api/v1/builds/android` | the `apk` rows with `android` guaranteed, `?environment` `?packageName` |
| `GET /api/v1/builds/android/{buildId}` | one build, addressed by the artifact's own id |

Contract at **1.7.0**, `probes.API_CONTRACT_VERSION` with it,
`capabilities.artifactDownloads` flipped to `true`. Two catalogued actions:
`artifacts.read`, `artifacts.download`.

**Nothing in this build produces an artifact.** No ingestion path, no upload
endpoint, no executor message writes a row; `store.create_artifact` is the only
way one exists, which today means a test fixture or an operator script. Said out
loud in the module docstrings, the API README, the OpenAPI descriptions and the
test docstrings rather than implied.

### Design decisions worth knowing

- **An Android build is not a second entity** — it is an artifact of type `apk`
  plus its metadata, keyed by the artifact's own id, so the mobile client never
  holds two identifiers for one file.
- **The bytes are not behind the session token.** Android hands a large download
  to the system downloader, a separate process with no access to the app's
  session. The download credential travels in `Authorization: Bearer`, never in
  a query string (`security-standards.md` §2; issue #15 is the precedent), and
  the mint response returns a *path* with no credential in it.
- **The token is not single-use** — see the risk acceptance below.
- **`storage_path` never ships.** Confinement is checked lexically at the write
  and after `Path.resolve()` at the read, which is what catches a symlink
  planted inside the root.
- **Retention is load-bearing:** past `retainedUntil` the row is still listed and
  reports `retained: false`, while minting and downloading both answer `409`.

## Changed files

`gateway/app/api/routes/artifacts.py` (new),
`gateway/app/services/{artifact_storage,artifact_types}.py` (new),
`migrations/0010_artifacts.sql` (new),
`tests/integration/test_artifacts.py` (new, 52 tests),
`gateway/app/api/{auth,permissions}.py`,
`gateway/app/api/routes/probes.py`, `gateway/app/core/{config,oauth}.py`,
`gateway/app/db/schema_guard.py`, `gateway/app/main.py`,
`gateway/app/models/entities.py`, `gateway/app/services/store.py`,
`docs/api/{README.md,codex-bridge.openapi.yaml}`, `docs/codemap.md`,
`docs/{security,installation,operations,required-reading}.md`,
`deploy/README.md`, `scripts/{install.sh,apply_migrations.py}`,
`.env.example`,
`tests/contract/{test_openapi_document,test_docs_match_the_runtime}.py`,
`tests/integration/{test_auth,test_probes}.py`, `tests/unit/test_schema_guard.py`.

## Deploy needs a migration

`python3 scripts/apply_migrations.py` before starting the new build.
**Not done, not authorised.** Read Next Step item 1 first: the gateway will
start *without* it and look healthy, which is exactly the trap.

Also set `CODEX_BRIDGE_ARTIFACTS_ROOT`. The vhosts already route `/api/`, so
there is no nginx edge change — but see "Not validated" about buffering.

## Checks

`PYTHONPATH=. python -m pytest -q` → **621 passed, 3 skipped** from the
worktree, with `gateway` resolving to the worktree copy (verified). Each new
test was run against the unfixed code and observed to fail first.

`not validated:` PostgreSQL; any deployed environment; nginx buffering behaviour
on a real multi-megabyte APK through `location /api/`; behaviour under uvicorn
with more than one worker; and the ingestion path, which does not exist.

---

## Council round 1 — 13 raised, 11 distinct survived §2, 11 became tests or corrections, 5 questions left open

Three lenses (claim auditor, second caller, adversarial user) against the
approved, committed delivery `9ba4e7b`. Thirteen reports, eleven distinct after
merging two duplicates (the contract's security scheme and the revocation gap
were each found by two lenses). Every one arrived with a reproduction, so all
eleven survived `.docs/agents/council.md` §2.

| # | lens | what was wrong | closed by |
|---|---|---|---|
| 1 | claim auditor | "Four things narrow the credential, and **each one is tested**" — the hashed-storage property had no test anywhere | `test_artifacts.py::test_the_download_token_is_never_stored_in_the_clear` |
| 2 | claim auditor | `docs/api/README.md` said `android.signingFingerprint` is on the mint response; it is not | prose corrected |
| 3 | claim auditor | contract declared `application/octet-stream` for the download while the server sends the artifact's own `contentType` | `'*/*'` in the contract, with the reason |
| 4 | claim auditor + second caller | `downloadArtifact` declared `bearerAuth`, whose description promises revocation "everywhere" — a generated client would attach the session token and loop on its 401 interceptor | new `artifactDownloadToken` scheme + `DownloadTokenRejected` response + `test_openapi_document.py::test_the_artifact_download_does_not_claim_the_session_credential`, `::test_every_declared_security_scheme_is_used` |
| 5 | all three | **a minted download token survived `POST /api/v1/auth/revoke`** — sign-out killed the session and left an APK streaming for the rest of the TTL | `store._revoke_artifact_download_tokens` + `test_auth.py::test_signing_out_kills_a_download_token_minted_before_it`, `::test_revoking_by_refresh_token_also_kills_the_download_tokens` |
| 6 | claim auditor | `_content_missing` told the operator to find the artifact "from the `requestId` in the log"; no log line existed | `logger.warning("artifact_content_unavailable", …)` + `test_artifacts.py::test_the_missing_content_404_writes_a_log_line_the_request_id_finds` |
| 7 | claim auditor | `ArtifactError`'s docstring advertised a `400 validation_failed` conversion no route performs | docstring corrected; the pointer is for the ingestion endpoint a future issue adds |
| 8 | claim auditor | `docs/codemap.md` advertised a `response` parameter `list_artifacts` does not have | regenerated |
| 9 | adversarial user | **`Range` of 4301+ digits → `500 internal_error` with `retryable: true`** (CPython's `int()` conversion limit), reachable by any download-token holder | digit bound in `_RANGE_RE` + `test_artifacts.py::test_an_absurdly_long_range_is_not_a_five_hundred` |
| 10 | second caller | `schema_guard` cannot fail a boot for a missing table, and this delivery's own README sentence promised it does | prose corrected in five files + `tests/unit/test_schema_guard.py::test_required_tables_cannot_fire_at_boot_today`; mechanism escalated (Next Step 1) |
| 11 | second caller | five places cite §"Fields that must never ship" as forbidding `storage_path`; the section named only `ProjectModel.path` | bullet added + `test_docs_match_the_runtime.py::test_every_field_cited_as_never_shipping_is_actually_listed_there` |

Also added in round 1, from the adversarial user's question about what stops the
*next* unguarded route: `tests/integration/test_probes.py::test_every_served_api_route_is_guarded_or_listed_with_a_reason`
plus `UNGUARDED_API_ROUTES` — `security-standards.md` §4's "a missing guard fails
review, it is not default-allow" was a human promise until this delivery added
the first `/api/v1` route that authenticates with a credential of its own.

Questions left open after round 1 (5): nginx buffering on a real APK; whether
0008 is exercised on PostgreSQL anywhere; whether the two 0008 indexes should
also be declared on the models; that the expired-token sweep only fires on mint;
and whether bare SHA-256 is the intended storage for a high-entropy bearer
(it matches `create_oauth_access_token`, so yes — now written down in
`docs/security.md`).

## Council round 2 — 11 raised, 11 survived §2, 11 became tests or corrections, 5 questions left open

Same three lenses, against the staged round-1 fixes. Both round-1 security
findings were independently confirmed closed, path confinement and token binding
re-probed and still holding. Classification per `.docs/agents/council.md` §4:

### `introduzido-pela-r1` (7)

| # | what the round-1 fix broke | closed by |
|---|---|---|
| 1 | **the by-actor revocation reached across grants.** `/auth/revoke` deliberately acts on a refresh token it has already classified as dead; both `UPDATE`s are no-ops then, and the new `DELETE` was the one statement that still hit something — so an *unauthenticated* replay of a long-dead token destroyed a **live** grant's download credential, repeatably. Same widening let a ChatGPT sign-out abort the phone's APK transfer | `artifact_download_tokens.grant_id` (0008, undeployed, so free) + revocation scoped to `(user_id, grant_id)` + `test_auth.py::test_a_replayed_dead_refresh_token_cannot_kill_a_live_grants_download`, `::test_a_grantless_sign_out_does_not_abort_the_phones_download` |
| 2 | the new `UNGUARDED_API_ROUTES` gate detected **authentication**, not authorization: a route with only `Depends(current_principal)` passed, and so did a route with no auth at all whose dependency happened to be named `guard` | `require_action` tags its closure `guarded_action`; the gate reads that. `/auth/me`'s exemption became load-bearing, and `::test_every_exemption_is_load_bearing` now fails if any entry is inert |
| 3 | the 19-digit `Range` bound dropped legal zero-padded ranges (`bytes=000…01-2`), silently re-sending the whole file with `200` — and the comment called the bound lossless | widened to 255 digits + `test_artifacts.py::test_a_zero_padded_range_is_still_a_range` |
| 4 | the corrected docstring said "All five live in `test_artifacts.py`" while one lives in `test_auth.py` | corrected, with the reason it lives there |
| 5 | `docs/api/README.md` pointed the operator escalation at `docs/issues/011-…/RESUME.md`, which did not exist | this file |
| 6 | the docstring that retired a rotted count ("eleven") replaced it with "most", for a 37% plurality | no count and no proportion quoted; the load-bearing half kept |
| 7 | `test_required_tables_cannot_fire_at_boot_today` contracted "if someone makes the gate real, this test must fail" and could not — it never read the boot ordering | now asserts `run_sync(create_all)` precedes `run_sync(check_schema)` in `main.py:startup` |

### `aberto-da-r1` (3)

| # | what round 1 did not finish | closed by |
|---|---|---|
| 8 | the boot-gate correction reached `docs/api/README.md` only; `scripts/install.sh`, `deploy/README.md`, `scripts/apply_migrations.py`, `schema_guard.py` and `docs/required-reading.md` still promised a crash loop | all five corrected + `test_docs_match_the_runtime.py::test_no_shipped_file_still_promises_a_boot_gate_for_a_table_only_migration` |
| 9 | `docs/api/README.md` still said "Four things" and omitted *narrowed* and *revoked* from the refusal list, contradicting the OpenAPI scheme added by the same fix | list rewritten to five, each naming its test |
| 10 | `.env.example` still said the unset artifacts root is `<checkout>/data/artifacts` — the one file an operator copies | corrected + `::test_the_env_example_does_not_claim_the_artifacts_root_is_the_checkout` |

### `pré-existente` (1)

| # | | closed by |
|---|---|---|
| 11 | `docs/installation.md` step 4 never named `CODEX_BRIDGE_ARTIFACTS_ROOT` while `docs/security.md` calls it mandatory, and `docs/operations.md` had no entry for the surface at all | both documented + `::test_the_installation_guide_names_every_setting_security_md_calls_mandatory` |

Questions left open after round 2 (5): nginx `proxy_buffering` on a 60 MB APK
(read off the config, not measured); the retired `deploy/incus` edge proxy
buffering a whole response if ever reinstated; whether `/auth/revoke` should
fail *closed* when the audit write fails (pre-existing shape, unchanged by this
delivery); whether 120 structured warnings/min/IP from `artifact_content_unavailable`
is inside the deployment's log budget; and `docs/codemap.md`'s unverifiable
symbol count, which is the generator's own output.

## Risk accepted, in writing

**The download token is not single-use.** Issue #11 asks for range and resumable
downloads in the same breath as short-lived authorization, and a token consumed
by the first request makes a resumed transfer impossible. The lifetime is the
control. Recorded in `docs/security.md` ("Risco aceito: token de download não é
de uso único") and pinned by
`tests/integration/test_artifacts.py::test_a_token_survives_reuse_inside_its_lifetime`,
which is what has to change if the decision changes.

## Reaching further than issue #11, named rather than smuggled

`design-standards.md` §7 — three changes touch surfaces this issue does not own,
and each is here because a council finding required it, not as a tidy-up:

- **`POST /api/v1/auth/revoke` now deletes download tokens** (`store.py`). Issue
  #4's endpoint, changed because leaving it alone meant shipping a sign-out that
  does not sign out.
- **`require_action` tags its closure `guarded_action`** (`api/auth.py`), so a
  route inventory can tell authorization from authentication. One attribute, no
  behaviour change.
- **Five deploy/ops documents corrected** about what `schema_guard` guarantees.
  Pre-existing and false for 0006 and 0007 as much as for 0008; correcting only
  #11's sentence would have left the same wrong belief in the files an operator
  actually reads.
