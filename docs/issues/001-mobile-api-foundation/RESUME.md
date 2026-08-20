# RESUME — WK-20260810-api-foundation (epic #1)

- work_id: WK-20260810-api-foundation
- data: 2026-08-10
- branch: `feature/gh-1/api-foundation` (pushed)

## Next Step (DO THIS FIRST)

Operator review and push/merge decisions for the branches below — nothing
implementation-side is blocking. Once merged, next unblocked pick is #10,
#11, #13 or #14 (no dependency ordering declared between any of #5-#14).

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
`handoff.md`'s 2026-08-20 "council-gh-6-7-8" entry for why, and its
"Known follow-up" section for the migration-number (`0005`) and
`API_CONTRACT_VERSION` (`1.4.0`) collisions across #5/#6/#7/#8 that whoever
merges more than one of them will need to resolve by hand.

Not yet attempted: #10, #11, #13, #14 (placeholder branches, 0 commits ahead
of `development`).

## Open, and whose

| item | owner |
|---|---|
| #15's executor-token-in-logs rotation — **rotate the token and purge logs** | operator |
| council round on #6/#7/#8 once reviewed and approved (council.md's own precondition) | next session, after operator approval |
| Postgres never exercised (production is SQLite) | next session |
| pre-existing `test_agent_ws_handshake.py` order-dependency (4 tests fail in full-suite runs, pass alone) on plain `development` itself | next session |

## Checks

Per-branch `python3 -m pytest -q`: #5 381, #6 382, #7 400, #8 388 (each
against its own `development` base). No combined run across branches without
merging first.
