Parent: #63
Related: #53 (orchestration commands/status/event contract), #41, #50

## Objective
Expose the first HTTP endpoint that can create work: `POST /api/v1/missions`. Today, task creation exists **only** as the MCP tool `submit_codex_task` — `gateway/app/api/permissions.py`'s own docstring says so on purpose: `codexbridge.task.submit` "is therefore still absent [from the HTTP contract]: it exists in the MCP transport and in `users.json`, and no HTTP endpoint of this contract offers it yet." As a direct consequence, CodexBridgeMobile has no way to launch anything today. This issue is the single highest-leverage item blocking the entire CodexBridgeMobile mission-launcher workstream filed alongside this epic.

## Scope
- New route in `gateway/app/api/routes/missions.py`.
- New `Action` in `gateway/app/api/permissions.py` (`missions.create`), the first HTTP exposure of `codexbridge.task.submit`.
- New `missionCreation` capability flag reported by `GET /api/version` (`gateway/app/api/routes/probes.py`), so a client never renders a launch control the backend cannot honor.

## Requirements
- Honors `Idempotency-Key` per the existing convention (`gateway/app/api/idempotency.py`) — a mobile client retrying after a lost connection must not create a second mission for the same intent.
- Accepts an issue reference, project reference, engine choice, and the same `DeliveryRequest` envelope (`branch`, `allow_push`) introduced in #66, following the same pre-authorization-as-approval path described there — no separate, weaker authorization path for the HTTP surface.
- **Must not re-open the identity question council finding F01 raises.** `mission`, `session`, and `decision` are today the same `TaskModel` row, and the Flutter client already persists that id on screen (`http_mission_repository.dart`, `http_live_session_repository.dart`). This endpoint creates a `TaskModel` row exactly as `submit_codex_task` does; it does not introduce a new id space, and the response id is the same id `GET /api/v1/missions/{id}` already serves. The identity split (Mission vs. Attempt vs. Session vs. Decision as distinct aggregates) remains #43's decision to make, not this issue's.
- Response shape matches the existing `_mission_dto` (`gateway/app/api/routes/missions.py`), extended additively with the same `engine`/`issue_ref`/`delivery` fields #64–#66 add to the task row.

## ARO
- **F01** (critical, open): this issue deliberately does not touch identity — see above. Any reviewer proposing an id-space change here should redirect that discussion to #43.
- Standard authentication/authorization risk: this is the first `task.submit`-equivalent capability reachable from a mobile bearer token rather than only an OAuth-scoped MCP session; the existing `permissions.py` catalogue and scope-checking machinery is reused unchanged, not reimplemented.

## Test plan
- Extend `tests/integration/test_missions.py`: creation happy path; idempotency replay; `missionCreation: false` capability gating in a build/config where the feature is disabled; delivery pre-authorization flowing through identically to the MCP path.
- `tests/contract/test_openapi_document.py`: the new path and the `missionCreation` capability flag are documented in `docs/api/codex-bridge.openapi.yaml`.
- `tests/contract/test_proxy_routes.py`: the route is added to `deploy/nginx/frida-codex-bridge.conf`'s `/api/` location allowlist path if it is not already covered by the existing `/api/` prefix (verify — the plan notes `/api/` already has a location block, but this test enforces it either way).

## Definition of Done
- A client holding `codexbridge.task.submit`-equivalent HTTP authorization can create a mission via `POST /api/v1/missions` and immediately read it back via the existing `GET /api/v1/missions/{id}`.
- No new id space, no new `TaskState`, no change to `_mission_dto`'s existing field meanings.
