# RESUME — WK-20260902-gh73-control-ui (epic #73)

- work_id: WK-20260902-gh73-control-ui
- data: 2026-09-02
- Stage 1 (domain/contracts): PR #74 merged into `development` as `80e5d2f`.
- Stage 2 (fleet visibility), Stage 3 (discovery report + adoption), Stage 4
  (authorization plane enforcement): merged onto this lineage before this
  session (`2ed550f`, `a57a8d9`, `a1cf4d7`, `e450c85`, `ac79a47`).
- Stage 5, first cut (this session): branch `feature/gh-73/control-ui`,
  worktree `../CodexBridge--WK-20260902-gh73-control-ui`, base
  `feature/gh-73/authorization-plane`. Committed locally, **not pushed, no PR
  opened** (commit and stop, same as every prior stage in this lineage).

## Next Step (DO THIS FIRST)

Open the PR for `feature/gh-73/control-ui`, get it reviewed, then decide with
the operator whether the next stage is (a) a real `POST /api/v1/nodes/invite`
+ `scripts/enroll_node.py` (the gap this session found and did not build —
see "Watch for" below), or (b) the epic's own Stage 6 (Missions/Decisions/
Audit/Settings convergence).

## Current state

- `gateway/app/api/routes/control_ui.py` (new): three working screens —
  `GET /control` (fleet), `GET /control/nodes/{nodeId}` (capabilities/
  engines, paginated discovered candidates with Adopt/Deny, authorizations
  with Grant/Revoke), `GET /control/invite` (explanation only — see below).
  HTML in the gateway's own process, the `/oauth/authorize` precedent — no
  template engine, no second deployable.
- Reads call the exact DTO functions the JSON routes already use
  (`routes.nodes._node_dto`, `routes.discovery._discovered_resource_dto`,
  `routes.authorizations._authorization_dto`); writes are `fetch()` against
  the real `/api/v1/**` routes. No business logic duplicated.
- Auth: HTTP Basic, re-verified per request via the same `authenticate_async`
  `/oauth/authorize` uses, gated by the same `permissions.is_allowed`
  catalogue as `/api/v1/**`. A page that needs to write (node detail) mints
  an ordinary, short-lived `oauth_access_tokens` row per render (same table,
  same scope cap as mobile sign-in) embedded inline for that page's own
  `fetch()` calls — never in a URL, never audited on mint. Full reasoning in
  `control_ui.py`'s own module docstring and `docs/control-plane.md`'s
  "Stage 5" section.
- Three new `store.py` read-only helpers, used only by this module:
  `count_decidable_discovered_resources`, `list_active_authorizations_for_node`,
  `get_project_names` (name only, never `ProjectModel.path`).
- **Finding, not silently patched**: the plan's fourth screen
  (`GET /control/invite`) was specified to call `POST /api/v1/nodes/invite`
  and print a `scripts/enroll_node.py` command. Neither exists in this
  codebase — confirmed by grep and by `docs/project-onboarding.md`, which
  already documented node registration as a manual two-file procedure. Built
  as an honest explanation screen instead of a form that posts to nothing.
  See `docs/napkin-lessons.md`'s 2026-09-02 "um plano de UI pode descrever um
  endpoint que nunca foi construído" entry and `control_ui.py`'s own
  docstring, "`/control/invite`".
- `x-contract-excluded-paths` gained three entries (`/control`,
  `/control/nodes/{nodeId}`, `/control/invite`) — HTML, not part of the
  mobile contract, same posture as `/oauth/*`. `API_CONTRACT_VERSION` **not**
  bumped: no `/api` route changed.

## Changed files

`gateway/app/api/routes/control_ui.py` (new),
`tests/integration/test_control_ui.py` (new),
`gateway/app/services/store.py`, `gateway/app/main.py`,
`docs/api/README.md`, `docs/api/codex-bridge.openapi.yaml`,
`docs/control-plane.md`, `docs/operations.md`, `docs/codemap.md`,
`docs/napkin-lessons.md`, `deploy/nginx/frida-codex-bridge.conf`.

## Checks

- `.venv/bin/python -m pytest -q` → **906 passed, 7 skipped, 0 failed**
  (branch baseline before this PR: 886/7).
- `tests/contract/` → all green (26 passed), codemap regenerated with
  `governancekit --root . map`.
- Pytest collection needed the sibling `awt` `.env` moved aside first, same
  as every prior session in this lineage — restored immediately after,
  never committed.

## NOT validated

No deploy, no real browser exercised against a live gateway (all coverage is
`TestClient` + in-memory SQLite). No manual check that the nginx block
proposed in `docs/operations.md` actually reverse-proxies correctly on
`frida` — applying it is the operator's own action, not done by this session.

## Watch for

`GET /control/invite` does not do what its name promises — it explains why
instead. Building the real flow (a token-issuing endpoint with its own
security posture, plus `scripts/enroll_node.py`) is real backend work
belonging to its own PR/stage, flagged here rather than fabricated inside a
UI PR.
