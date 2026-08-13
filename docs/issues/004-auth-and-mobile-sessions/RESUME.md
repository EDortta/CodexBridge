# RESUME — WK-20260813-mobile-auth (issue #4, epic #1)

- work_id: WK-20260813-mobile-auth
- data: 2026-08-13
- branch: `feature/gh-4/define-authentication-authorization-and-mobile-s`

## Next Step (DO THIS FIRST)

Adversarial review of this delivery — no council has looked at it. Concentrate
on `gateway/app/api/routes/auth.py` and `store.issue_auth_grant`: the rotation
race, the revocation counters, and whether any 401 path leaks which of the five
rejection reasons occurred.

## Current state

Implemented, not committed, not deployed. Four endpoints under `/api/v1/auth`
(`sign-in`, `refresh`, `revoke`, `me`), revocation honoured by the store both
transports read, and a permission catalogue that guards the endpoints and is
what `GET /api/v1/auth/me` reports.

Contract moved to 1.3.0 (`probes.API_CONTRACT_VERSION` with it). `Actor` left
`x-pending-components`, which is now empty.

## Changed files

`gateway/app/api/{permissions,timestamps}.py` (new), `gateway/app/api/routes/auth.py`
(new), `gateway/app/api/auth.py`, `gateway/app/api/routes/{sessions,probes}.py`,
`gateway/app/services/store.py`, `gateway/app/models/entities.py`,
`gateway/app/db/schema_guard.py`, `gateway/app/core/{users,oauth,config}.py`,
`gateway/app/main.py`, `migrations/0003_mobile_auth.sql`,
`docs/api/{README.md,codex-bridge.openapi.yaml}`, `docs/security.md`,
`.env.example`, `tests/integration/test_auth.py` (new),
`tests/{integration/test_probes.py,unit/test_apply_migrations.py,unit/test_users.py}`.

## Deploy needs a migration

`python3 scripts/apply_migrations.py` before starting the new build —
`schema_guard` refuses to serve without `0003`. **Not done, not authorised.**
The vhosts already route `/api/`, so there is no nginx edge this time.

## Checks

`python3 -m pytest -q` → 230 passed. Also 230 against a throwaway database
(`CODEX_BRIDGE_DATABASE_URL=sqlite+aiosqlite:////tmp/fresh_cb.db`), which is the
fresh-install path. `tests/integration/test_auth.py` runs standalone.

Not validated: Postgres, and any deployed environment.

## Still open from the epic

Council round 2 on #9; #15 (token rotation, operator); #16; #17.

## Council round 1 — 17 raised, 17 survived §2, 16 became tests, 1 risk acceptance, 0 questions left open

Four lenses (sweep skeptic, claim auditor, second caller, adversarial user)
against the approved work. Every finding arrived with a reproduction or an
honest `not reproduced:`, so all 17 survived `.docs/agents/council.md` §2.

Closed with a test that fails without the fix (16):

| # | what was wrong | test |
|---|---|---|
| 1, 4 | disabled account answered `403`, undeclared on `/auth/me` | `test_auth.py::test_a_disabled_account_is_asked_to_sign_in_again_not_told_it_may_not` |
| 2 | `docs/api/README.md` denied a rate limiter that ships | `test_docs_match_the_runtime.py::test_the_api_readme_does_not_deny_the_limiter_that_ships` |
| 3 | runner claimed "nothing was committed" over a half-applied migration | `test_apply_migrations.py::test_a_half_applied_migration_is_not_reported_as_untouched` |
| 5 | decoy cost was a constant, not the registry's | `test_users.py::test_an_absent_user_costs_what_this_registry_costs` |
| 6 | parity guard exempted the whole `ADMINISTRATIVE` category | `test_auth.py::test_the_guard_flags_a_new_administrative_action` |
| 7 | two different 401 messages under a claim of one | `test_auth.py::test_every_401_on_this_surface_is_the_same_401` |
| 8 | `;` inside migration prose split the file | `test_apply_migrations.py::test_a_semicolon_in_a_comment_is_not_a_statement` |
| 9, 12 | sign-in minted scopes past the server allowlist | `test_auth.py::test_sign_in_cannot_mint_a_scope_the_server_allowlist_withholds` |
| 10 | second identical sign-out answered `401` | `test_auth.py::test_signing_out_twice_with_only_an_access_token_is_still_a_sign_out` |
| 11 | `docs/codemap.md` still named `require_scope`, omitted three new modules | `test_docs_match_the_runtime.py::test_the_codemap_names_every_module_of_the_gateway` (renamed in round 2 to `::test_the_codemap_names_every_module_it_claims_to_index`) |
| 13 | default registry was the committed `examples/users.json` | `test_auth.py::test_an_unconfigured_gateway_has_no_account_to_sign_in_as` |
| 14 | `/oauth/authorize` kept the 185x timing oracle | `test_oauth_authorize.py::test_a_wrong_password_costs_the_same_for_a_real_and_an_invented_account` |
| 15 | `audit_events` had no retention and a new unauthenticated writer | `test_auth.py::test_audit_rows_past_the_retention_window_are_swept` |
| 16 | audit payload stored the operator's e-mail | `test_auth.py::test_the_audit_trail_names_the_actor_by_id_and_never_by_email` |

Closed with a **written risk acceptance** (1): finding 17 — `/revoke` acts on a
refresh token it has already classified as spent. Accepted in `docs/security.md`
("Risco aceito: refresh token gasto ainda encerra a própria concessão") and
pinned by `test_auth.py::test_a_consumed_refresh_token_still_ends_its_own_grant`.
**Flagged for the operator:** fixing it points the other way from
`design-standards.md` §6 (fail-closed), so the direction is theirs to set, not
the programmer's.

Two changes reach further than issue #4 and are named rather than smuggled
(`design-standards.md` §7): `users.verify_password_at_constant_cost` was replaced
by `users.authenticate`, converting both call sites and deleting the old one; and
`settings.user_registry_file` no longer defaults into this checkout.

### Checks after round 1

`python3 -m pytest -q` → 262 passed, and 262 again against a throwaway database
(`CODEX_BRIDGE_DATABASE_URL=sqlite+aiosqlite:////tmp/fresh_cb3.db`). Each new
test was run against the unfixed code and observed to fail first. Every touched
test file also runs standalone.

Not validated: Postgres; any deployed environment; and the machine-readable
council record (`governancekit council --record`), which binds to a staged diff
and nothing is staged — an operator step.

## Council round 2 — 8 raised, 8 survived §2, 8 became tests, 0 risk acceptances, 0 questions left open

Round 2 checked round 1's fixes. Findings 1–17 were re-examined and none
reopened; the eight new ones are all consequences of the round-1 changes rather
than of the original delivery, which is exactly what a second round is for.

| # | what was wrong | test |
|---|---|---|
| 18, 20, 25 | the constant-cost fix put a ~300 ms derivation on the one auth route with no attempt ceiling, running on the event loop | `test_oauth_authorize.py::test_a_flood_of_bad_logins_does_not_stall_the_liveness_probe`, `::test_the_browser_login_form_has_an_attempt_ceiling`, `::test_no_request_handler_derives_a_key_on_the_event_loop` |
| 19 | `issue_auth_grant` argued §2 in its docstring and wrote `user_email` into two credential tables | `test_auth.py::test_a_credential_row_names_the_actor_by_id_and_never_by_email`, `test_apply_migrations.py::test_the_operators_email_is_gone_from_every_credential_table` |
| 21 | the decoy charges the registry's **highest** cost, so every cheaper account answered faster than an invented one | `test_users.py::test_the_cheapest_account_in_a_mixed_registry_is_not_identifiable` |
| 22 | a registry that is absent fails closed in total silence | `test_auth.py::test_an_unconfigured_gateway_says_so_instead_of_failing_in_silence` |
| 23 | the retention window chosen for sign-in spam deleted `task.approved` too | `test_auth.py::test_the_retention_sweep_does_not_age_out_the_approval_record` |
| 24 | the new codemap gate walked `gateway/` while the map indexes five trees | `test_docs_match_the_runtime.py::test_the_codemap_names_every_module_it_claims_to_index` |

Reaching further than issue #4, named rather than smuggled
(`design-standards.md` §7):

- `POST /oauth/authorize` now carries `RateLimitDependency`. It was the top item
  in `docs/security.md`'s gap list, and round 1 is what made it urgent.
- `migrations/0004_drop_user_email.sql` removes `user_email` from the three
  credential tables. `schema_guard` gained a `FORBIDDEN_COLUMNS` check so an
  upgrade that skips it fails at boot, naming the file, instead of failing on
  the first sign-in with an integrity error.
- `authenticate_async` is the entry point for request handlers;
  `authenticate` stays synchronous for tests and scripts.

### Checks after round 2

`python3 -m pytest -q` → 270 passed. Each new test was run against the unfixed
code and observed to fail first; the numbers are in the test docstrings.

`migrations/0004_drop_user_email.sql` was applied to the checkout's local
`codex_bridge.db` (gitignored, zero rows in all three tables) because the new
`schema_guard` check refuses to start against a database that still has the
columns — the same step `docs/installation.md` documents for the deployment. A
copy of the file as it was is at `/tmp/codex_bridge.db.before-0004`.

Not validated: Postgres; any deployed environment; the machine-readable council
record (`governancekit council --record`), which binds to a staged diff and
nothing is staged; and behaviour under uvicorn with more than one worker, which
changes how many concurrent derivations it takes to saturate the host but not
the cost of one.
