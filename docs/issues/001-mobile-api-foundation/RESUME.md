# RESUME — WK-20260810-api-foundation (epic #1)

- work_id: WK-20260810-api-foundation
- data: 2026-08-10
- branch: `feature/gh-1/api-foundation` (pushed)

## Next Step (DO THIS FIRST)

Run council round 2 over the issue #9 fixes. One adversarial round ran and
produced 16 findings; all were closed with tests proven to fail without them,
but **no pass has looked at the closures**. Same standing gap #12 and #3 had.

## Current state

#2, #12, #3, #9 delivered, committed, pushed, and **deployed to frida**.
Verified through `https://codexbridge.inovacaosistemas.com.br:8443`: probes 200,
`contractVersion` 1.2.0, `/api/v1/sessions` 401 without a token, `/mcp` unchanged,
executor `devel3` reconnected.

Commits: 4c6d70f (#2), b76a391 (#12), f70d858 (#3), 9b2fa4f (extra councils),
4ddac46 (env recipe), db34d22 (deploy README), ce33e09 (#9).

## Open, and whose

| item | owner |
|---|---|
| #15 — executor token in logs; **rotate the token and purge logs** | operator |
| #16 — pause/resume/restart need protocol work and a prior decision | next session |
| #17 — nothing replays `task.cancel` on reconnect; a stopped session keeps running | next session |
| council round 2 on #9 | next session |
| Postgres never exercised (production is SQLite) | next session |
| MCP cancel/dispatch paths have no test; `hub_envelope` protected only by import | next session |

## Checks

`pytest tests -q` → 197 passed. Every new test file also runs alone.
Backups before each deploy in `/var/backups/codex-bridge/<TS>/`, `LAST` points at
the most recent (`20260810-165541`).
