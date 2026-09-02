# RESUME — WK-20260826-gh13-events (issue #13, epic #1)

- work_id: WK-20260826-gh13-events
- data: 2026-08-26
- branch: `feature/gh-13/mobile-event-stream`
- contract: 1.8.0 (`probes.API_CONTRACT_VERSION` matched)
- status: **merged** via **PR #62** (2026-09-02), on `main`, `contract/1.8.0/`
  published. Not deployed.
- **the migration was renumbered on merge**: `0009_event_subscriptions.sql` ->
  **`0011_event_subscriptions.sql`**. 0009 had been taken by #73's control plane,
  and two added files with different names is not a merge conflict, so nothing
  reported it.

## Next Step (DO THIS FIRST)

One **operator decision**, opened by the merge and deliberately not made in it.

`gateway/app/services/event_types.py:NOT_DELIVERED` is new. This issue's guard
(`test_every_audited_domain_event_type_is_translated`) fails on any
`record_event` under a deliverable entity with no mobile mapping, and two
writers already on `development` had none — `task.push_preauthorized` and
`task.notification_failed`. Neither was visible from this branch or from
`development` alone; they only met on merge day.

Both are now **excluded on purpose**, with the reason written next to them: the
first is already delivered as `decision.resolved` by the same call, and the
second is an SMTP failure, which is an operator concern with an operator's
channel. That is a judgement call about what the mobile client is owed.

**If the client should hear either of them**, the answer is not an edit to that
dict: it is a new `MobileEventType`, which `docs/api/README.md` counts as a
breaking change, so it is a contract bump and a client migration. The guard also
now fails on an exemption whose writer has disappeared, so the dict cannot rot
quietly.

## What shipped

An authenticated **SSE** event stream (`GET /api/v1/events/stream`) plus a
polling/backlog fallback (`GET /api/v1/events`) and notification-subscription
preferences (`GET`/`PUT /api/v1/notifications/preferences`, migration
`0011_event_subscriptions.sql`). Events are projected from `audit_events`
(monotonic `id` is the resume cursor). Auth/security events are excluded; a
project-scoped principal sees only its own projects' events (fail-closed on an
underivable project); payloads go through a closed vocabulary, never raw
`payload_json`. Resume from an id older than retention returns a typed
`stream.gap` signal (no silent loss). New permissions `events.read`,
`notifications.manage` reported by `/auth/me`.

Endpoints, transport choice (SSE over WS: rides existing bearer auth on a GET,
native `Last-Event-ID` reconnect) and the polling fallback are documented in
`docs/api/README.md`.

## Adversarial review — two rounds (`.docs/agents/council.md` §4)

**Round 1 — raised 11 · survived §2 11 · became tests 11 · questions 0.** Lenses:
claim auditor, second caller, adversarial user (commit `a49ccb8`). Every finding
arrived with a reproduction and closed with a test that fails without the fix.
Highest blast radius:
- the payload whitelist admitted `control`/`state`, which `main.py` reads from an
  executor's `task.ack` **unvalidated** — a connected executor could put a path,
  an internal `host:port`, a `Bearer` value and a 200 KB blob into a mobile line.
  Fixed with a closed vocabulary (membership, not an `assert`).
- the `gap` block queried `audit_events` **unscoped** while the page was scoped —
  a project-limited token could binary-search the global newest id. One
  visibility predicate now used everywhere.
- bounds: `?after=2**63+1` → 500 / killed the stream with no closing frame; unbounded
  `?type=`/`eventTypes` reflected into `details[]`; one token could take all slots
  (per-actor ceiling added; process ceiling lowered 32→8 to fit the 15-connection
  pool).

**Round 2 — raised 7 · survived §2 7 · became tests 1 · questions 2.** Verified by
mutation that 6 of 7 round-1 fixes are genuinely pinned (revert → suite red); the
core security properties (cross-project isolation, token-expiry/revocation ends
the stream within one poll, resume with no off-by-one, auth rows excluded, NULL-
project dropped for admins too) confirmed closed. Classification:

| # | class | finding | disposition |
|---|---|---|---|
| 1 | introduzido-pela-r1 | per-actor slot ceiling untested at the wiring (the `api` fixture drops `per_actor`; dropping the arg leaves the suite green) | **CLOSED this session** — `test_the_module_level_slots_carry_the_configured_per_actor_ceiling` (fails when the arg is dropped) |
| 2 | aberto-da-r1 | 4 accounts still lock out the admin (32→8 made it 4× cheaper); the 503 does not advertise that `GET /api/v1/events` is available now | **operator** — slot arithmetic / whether to advertise the fallback is a direction call |
| 3 | introduzido-pela-r1 | the rescoping made `cursor_ahead`/`oldestAvailableId` per-feed, but the OpenAPI/README text still says "this log" — a client new to a quiet project is told its position "came from another deployment" | **operator/follow-up** — doc correction + whether losing project access deserves a distinct reason vs `beyond_retention` |
| 4 | pré-existente | `actorId` is a whitelisted key with no vocabulary/redaction/length bound (**not reproduced end-to-end** — every live writer passes a server-side `user_id`) | **operator/follow-up** — bound + redact it defensively |
| 5 | pré-existente | `redact` is a pattern list, not a closed set; `error`/`reason` free-text keys still ship a Stripe key, `pw=`, an S3 URI, a UNC path, an email. Same redactor and same `codexbridge.read` audience as the rest of the surface — **not an audience widening** | **operator** — improving `redact` is a whole-surface change |
| 6 | pré-existente | a principal whose project is quiet re-scans the whole tail every poll (cursor never advances when the scoped page is empty); O(n) per poll, 96 ms @ 100k rows | **operator/follow-up** — advance the cursor past the scanned id even on an empty scoped page |
| 7 | pré-existente | a malformed `Last-Event-ID` with no `?after=` replays the entire feed (`_resume_from("-4", None) == 0`); low severity — duplicates not loss, a compliant EventSource cannot produce it | **operator/follow-up** — clamp the no-`after` malformed case |

Round-2 questions left open: (a) is 8/2 the right operating point for the number
of operator accounts this deployment has, or advertise the fallback in the 503;
(b) should losing access to a project be reported as `beyond_retention` or a
third reason.

Per `.docs/agents/council.md` §4 (two rounds, then the operator), the surviving
round-2 findings that are not closed here are the operator's — none is a live
security regression; the core isolation/expiry/resume properties are
mutation-proven closed.

## Checks

`PYTHONPATH=. .venv/bin/python -m pytest -q` (project `.venv`; system python
cannot collect `tests/contract` — pre-existing `fastapi.routing.iter_route_contexts`
ImportError) → **617 passed, 3 skipped**. The round-2 wiring test verified failing
against the unfixed wiring.

Not validated: Postgres; any deployed environment; multi-worker uvicorn; nginx
buffering of a long-lived SSE connection; push delivery (preferences are
future-push hooks only). Migration `0009` NOT applied anywhere. Contract at
1.8.0 — the operator re-bumps on merge order if #11 (1.7.0) lands first.
`governancekit council --record` was not produced (no pre-commit hook here); the
four counts per round are recorded here and in `docs/napkin-lessons.md`.

## Next

Operator: rule on round-2 findings 2–7 (mostly follow-up/pre-existing); merge
order vs #11's 1.7.0; run `scripts/publish_contract.py` after merge (#14 gate).
