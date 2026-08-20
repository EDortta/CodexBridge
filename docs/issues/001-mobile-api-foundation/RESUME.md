# RESUME — WK-20260820-gh-5-projects-api (epic #1)

- work_id: WK-20260820-gh-5-projects-api
- data: 2026-08-20
- branch: `feature/gh-5/projects-operational-summary-api` (committed, not pushed)

## Next Step (DO THIS FIRST)

Operator review and push/merge decision for #5 (this session's delivery).
After that: #6 (decisions) is the next natural pick, but read the dead
`feature/gh-6/expose-operational-decisions-api` branch's own WIP commit first
— design reasoning worth keeping even though nothing built on it.

## Current state

Merged to `development`: #2, #3, #4, #9, #12, #15, #16, #17.
This session delivered #5 (projects + operational summary API) — committed on
its own branch, **not pushed, not merged**. See `handoff.md`'s
"[2026-08-20] WK-20260820-gh-5-projects-api" entry for the full breakdown.

Stale entries from before this session (not re-verified now): #2/#3/#9/#12
were reported deployed to frida as of 2026-08-10 — not re-checked this
session, do not assume still current.

## Open, and whose

| item | owner |
|---|---|
| #5 — push/merge decision | operator |
| #6 (decisions), #7 (missions), #8 (epics/issues) — each has a parked, failed autopilot attempt on its own `feature/gh-N/...` branch (2026-08-14, reviewer BLOCKER or reviewer-agent failure); not resumed by this session | next session |
| #10 (conversations), #11 (artifacts), #13 (event stream), #14 (contract tests) — no attempt yet; empty placeholder branches exist for #10/#11/#13 | next session |
| #15's token rotation/log purge (operator action, named in the 2026-08-18 entries) | operator, if not already done |
| Postgres never exercised (production is SQLite) | next session |

## Checks

`python3 -m pytest -q` → 381 passed, as of this session (`feature/gh-5/projects-operational-summary-api`).
