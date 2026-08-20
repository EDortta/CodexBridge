# RESUME — WK-20260820-gh-5-projects-api (epic #1)

- work_id: WK-20260820-gh-5-projects-api
- data: 2026-08-20
- branch: `feature/gh-5/projects-operational-summary-api` (committed, not pushed)

## Next Step (DO THIS FIRST)

Operator review and push/merge decision for `integration/gh-5-6-7-8-contract-align`
(see `handoff.md`'s 2026-08-20 "integration-gh-5-6-7-8" entry) — the four
branches below are combined and conflict-resolved there, full suite green.
Once merged, next unblocked pick is #10, #11, #13 or #14 (no dependency
ordering declared between any of #5-#14).

## Current state

Merged to `development`: #2, #3, #4, #9, #12, #15, #16, #17.

Delivered, committed, **not pushed, not merged** (each its own branch off
`development`, awaiting operator review):

| issue | branch | commit |
|---|---|---|
| #5 — projects + operational summary | `feature/gh-5/projects-operational-summary-api` | e3d7d5c |
| #6 — operational decisions | `feature/gh-6/expose-operational-decisions-api-v2` | 8113ec2 |
| #7 — missions + mission control | `feature/gh-7/expose-missions-and-mission-control-api-v2` | 37f23ba |
| #8 — epics and issues | `feature/gh-8/expose-epics-and-issues-api-v2` | 0660b17 |

#6/#7/#8 each replace an earlier `feature/gh-N/...` (no `-v2` suffix) branch
that autopilot parked `wip(gh-N): parked, failed` on 2026-08-14 — those are
left untouched as the historical record, not merge candidates. See
`handoff.md`'s 2026-08-20 "council-gh-6-7-8" entry for why.

**All four are now combined** on `integration/gh-5-6-7-8-contract-align`
(off `development` at `81312bb`): the `migrations/0005` number collision
(#6 vs #8 — `0006_epics_issues.sql` is #8's file now, `schema_guard.py`
updated to match) and the `API_CONTRACT_VERSION` (`1.4.0`) changelog-comment
overlap are resolved there — see `handoff.md`'s 2026-08-20
"integration-gh-5-6-7-8" entry for exactly what changed and the combined
suite result. That branch is also committed, **not pushed, not merged**; the
four originals above are left untouched.

Not yet attempted: #10, #11, #13, #14 (placeholder branches, 0 commits ahead
of `development`).

## Open, and whose

| item | owner |
|---|---|
| `integration/gh-5-6-7-8-contract-align` — push/merge decision | operator |
| #15's executor-token-in-logs rotation — **rotate the token and purge logs** | operator |
| council round on #6/#7/#8 once reviewed and approved (council.md's own precondition) | next session, after operator approval |
| #10 (conversations), #11 (artifacts), #13 (event stream), #14 (contract tests) — no attempt yet; empty placeholder branches exist for #10/#11/#13 | next session |
| Postgres never exercised (production is SQLite) | next session |
| pre-existing `test_agent_ws_handshake.py` order-dependency (4 tests fail in full-suite runs, pass alone) on plain `development` itself | next session |
| gh-7's own branch carries a duplicate empty `/health:` path key in its `openapi.yaml` (own-branch bug, found while integrating, dropped from the integration branch, not fixed on gh-7 itself) | next session, if gh-7 is ever merged standalone |

## Checks

Per-branch `python3 -m pytest -q`: #5 381, #6 382, #7 400, #8 388 (each
against its own `development` base). Combined run on
`integration/gh-5-6-7-8-contract-align` — see `handoff.md`'s 2026-08-20
"integration-gh-5-6-7-8" entry for the result.
