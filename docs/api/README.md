# CodexBridge public API — contract rules

- work_id: WK-20260810-api-foundation
- data: 2026-08-10
- owner: Esteban D.Dortta
- issue: #2 (epic #1)

The canonical contract is [`codex-bridge.openapi.yaml`](./codex-bridge.openapi.yaml).
This file holds the rules that a YAML document cannot express: what is in scope,
what forces a new version, and what may never appear in a response.

---

## Contract scope

The gateway exposes several HTTP surfaces. Only one of them is this contract.

| surface | in this contract? | why |
|---|---|---|
| `/api/v1/**` | **yes** | the mobile-facing public API, including `/api/v1/auth/**` (issue #4) |
| `/health`, `/ready`, `/api/version` | **yes** (issue #3) | mobile probes them before authenticating |
| `POST /mcp` | no | JSON-RPC/MCP transport for ChatGPT; contract is `docs/protocol.md` |
| `/oauth/**`, `/.well-known/**` | no | OAuth 2.1 flow and metadata; contract is the RFCs (6749, 7636, 8414, 9728) |
| `GET /metrics` | no | Prometheus scrape format, operator-facing |
| `GET /healthz` | no | pre-existing infrastructure probe, superseded for mobile by `/health` |
| `WS /agent/ws` | no | reverse executor channel; contract is `docs/protocol.md` |
| `GET /control/**` | no | CodexBridge Control's server-rendered screens (issue #73 Stage 5); HTML, gated by HTTP Basic, consuming this same contract's `/api/v1/**` endpoints from the browser — see `gateway/app/api/routes/control_ui.py`'s own docstring |
| `/openapi.json`, `/docs`, `/docs/oauth2-redirect`, `/redoc` | **not served at all** | FastAPI's auto-generated description and its UIs, switched off — see below |

`docs/chatgpt-oauth-rollout.md` is **not** the contract for the OAuth endpoints.
It is a rollout plan: it names no path and specifies no request or response
shape. The normative references are the RFCs, and `gateway/app/core/oauth.py` is
what this deployment actually issues.

### There is no other OpenAPI document

FastAPI generates an OpenAPI description by introspecting the application and
serves it at `/openapi.json`, with Swagger UI at `/docs` and ReDoc at `/redoc`.
That document lists the internal MCP and OAuth surfaces and carries none of the
rules in this file, so it was two public descriptions of one gateway with the
canonical one not among them.

`gateway/app/main.py` now passes `openapi_url=None`, `docs_url=None` and
`redoc_url=None`. All four paths return 404, and
`tests/contract/test_openapi_document.py::test_generated_openapi_is_not_served`
fails if any of them comes back — whether by someone removing the arguments or
by a FastAPI default changing underneath. This document is the only description
of this gateway.

They are deliberately **not** listed in `x-contract-excluded-paths`: that list
describes served surfaces, and `test_no_exclusion_outlives_its_route` would
reject an entry for a route the gateway does not serve.

Note for anyone reading history: at the public deployment those paths already
answered 404 before this change, because the nginx edge proxy did not forward
them. The exposure was on any network that reaches the gateway directly, not on
the public host — the fix removes the surface rather than relying on the proxy
to keep hiding it.

The table above is the human-readable view. The **enforced** copy is
`x-contract-excluded-paths` inside the OpenAPI document itself, which is what
`tests/contract/test_openapi_document.py` reads; keeping the contract as the
single machine-readable source is why the exclusions live there and not in the
test. This table is documentation and can drift from it — the test cannot.

A new public route that appears in neither `paths` nor `x-contract-excluded-paths`
fails the test, and an exclusion with an empty `reason` fails it too. So an
endpoint can be left out of the contract only on purpose and in writing, never by
forgetting.

Two escapes are closed explicitly, because both were found by adversarial review
of the first cut of this gate:

- **A route under `/api` can never be waived.** The exclusion list is not an
  escape hatch for the public namespace: a route the app serves under `/api`
  must appear in `paths`, and must be under `/api/v1/`. Without that rule, a
  developer whose new `/api/tasks` route failed the undocumented-route check
  could read the failure message — which names `x-contract-excluded-paths` — and
  ship an unversioned public API with the suite green.
- **An exclusion cannot outlive its route.** A stale entry would stay valid
  forever and silently pre-authorize any future route that reclaimed the path.

### What the gate does not cover

It compares **route inventories**: `(path, method)` on both sides. It does not
read a single `requestBody` or `responses` block. An endpoint that returns a
shape this document does not describe — FastAPI's default `{"detail": ...}` with
HTTP 422, for instance, which matches no field of `Error` — passes this gate.

Body-level conformance is a **separate** gate,
`tests/contract/test_declared_examples_are_real.py` (issue #14). It validates
live response bodies against the schemas declared here, checks that no response
carries a top-level field this document omits, and checks every declared example
against the schema it illustrates. It reaches only what it can drive without a
credential — the operations that declare `security: []` — so **authenticated
endpoints' bodies are still unchecked against this document**; they are covered
in `tests/integration` against expectations written in Python, which is the
weaker form, because two independent statements of one contract drift.

Read a green route-drift run as *"the same endpoints exist on both sides"*,
never as *"the implementation matches the contract"*. `docs/api/testing.md`
has the table of which gate guards which pair.

---

## Versioning

The public namespace is `/api/v1`.

- `info.version` in the OpenAPI document is the **contract** version and follows
  semver. It is independent of the gateway application version and of the
  `/api/version` response.
- The **namespace** (`v1`) changes only on a breaking change. Contract minor and
  patch versions move within a namespace.
- **Every change to the document moves `info.version`.** A client that pins
  `1.0.0` must receive the same bytes tomorrow; leaving the version still while
  the content changes is what makes a pin meaningless.
- `x-minimum-supported-version` names the oldest **published** version this
  build still promises to serve. `scripts/check_contract_compatibility.py`
  compares the working document against the published copy of that version and
  fails the build on any change the next section forbids. Raising the floor
  drops the promise to every client still on the older pin, and needs the same
  conversation with the mobile team that a deprecation does — so it must be the
  oldest published version unless `x-minimum-supported-version-raised` records
  why not, naming the mobile release that stopped using it. That is not
  bureaucracy: raising the floor is also the cheapest way to silence this gate
  permanently, and a one-line diff should not be able to do that unremarked.

What is enforced, and what is still on trust: the digest of a published version
is enforced (a version edited after publication fails
`tests/contract/test_published_contract_artifact.py`), and so is the absence of
a mechanically visible break against the floor. **`info.version` moving on every
change is not enforced** — a byte change with the version left still fails the
publish check, which is satisfied by republishing under the same number. See
"Getting the contract to the mobile repository".

### The `/api/version` carve-out

`GET /api/version` is the one path allowed under `/api` outside the versioned
namespace, and the rule is enforced that way in
`tests/contract/test_openapi_document.py` (`UNVERSIONED_API_PATHS`).

It has to sit outside, because its job is to tell a client which namespaces the
server speaks *before* the client commits to one — a question it cannot ask from
inside `/api/v1`. Its response therefore describes **all** namespaces the server
serves, not the one it is nested in, and when `/api/v2` exists this same path
reports both. That obligation is what keeps it from being a versioning hole.

### What is a breaking change

A change is breaking — and therefore requires `/api/v2` or a documented
migration accepted by the operator — when an existing, conforming client can
stop working because of it:

- removing an endpoint, a field, or an enum value a response may return;
- renaming anything, in either direction;
- narrowing a type, tightening a constraint (`maxLength`, `pattern`, `required`),
  or making an optional request field required;
- **a field of a *response* leaving that schema's `required` list.** A generated
  client makes a required field non-nullable and reads it unconditionally, so
  "it might not be there now" breaks it. On a request-only schema the same edit
  is a relaxation — the gate reports both and names the direction, because a
  JSON pointer cannot tell which a shared schema is, and most here are shared;
- **changing a `default`.** A client that omits the field gets different
  behaviour with no code change on either side and no error to notice;
- **changing which credential an operation accepts** — a different scheme, or a
  scope a client's token does not carry. An endpoint that stops being
  unauthenticated is the same rule at its limit;
- **requiring a request body where the operation accepted none**, or pointing an
  operation at an already-required component parameter;
- changing the meaning of an existing field while keeping its name and type
  — the most dangerous kind, because no schema diff catches it;
- changing the HTTP status or the `code` returned for an existing failure;
- changing default sort order, or the identity/lifetime of a pagination cursor.

The five bold rules were added by issue #14 alongside the gate that enforces
them. They were always true; nothing stated them, so nothing could be held to
them. `scripts/check_contract_compatibility.py` transcribes **this** list, and
`docs/api/testing.md` records which of these it can and cannot see.

### What is not breaking

- adding a new endpoint;
- adding an **optional** request field, or a new response field;
- adding a new value to `ErrorCode` — clients are required by the contract to
  degrade unknown codes to their HTTP status class;
- relaxing a constraint (widening `maxLength`, removing a `pattern`);
- any change to text in `description` / `summary`.

Adding a value to any **other** enum is breaking by default. `ErrorCode` is the
single exception, and it is an exception only because the contract states the
client's fallback behavior explicitly.

### Deprecation

1. Mark the endpoint or field `deprecated: true` in the OpenAPI document and
   state, in its `description`, what replaces it and the earliest date it may be
   removed.
2. Keep it working, unchanged, for at least **one full release cycle** of
   `EDortta/CodexBridgeMobile` after the mobile client stops using it.
3. Remove it only in a new namespace, never inside `v1`.

A deprecation with no replacement named is not a deprecation, it is a removal
announcement — do not merge one.

---

## Fields that must never ship

The gateway holds data the mobile client must never receive. These are excluded
by the contract itself, not by a filter applied late:

- credentials of any kind — machine tokens, OAuth token values, password hashes,
  the contents of `users.json` or `registry.json`;
- **server filesystem paths.** `ProjectModel.path` is the canonical trap: it is
  the project's real path on the executor and it is an internal field. Projects
  are addressed by `ProjectId` and nothing else. `ArtifactModel.storage_path`
  (issue #11) is the second one: a path relative to `CODEX_BRIDGE_ARTIFACTS_ROOT`,
  never serialized, never composable by a client — the bytes are reached through
  a minted download token, and `gateway/app/services/artifact_storage.py` is the
  only code that turns the stored value into a real file. The migration, the
  model, the artifacts router and the tests all cite *this* section as the rule
  that forbids it, and a council round found the citation pointing at a list
  that did not contain it;
  are addressed by `ProjectId` and nothing else. Same category, same rule:
  `WorkspaceBindingModel.local_path` (issue #73) and
  `DiscoveredResourceModel.resource_path` (issue #73 Stage 3 adoption half,
  `migrations/0014_discovery_resource_key_hash.sql`) — the latter IS the
  candidate's absolute path on the node, not a project id
  (`docs/control-plane.md`, "resource_key é dado sensível"). Both are
  operator-surface-only, exactly like `ProjectModel.path` — and both have
  exactly one exception, both narrow and both administrative-scoped:
  `WorkspaceBindingModel.local_path` has none yet (no endpoint returns it in
  this build); `DiscoveredResourceModel.resourcePath` is returned by
  `GET /api/v1/nodes/{nodeId}/discovered-resources` and the `adopt`/`deny`
  responses ONLY — see "Discovered resources" above for why. CodexBridge
  Control's node-detail screen (issue #73 Stage 5, `GET
  /control/nodes/{nodeId}`) renders that same JSON in HTML instead of
  fetching it a second way — it is the identical, already-excepted
  administrative surface, not a new exception, and the module's own
  docstring names exactly where the path may and may not appear (the escaped
  table body; never a `<title>`, a query string, or a log line). Since 0013,
  `DiscoveredResourceModel.resource_key` itself is no longer the sensitive
  field: it is `hash_resource_key(path)`, a fixed-width lookup key with no
  reversible relationship to the path it was computed from, and it is not
  part of this contract's response shape at all (present in the database,
  absent from every DTO);
- executor hostnames, internal IPs, ports, or anything that would let a client
  reach an executor without going through the gateway;
- raw stack traces and raw driver errors. These map to `internal_error` plus a
  `requestId`; the detail stays in the server log.

The threat model behind these is `docs/threat-model.md`.

**Do not expect existing sanitization to enforce any of the above.**
`shared/security.py:sanitize_log_line` redacts exactly three patterns — `sk-…`,
`ghp_…` and `Bearer …` — as `docs/threat-model.md` already states. Filesystem
paths, executor hostnames, `IP:port` pairs and stack traces pass through it
untouched, and it is applied at one gateway call site only (inbound `task.log`
frames in `gateway/app/main.py`), never to a response body. Any endpoint that
returns log content owes its own redaction; there is no existing net under it.

---

## Probes: live, ready, degraded

`GET /health`, `GET /ready` and `GET /api/version` (issue #3). All three are
unauthenticated — a probe that needs a credential cannot be used before
authenticating, which is the whole point of having them.

- **`/health` touches nothing.** It stays `ok` with the database down. A liveness
  probe that queries a dependency restarts a healthy process because the
  dependency blinked, turning a brief outage into a restart loop.
- **`/ready` checks what a request needs**, and names the failing dependency
  rather than returning a bare boolean. `503` carries the standard `Error`
  envelope plus the same `checks` array, so one parser handles both outcomes.
- **Its result is cached and single-flighted** for
  `CODEX_BRIDGE_READY_CACHE_SECONDS` (floored at 0.5s; a failure is cached for
  only 1s so a blip cannot pin a recovered gateway out of rotation). The lock
  matters as much as the cache: without it a concurrent burst all missed the
  cold cache and all probed, which is the exhaustion the cache exists to stop. The endpoint
  is unauthenticated and unlimited, and each uncached call took a connection from
  the same pool that serves the API: enough concurrent callers exhausted it, real
  requests blocked for the pool timeout, and the resulting error was reported as
  `database: unavailable` — so a flood made the gateway ask the load balancer to
  pull it out of rotation and blame the database.
- **Executor connectivity is not reported by default.**
  `CODEX_BRIDGE_READY_EXPOSE_EXECUTOR_STATE` turns it on. The boolean is a
  presence signal about the operator's own machines and the endpoint is
  anonymous and pollable, so it charts when they are online; `/metrics` is
  already restricted to localhost at the proxy for the same reason.
- **Degraded is not unready.** With executor state exposed, no executor connected
  means new tasks cannot run while every read still works, so that is `200` with
  `status: degraded`. A `503` there would take the API offline exactly when an
  operator needs it to see why nothing is executing.
- **No infrastructure detail leaves these endpoints.** The database check
  swallows its exception: driver errors carry host, port and sometimes the
  password, and `/ready` is unauthenticated. A test asserts the connection
  string never appears in a response.

`/api/version` reports every namespace served, the contract version this build
implements, and capability flags. A `false` flag is an honest report of work not
yet done — it lets a client degrade instead of meeting a 404.
`tests/contract/` asserts the reported contract version equals the document's
`info.version`, because a client that pinned a version has no other way to learn
what the server actually speaks.

Releases must move `gateway/app/version.py` and `pyproject.toml` together;
`tests/unit/test_version_is_single_sourced.py` binds every copy — the settings
default, `FastAPI(version=...)` and the MCP `serverInfo` — to that one constant,
because there were four hand-maintained copies and the release script updated
none of them.

`/healthz` still exists and is unchanged. It is the pre-existing infrastructure
probe, listed in `x-contract-excluded-paths`; the deployment's own checks point
at it and were not migrated by this issue.

### Reaching the API

The gateway is not the front door. `deploy/nginx/frida-codex-bridge.conf` and
`codexbridge-container.conf` are **location allowlists with no catch-all**, so a
route they do not name answers 404 in production however well it works in the
application and however green the suite is.

That is not hypothetical: `/health`, `/ready` and the entire `/api` surface were
implemented, contracted and fully tested while no vhost mentioned them. Every
endpoint of this epic would have been dead at the public host.

**Publishing a route is two edits: the router, and the vhost.**
`tests/contract/test_proxy_routes.py` fails when the contract declares a path no
terminating vhost forwards. Note it reads the configs in this repository — it
cannot know what is installed on the host, so applying them is still a deploy
step the operator performs.

### Rate limiting

`/api/version` carries the limiter and returns `429` with `Retry-After` in the
standard envelope. `/health` and `/ready` do **not**: monitoring polls them on a
timer, and limiting them makes the first symptom of heavy client traffic a red
health check, which points the operator at the wrong thing. `/ready` is protected
by caching instead — see above.

It is a FastAPI dependency, not middleware, and that is mechanical rather than
stylistic: `app.exception_handler` handlers run inside `ExceptionMiddleware`,
which sits *inside* every user middleware, so an `ApiError` raised from
middleware would never reach them and `429` would arrive as a bare framework
response with no `requestId`.

`dependencies=` on `include_router` binds to that router only. A route added
with `@app.get("/api/v1/...")` would be **unlimited**, so "every `/api` route
inherits it" is a claim a comment cannot keep:
`test_every_served_api_route_carries_the_rate_limiter` is what keeps it.

#### Which entry identifies the caller

`CODEX_BRIDGE_API_TRUSTED_PROXIES` lists the addresses or CIDRs of the proxies in
front of the gateway. The client is the **rightmost `X-Forwarded-For` entry that
is not one of them**.

It is not a hop count, and an earlier version of this section said it was.

**Measured on frida, 2026-08-10:** the nginx access log records the caller's
public address in `$remote_addr`, the vhost sets
`X-Forwarded-For $proxy_add_x_forwarded_for`, and the gateway's peer is
`127.0.0.1` — so the header arrives with **one entry** and the correct value is
`CODEX_BRIDGE_API_TRUSTED_PROXIES=127.0.0.1`.

A count was still the wrong mechanism. `deploy/` also carries the dom1 path
(`dom1-codexbridge.conf` → `codexbridge_edge_proxy.py` → frida), which appends
two more entries; the operator has since retired dom1 from serving CodexBridge
— it renews certificates only — but the two configurations remain in the tree
and a chain of a different length is one deploy away. Walking from the right
past the known proxies is correct for any length; a number is correct for one
topology and silently wrong for the next.

`deploy/nginx/codexbridge-container.conf` belongs to that dom1 path and is **not
installed on frida** (its enabled vhosts are `codexbridge-http` and
`codexbridge-https`). If it is ever put back in front of the gateway, its
address has to join the trusted list.

Two guards, both pessimistic on purpose:

- **the immediate peer must itself be a trusted proxy**, or the header is ignored
  entirely. The gateway binds `0.0.0.0`, so anything on the LAN reaches it
  directly and would otherwise write its own identity;
- anything unresolvable — unset configuration, a non-address where the client
  should be, every entry trusted, no header at all from a proxy — falls back to
  one shared bucket rather than to a key built from client-controlled bytes or
  from a proxy's own address.

Leave it **unset** until the addresses are known: the header is ignored, every
anonymous caller shares one bucket, and a warning is logged once. A wrong value
is worse than no value. Addresses are normalized, so `2001:DB8::1` and
`2001:0db8::1` are one bucket rather than two.

### Components declared before they are used

`x-pending-components` lists every component the document declares that no
endpoint references yet, each with the issue that will use it. A component
nothing points at is otherwise indistinguishable from a promise, and a client
may reasonably build against it. Two tests enforce it: an unreferenced component
must be listed with an issue number, and an entry whose component has since been
wired must be removed, so the list cannot become a permanent exemption.

---

## Authentication and authorization (issue #4)

`POST /api/v1/auth/sign-in`, `POST /api/v1/auth/refresh`,
`POST /api/v1/auth/revoke`, `GET /api/v1/auth/me`.

### Sign-in, not device authorization

The issue allowed either. Device authorization (RFC 8628) exists for clients
that cannot show a keyboard; CodexBridgeMobile is a phone app with a text field,
and the gateway already verifies the operator's password for the browser OAuth
flow. A device-code table, a polling endpoint and a verification page would be a
second authentication surface to keep correct forever, serving a client that can
simply ask. `GET /api/version` reports `deviceAuthorization: false`, so the
absence is visible to a client rather than assumed.

The existing OAuth 2.1 + PKCE flow is **not** what mobile uses, and that is not
duplication. It is the right flow for ChatGPT — a third-party client that must
never see the password — and it issues no refresh token at all, which is the
renewal this issue is about. Both flows write to the same token table.

### One credential store

`store.get_oauth_access_token` refuses an expired **or revoked** token, and both
the mobile API and `POST /mcp` authenticate through it. That is why revocation
is a property of the system rather than of one router: a token revoked from the
phone stops driving executors through ChatGPT in the same instant.

### Rotation, and what a replay means

A refresh token is single use. Exchanging it consumes it and returns a new pair;
`refreshTokenExpiresAt` is carried forward unchanged, so a grant has an absolute
lifetime and rotation cannot extend a stolen credential indefinitely.

Presenting a **consumed** refresh token revokes the whole grant. Replay and
theft are indistinguishable from the server side, and the safe reading of that
ambiguity is theft: signing in again is cheap, sharing a session with whoever
holds the copy is not.

Every rotation re-reads `users.json` and intersects — never unions — the grant's
scopes with the account's current ones. A disabled or deleted account ends the
grant at the next refresh rather than at the next expiry, which for a 30-day
refresh token is the difference between minutes and a month.

### Every 401 says the same thing

Absent, unknown, wrong, expired, revoked, or belonging to an account the
operator has since disabled: one status, one code, one message, and
`WWW-Authenticate` on all of them. A distinct "expired" tells a holder of a
stolen token it was once real; a distinct "no such user" turns the sign-in form
into a user directory. `403 permission_denied` is reserved for an actor who *is*
authenticated and is not permitted — the distinction the mobile client branches
on to decide between "sign in again" and "you cannot do this".

**A disabled or deleted account is a `401`, not a `403`.** The credential is
dead and the only recovery is to present another one, which is what 401 means.
It was briefly a 403, on the reasoning that the token itself was still valid;
that made a client show a permissions error and keep a session that could never
work again, and it made `GET /api/v1/auth/me` — the one endpoint whose purpose
is reporting authorization — answer a status its contract does not declare.
On `/api/v1`, `403` comes from `require_action` and from nowhere else.
Asserted by `tests/integration/test_auth.py::test_every_401_on_this_surface_is_the_same_401`
and `::test_a_disabled_account_is_asked_to_sign_in_again_not_told_it_may_not` —
"one message" is a claim that was written in four places and was not true, so
it now has a test under it rather than a docstring.

The same reasoning covers timing, which no response body can hide: an unknown
username is charged the same PBKDF2 derivation as a real one
(`users.authenticate`), at the iteration count read from the registry itself
rather than from a constant that nothing keeps in step with it. The same
function serves `POST /oauth/authorize`, which used to short-circuit and
answered an unknown username 185x faster than a real one.

### What a sign-in token may carry

The account's scopes **intersected with `CODEX_BRIDGE_OAUTH_DEFAULT_SCOPES`**.
Both flows write to the same token table, and `POST /mcp` authenticates against
it, so a sign-in token that skipped the browser flow's cap would be a live MCP
credential carrying scopes the deployment's allowlist exists to withhold. Note
that `roles` still come from `users.json` at request time: stripping
`codexbridge.admin` from a token does not demote an account whose role is
`admin`, and it is not meant to.

### Effective permissions, and why the client must not compute them

`GET /api/v1/auth/me` returns `permissions`: every action this build serves,
with `allowed` evaluated for the caller. A client reads it to decide whether to
**show** a control.

The list is produced from `gateway/app/api/permissions.py:CATALOGUE`, which is
the same table `require_action` enforces on the endpoints. That is the whole
design: a client deriving "may I stop a session" from a scope string would be
re-implementing the server's authorization rules, and the two copies drift the
first time a scope is split — with the client's copy deciding what the operator
sees. `tests/integration/test_auth.py::test_the_report_and_the_endpoints_agree`
calls two different actors against every action that *has* an endpoint and
asserts a `403` exactly when the report says `allowed: false`.

Be precise about the coverage, because the first version of this paragraph was
not: `sessions.readAllProjects` has no endpoint of its own — it is the admin
widening of the two read endpoints — and is covered by
`::test_the_administrative_action_describes_what_the_list_endpoint_does`
instead. The guard that keeps a new action from shipping unchecked
(`::test_every_catalogued_action_is_exercised_below`) names that exemption one
action at a time. It used to exempt the whole `administrative` category, which
meant the next administrative action would have shipped with no parity
assertion at all and a green suite —
`::test_the_guard_flags_a_new_administrative_action` is what now stops that.

Actions carry one of three classes — `read`, `operational`, `administrative` —
so that adding an endpoint forces a reviewer to classify it, and classifying a
cancel as `read` is a visible mistake instead of an invisible one.

**The catalogue lists only actions a served endpoint honours.** Same rule as the
capability flags, for the same reason: `codexbridge.task.submit` and
`codexbridge.task.approve` exist in the MCP transport and in `users.json`, and
no HTTP endpoint offers them yet, so they are absent.

### Schema

`migrations/0003_mobile_auth.sql` adds `oauth_access_tokens.revoked_at`,
`oauth_access_tokens.grant_id` and the `oauth_refresh_tokens` table. Both
columns are nullable with no default: a migration that revoked the installed
base would sign out ChatGPT and the operator at deploy time. `schema_guard`
names the file if a deployment starts without it.

---

## Projects (issue #5)

`GET /api/v1/projects`, `GET .../{id}`, `GET .../{id}/summary`.

A **project** is a `ProjectModel` row: an entry in the gateway registry
(`docs/project-onboarding.md`), addressed by `ProjectId` and never by its
server filesystem path. `ProjectModel.path` is the canonical trap named above
and is excluded from every response this issue adds.

### Counts read one entity, not three

The acceptance criteria ask for counts of "pending decisions, missions, issues,
sessions and recent artifacts". Only `TaskModel` exists today. `pendingDecisions`
(`awaiting_approval` sessions) and `activeMissions` (every non-terminal
session) both read that one table under the vocabulary issues #6 and #7 will
eventually give their own endpoints — they are not new entities, and building
one now would be exactly the speculative expansion `docs/limits.md` rules out.
`issues` (issue #8) and `artifacts` (issue #11) have no backing model at all in
this build and are omitted rather than always reported as zero — a
permanently-zero field is a claim a mobile client can build a UI around and
never see contradicted, the same failure `probes.CAPABILITIES`'s own history
warns about.

### Health is derived from executor staleness, not the raw `connected` column

`ExecutorModel.connected` is set `true` on HELLO/heartbeat and `false` on a
*graceful* disconnect (`AgentHub.unregister`). An abrupt process kill on the
executor side runs neither, and nothing else ever times the column back out —
so a dashboard reading it raw would show a dead executor's project healthy
forever. `store.executor_is_live` instead checks `last_seen_at` against
`settings.reconnect_grace_seconds` (default 120s), which is refreshed on every
heartbeat regardless of which gateway process is holding the socket.

This is used by the new `health` field (`ok` / `degraded` / `unknown` /
`disabled`) and by `ProjectSummary.executors[].connected`. It is **not**
applied to the existing MCP `executor_status` / `list_executors` tools, which
still read the raw column — retrofitting an already-shipped, unrelated surface
is out of this issue's scope; a future issue can converge them.

### `attention` is computed in Python, not pushed to SQL

`health` and `pendingDecisions` are derived at read time, not stored columns,
so the database cannot filter on them the way it filters `q` and `status`.
`?attention=true|false` loads every matching project unpaginated
(`store.list_projects_filtered`) and paginates the filtered result in memory.
The registry this reads is operator-curated and expected to hold at most a few
hundred rows; this is a documented trade-off, not a scalability promise, and
`store.list_projects_page`'s cursor-paginated, database-level query is still
what serves every request that does not set `attention`.

### List and detail are the condensed shape; `summary` adds the executor breakdown

`GET /api/v1/projects` and `GET /api/v1/projects/{id}` return `ProjectStatus` —
health and counts, no per-executor detail, so a list of fifty projects does not
repeat an executor array fifty times. `GET /api/v1/projects/{id}/summary`
returns `ProjectSummary`: the same fields plus `executors[]` (id, staleness-derived
`connected`, `lastSeenAt`) and `generatedAt`, for the one-project dashboard view
that needs the full picture in one call.

### Authorization

Same rule as sessions: project scope is enforced **on the query**, and a
project in a scope the caller cannot see returns **404, never 403**.

---

## Sessions (issue #9)

A **session** is one `codex exec` run — internally a `TaskModel`. The mobile
vocabulary and the internal one differ on purpose: the client should not learn
the word "task" from a URL and meet it again meaning something else in the
issues API.

`GET /api/v1/sessions`, `GET .../{id}`, `GET .../{id}/logs`,
`POST .../{id}/stop`, `POST .../{id}/pause`, `POST .../{id}/resume`,
`POST .../{id}/restart`, `POST .../{id}/explain-error`.

### What #16 adds

`pause`, `resume` and `restart` are implemented for **connected** executors.
They are not optimistic writes: the HTTP response moves the session into a
transitional state (`pausing`, `resuming`, `restarting`) and the stable state
arrives only when the executor acknowledges the control with `task.ack`.

`stop` maps to `task.cancel`, which exists and the MCP client already uses.

### Authorization

Project scope is enforced **on the query**, not on the response: filtering after
loading is how `page.hasMore` ends up describing rows the caller may not see.

A session in a project the caller cannot see returns **404, never 403**.
Confirming that an identifier exists is exactly what probing is for.

An empty `allowed_projects` list means the caller sees nothing; only an admin
means "unrestricted". Collapsing the two is a one-character mistake that grants
everything.

### Logs are redacted on the way out

`shared/security.py:sanitize_log_line` covers three credential patterns and
nothing else. Issue #15 is the live proof that stored log text is not safe: the
executor's own machine token reached the gateway log through a URL query string.

So the log endpoint redacts again as it serialises — credentials in query
strings, absolute filesystem paths, `host:port` pairs — rather than trusting
what was written. Any future endpoint returning log or executor output owes the
same.

### A disconnected executor does not fail a stop

The session is marked cancelled and the executor learns on reconnect, through
the same recovery that already handles a gateway restart. Refusing would leave
the operator unable to stop a session exactly when the executor is unreachable —
which is when they most want to.

---

## Decisions (issue #6)

`GET /api/v1/decisions`, `GET .../{id}`, `POST .../{id}/approve`,
`POST .../{id}/reject`, `POST .../{id}/request-revision`.

A **decision** is not a new domain object. It is a `Session` (`TaskModel`) that
`shared/policy.py:evaluate_task_policy` withheld approval for — the same
`awaiting_approval` mechanism the MCP transport's `approve_codex_task` tool has
resolved since before this API existed. `GET /api/v1/sessions/{id}` and
`GET /api/v1/decisions/{id}` describe the same row from two vocabularies, the
same relationship `docs/api/README.md`'s "Sessions" section already draws
between a session and `TaskModel`.

### Two sources, one inbox (issue #79/#80, WK-20260902-forge-binding, PR B4)

Since PR B4, a decision can also be a **forge write** — a sensitive GitHub
operation (open/comment/close an issue via `gh`) held for the same human gate
a sensitive task already gets, on its own table (`ForgeOperationModel`, never
folded into `TaskModel` — see that model's own docstring for why). The
operator's decision, made explicitly this session: **one inbox**, not two. A
GitHub write and a coding-agent session are not the same kind of thing, so
`decisionType` (`"task"` | `"forge_operation"`) is an honest discriminator on
the `Decision` DTO — but they compete for the same human attention, so they
share the one endpoint rather than splitting into a second decisions surface.

What this did **not** change for a task decision: every field the DTO already
returned keeps its name, its meaning, and its value — nothing removed,
nothing renamed, nothing narrowed. What it added is strictly additive: a new,
always-present `decisionType` plus three forge-only fields
(`forgeKind`/`repoIdentity`/`issueNumber`, `null` for a task), and a widening
of `mode`/`deadline` from non-nullable to nullable (`null` for a forge
decision, which has neither a coding-agent mode nor an expiry — real values
for a task decision as always). A client that never learns about forge
decisions keeps working unmodified; it will start seeing forge rows in its
list unless it filters `decisionType` out, since this endpoint never offered
a "tasks only" mode.

**Id collision is ruled out by construction, not by the odds of a random
`uuid4()` collision.** A forge decision's `id` always carries an explicit
`forge:` prefix (e.g. `forge:3fa85f64-...`); a task decision's `id` is never
touched. A bare `uuid4()` string can never contain a `:`, so the two id
spaces this endpoint serves are provably disjoint. Approving, rejecting or
requesting revision on a forge decision uses the exact same three endpoints,
addressed by that prefixed id — there is no separate set of routes for the
forge source.

**A forge read never appears here.** `issue_list`/`issue_view` are never
gated (`shared.policy.forge_operation_policy_level`: `READ`), so — exactly
like a `READ`-mode task, which also never shows up on this endpoint — they
never reach `awaiting_approval` and are never a decision in the first place.

**Approving a forge decision dispatches, in the same request, for the same
reason issue #20 was a bug for tasks.** `store.decide_forge_operation` +
`AgentHub.dispatch_forge_operation` run exactly where `store.
decide_task_approval` + `AgentHub.dispatch_available` already ran for a task
— an approved forge write this endpoint never told to dispatch would be
issue #20 again, on a different table (`docs/napkin-lessons.md`, 2026-08-21
and 2026-09-02). Same same-request-dispatch revision hazard, same fix: the
row is refreshed after dispatch so the response's `ETag` reflects the
post-dispatch `revision`, not the pre-dispatch one.

### `approve` dispatches in the same request, not on a later event

An `approved` outcome that leaves the task in `waiting_executor` is offered to
its executor before the response returns — `AgentHub.dispatch_available`, the
same mechanism `approve_codex_task` (MCP) now also calls, rather than each
transport hand-rolling `is_connected` + `dispatch_next` + `send` (issues
#18/#20). An offline or already-busy executor is unaffected: the task stays
`waiting_executor` and is picked up the same way it always was — the next
`mark_task_finished` call (issue #17) or the executor's own reconnect.
`reject` and `request-revision` never dispatch; both resolve to `CANCELLED`.

### Every decision this build serves is critical

Approval is withheld only at `PolicyLevel.SENSITIVE`, so `risk` is `sensitive`
on every decision that exists today. The `risk` filter, `DecisionRiskLevel`,
and the confirmation requirement on `approve` are still written against the
general enum rather than hardcoded to that one value, so a future change to
`evaluate_task_policy` that starts holding `controlled_write` tasks for
approval too needs no contract change to be filtered or protected correctly.

### `risk` outlives the decision; `approval_state` does not

`TaskModel.approval_state` is overwritten by `store.decide_task_approval` with
the outcome (`approved`/`rejected`/`revision_requested`) the moment a decision
resolves — it could never have doubled as a persistent risk field, because a
resolved decision would have lost the level it was raised at. `TaskModel.policy_level`
(`migrations/0005_decision_policy_level.sql`) is written once, at creation,
alongside `approval_state`, and is never touched again — `risk` filters and
reports from that column instead.

### `request-revision` still cancels the session

The agent protocol has no message that reopens a task for editing — the same
gap `routes/sessions.py` documents for `pause`/`resume`/`restart` before issue
#16's protocol work landed. So `ApprovalDecision.REVISION_REQUESTED` exists to
make the *outcome* reported to the operator distinct from a plain rejection
("send this back" versus "this will not run"), not to hold the session open
for a resubmission. Presenting anything else would be a control that reports
success and changes nothing.

### Authorization has two layers, not one

`GET` needs `codexbridge.read`, same as sessions. Resolving a decision needs
`codexbridge.task.approve` **and** `can_approve_sensitive` (or admin) on the
account — the same two-part check `gateway/app/mcp/server.py:approve_codex_task`
already applied. Both are enforced from `permissions.is_allowed`, not from a
second check inside the route: `GET /api/v1/auth/me` reports the same function
`require_action` enforces, and a route that checked `can_approve_sensitive`
separately would tell a client "you may" while the endpoint answered `403`.

### The confirmation is separate from `If-Match`

`If-Match` proves the client read the current state; it says nothing about
whether the tap that followed was deliberate. A critical `approve` therefore
also requires `confirm: true` in the body — refused with `validation_failed`
naming `/confirm` otherwise — which is the anti-accidental-action mechanism the
issue asks for. `reject` and `request-revision` carry no such requirement:
declining a sensitive action is the safe direction, and the acceptance
criterion ties the extra step to approving, not to every resolution.

### Idempotency and optimistic concurrency, reused rather than reinvented

Both endpoints follow `routes/sessions.py:stop_session`'s shape exactly:
replay on a repeated `Idempotency-Key` before touching anything, then
`If-Match`, then the state check. A decision already resolved — or otherwise no
longer `awaiting_approval` — answers `409 conflict`, the acceptance criterion
for "resolved or stale decisions"; a `412 stale_write` covers the narrower case
of a concurrent write racing the read that produced the `ETag`.

---

## Missions (issue #7)

`GET /api/v1/missions`, `GET .../{id}`, `GET .../{id}/timeline`,
`POST .../{id}/cancel`, `POST .../{id}/explain`.

### There is no separate mission entity

A **mission** is the same `TaskModel` row `GET /api/v1/sessions` (issue #9)
serves, reframed in mission-control vocabulary. This codebase's domain model
has no dependency graph, no "related entities" table and no execution-progress
percentage, so this issue does not invent them:

- `objective` is the instruction; `assignedAgent` is the executor id — the
  same value `Session.executorId` names, under the name issue #7 asked for.
- `stage` is a coarse three-phase grouping over `state`
  (`store.mission_stage`): `pending` (`queued`, `waiting_executor`), `active`
  (`running`, `awaiting_approval`, and issue #16's `pausing`/`paused`/
  `resuming`/`restarting`), `done` (every terminal state). `state` itself is
  returned unchanged and remains its own, finer filter — the issue asks for
  both, and they are not the same thing.
- `risk` is `shared/policy.py:policy_level_for_mode`, overridden to
  `sensitive` when `approval_state` recorded that a submitted instruction
  matched a sensitive keyword (`store.mission_risk`). It is not a live
  re-evaluation of the instruction text, and for every `TaskMode` value that
  function itself returns, it can only be `read` or `controlled_write` — the
  `sensitive` branch in `policy_level_for_mode` is unreachable for a real
  mode and exists only as a fallback for a future one.
- `blocked` / `blockedReason` is `state == awaiting_approval`, given a machine
  code and a human summary. This is the acceptance criterion ("every blocked
  mission includes a machine-readable reason and human-readable summary") and
  the only condition this build can report: it is the only state a mission is
  held in without the agent protocol having a way to move it forward on its
  own.
- The timeline is `audit_events` rows filtered to the mission's id, oldest
  first, summarized through a per-event-type allowlist rather than the raw
  stored payload — the payload carries fields (`policy_level`, `via`,
  `requested_by_user_id`) never audited for what they may contain, and this
  is public API surface.

`dependencies` and `relatedEntities`, named in issue #7's Scope section, are
**not implemented**. Nothing in this codebase links one task to another task
or to any other entity, so there is no data to expose — and shipping an
always-empty array would be a field a mobile client can build a list UI
around and never see populated, the same failure the capability flags exist
to prevent (see "Rate limiting" → `CAPABILITIES` reasoning above). A future
issue that adds real task dependencies or cross-references should add these
fields then, backed by real data.

### What this issue does NOT deliver, and why

`pause` and `resume` are not mission-control controls, for the same protocol
reason issue #9 gives for sessions: before issue #16's protocol work, nothing
served them; today, `pause`/`resume`/`restart` are session-level lifecycle
controls with no mission-control equivalent, because a mission's `cancel` is
the only command this issue's acceptance criteria named. `cancel` maps to
`task.cancel`, exactly as `stop` does for sessions, and is the one lifecycle
command this API offers for missions.

### Cancel and stop are two doors onto the same lock

`POST /api/v1/missions/{id}/cancel` and `POST /api/v1/sessions/{id}/stop`
both call `store.update_task_state(..., TaskState.CANCELLED)` on the same
row and write the same audit event type, `task.stopped_by_actor` — with
`via` distinguishing which door was used. A mobile client working entirely in
mission-control vocabulary never needs to know `/sessions` exists; a client
already using `/sessions` is not asked to migrate. The two endpoints are
independent implementations (concurrency, idempotency and audit each written
once per router) rather than one sharing a helper, so that this issue does
not touch `gateway/app/api/routes/sessions.py`'s already-tested code path.

**Issue #36's `reason` is a missions-door-only addition, not shared by this
lock.** `/sessions/{id}/stop` still writes `task.stopped_by_actor` with no
`reason` key at all — the two doors are no longer identical, only
"same event type, same row." A client that only ever cancels through
`/sessions` has nowhere to send an operator-typed reason today; issue #36's
own scope (`gh issue view 36`) names only the missions endpoint and
CodexBridgeMobile's mission-control cancel dialog, so extending `/stop` to
match was left out rather than folded in here. If a session-vocabulary
cancel flow ever needs the same field, that is a new issue against
`routes/sessions.py`, not an assumption this section should still make.

### Destructive commands are authenticated and audited

`cancel` requires `require_action(permissions.MISSIONS_CANCEL)` — an
authenticated principal carrying `codexbridge.task.cancel` — and records who
did it (`actor_id`, `actor_email`) in the same audit trail the timeline
reads, same as sessions' `stop`. This is issue #7's acceptance criterion
("destructive commands require authenticated actor context and are
audited").

### An optional cancel reason (issue #36)

`POST .../{id}/cancel`'s body may carry an optional `reason` (free text, up
to 4000 chars) — the operator-typed explanation CodexBridgeMobile's cancel
dialog already collects and, before this, had nowhere to send. It is not a
new column on `TaskModel`: there is no `Mission.cancelReason` field, only the
`reason` this endpoint's own `task.stopped_by_actor` audit event now carries,
the same way `task.decision_resolved_by_actor` already carries a decision's
resolution reason. The mission's timeline (`GET .../{id}/timeline`) surfaces
it in the cancellation entry's summary when present. Omitting `reason`, or
the body entirely, behaves exactly as before — this is purely additive
(contract `1.5.0` → `1.6.0`).

### State-transition validation

`cancel` refuses with `409 conflict` outside `CANCELLABLE`, which is
`shared.protocol.STOPPABLE_TASK_STATES` itself — the same set sessions'
`STOPPABLE` names, reused rather than duplicated (issue #17's review already
caught one local copy of this set silently missing
`paused`/`pausing`/`resuming`/`restarting`; a mission is the same
`TaskModel` sessions cancels, so a second copy here would risk the identical
drift). This is issue #7's acceptance criterion ("state-transition commands
validate the current mission state").

---

## Epics and Issues (issue #8)

`GET /api/v1/projects/{projectId}/epics`, `GET .../issues`,
`GET /api/v1/issues/{issueId}`, `POST /api/v1/issues`,
`PATCH /api/v1/issues/{issueId}`, `POST /api/v1/epics`,
`GET /api/v1/epics/{epicId}`, `PATCH /api/v1/epics/{epicId}`,
`POST /api/v1/epics/{epicId}/issues/{issueId}`.

An **epic** groups issues within one project. An **issue** carries status,
priority, labels, an assignee, dependencies (other issue ids it is blocked on)
and a blocked reason. Both are addressed by `Id` like every other resource in
this contract, never by anything a client would have to unlearn if the backing
system changed.

### This build owns epics and issues; there is no GitHub sync

Every epic and issue returned today was created through this API — `POST
/api/v1/epics` or `POST /api/v1/issues` — never mirrored from GitHub or any
other tracker. `EpicModel.provider` and `IssueModel.provider` are `"local"` on
every row this build writes and are not part of the mobile DTO: they are the
seam a future adapter would use to tell a gateway-authored row from a mirrored
one, the same way `ProjectModel` already mirrors `registry.json` rather than
owning it. Building a `GitHubIssueProvider` with no second caller ahead of an
actual sync requirement would be exactly the speculative architecture
expansion `docs/limits.md` rules out — the column is the whole boundary, on
purpose, until a sync exists to widen it.

### What issue #8 asked for and did not get

"Planning-review metadata and related missions, conversations and decisions"
is in the issue's stated scope and is **not implemented**. No entity named
mission, conversation or decision existed anywhere else in this codebase when
this issue was written, and the issue does not specify their shape, storage,
or relationship to an issue beyond the one sentence naming them. Inventing
three new subsystems to fill that gap would be speculative architecture the
issue itself does not describe, not the smallest durable change it asks for —
and "mission" now separately exists as issue #7's mission-control view of
`TaskModel`, not a new entity, so wiring an `Issue` to *that* is itself a
choice a future issue should make deliberately rather than this one making it
implicitly. A future issue that defines what a "decision" or "mission"
reference from an issue actually means can add it the same way `epicId` was
added here.

### An epic could not itself be changed, and that was a dead end

Before `WK-20260902-epic-update-and-move`, an epic could be created, listed,
read as part of a list page, and linked to — but there was no transport, REST
or MCP, that could change an epic's own `title`, `description` or `status`.
That is not a gap symmetric with issues: this project's answer to "there is no
delete, use `cancelled`" (see `docs/limits.md`) is only an answer if
`cancelled` is reachable, and for an epic it was not. `GET /api/v1/epics/{epicId}`
and `PATCH /api/v1/epics/{epicId}` close it, mirroring `GET`/`PATCH
/api/v1/issues/{issueId}` field for field — `ETag`/`If-Match`, 404 for a
hidden epic never 403, `validation_failed` for an unknown `status` — with the
one difference that follows from the model itself: an epic has no `labels` or
`dependencies` to carry into `UpdateEpicRequest`.

### Two ways to change an issue, on purpose kept to one relationship

`PATCH /api/v1/issues/{issueId}` changes title, description, status, priority,
labels, assignee and dependencies. It deliberately does **not** accept
`epicId`: `POST /api/v1/epics/{epicId}/issues/{issueId}` is the one mechanism
that moves an issue between epics. Accepting `epicId` in both places would be
two code paths that can disagree about what "moving an issue" means and drift
from each other the first time one of them is changed.

The link endpoint requires `If-Match` on the **issue's** current revision,
because that is the entity it mutates. Both the epic and the issue must be in
a project the caller may see, or the response is `404` — never `403`, for the
same reason a hidden session is `404`.

### Dependencies are validated, not just stored

An issue's `dependencies` are other issue ids it is blocked on. `POST
/api/v1/issues` and `PATCH /api/v1/issues/{issueId}` both reject a dependency
that does not name an existing issue in the same project, and reject an issue
depending on itself. This is enforced in `gateway/app/services/store.py`, not
only in the route: a guard duplicated at every future caller is a guard one of
them will eventually forget (`design-standards.md` §3). `epicId` on create is
validated the same way — it must name an epic already in the same project.

### Project scope, same rule as sessions

`projectId` — whether it is a path segment on the list endpoints or a body
field on the two creates — outside the caller's visible projects answers
`404`, never `403`. An unregistered `projectId` and one the caller simply
cannot see are indistinguishable to the caller, by the same probing-prevention
rule `get_task_for_projects` already applies to a single hidden session.

### Actor and history metadata

Every epic and issue records who created it and, once changed, who last
updated it — `createdBy` / `updatedBy` in the response, an email when one is
on record and the user id otherwise. This is the same shape `Session` already
uses for `requestedBy` rather than the `Actor` object `GET /api/v1/auth/me`
returns: one is a single reporter string, the other is a caller's own identity
with a `kind` that is always `user` here, and introducing the second shape for
one field this issue does not otherwise need would be the shape the sessions
precedent already argues against.

### Writes and idempotency

`POST /api/v1/epics`, `POST /api/v1/issues` and the link endpoint all accept
`Idempotency-Key`, the same reserve-then-complete flow `POST
/api/v1/sessions/{sessionId}/stop` uses: a client that lost the network after
creating an issue can retry without risking a second issue. Neither `PATCH`
(issues or epics) carries it — a repeated identical `PATCH` is naturally
idempotent at the field level, and `If-Match` already refuses a retry that
arrived after a concurrent change. The MCP tools this same work_id adds
(`update_issue`, `update_epic`, `move_issue_to_epic`) follow the same split:
the first two carry no idempotency key, `move_issue_to_epic` does, mirroring
the link endpoint it wraps. All three require `expected_revision` — the
JSON-RPC shape of `If-Match` — since an MCP caller must not get a laxer
concurrency contract on the same domain just because JSON-RPC has no header
to forget: absent is `expected_revision_required` (400), stale is
`stale_write` (409), same codes `gateway/app/api/concurrency.py` uses for the
REST `428`/`412` pair, translated to the status codes the `/mcp` JSON-RPC
transport already uses elsewhere (`gateway/app/mcp/server.py`).

### The write scope is separate from cancel

Creating or changing a plan (`codexbridge.issues.write`) and cancelling a
session (`codexbridge.task.cancel`) are different capabilities an operator may
grant separately — see `permissions.ISSUES_WRITE_SCOPE`'s comment. The scope
is now in `Settings.oauth_default_scopes`'s ceiling (`gateway/app/core/config.py`),
which only widens what an OAuth-issued token can ever request; an account
still needs the scope listed in its own `users.json` entry to actually receive
it on sign-in.

---

## Conversations (issue #10)

`GET /api/v1/conversations`, `GET .../{id}`, `GET .../{id}/messages`,
`POST .../{id}/messages`, `POST /api/v1/conversations`.

A **conversation** is a thread linked to at least one product entity. A
**context reference** names the entity: `project` (`ProjectModel`), `session`
/ `decision` / `mission` (all the same `TaskModel` row, under the three
vocabularies "Decisions" and "Missions" above already use), or `issue`
(`IssueModel`, issue #8).

### `artifact` is not a context type

The issue's Objective names conversations "linked to projects, decisions,
missions, issues, sessions and artifacts". Five of those six have a backing
model this build can check a reference against; `artifact` does not —
`ArtifactModel` has not shipped (issue #11) — so a reference of that type
could not be validated for existence or for project visibility, which is
exactly what the acceptance criterion below asks every context reference to
get. Rather than accept an unverifiable reference, `artifact` is omitted from
`ConversationContextType` until issue #11 gives it something to check
against, the same discipline issue #8 applied to "missions, conversations and
decisions" as issue links and issue #7 applied to `dependencies` /
`relatedEntities`: no backing entity, no field. See
`gateway/app/services/conversation_types.py`'s module docstring.

**Issue #11 has now shipped that entity, and the member is still absent.** The
reason changed rather than expired: adding a member to a response enum is a
breaking change (§"What is a breaking change" above), so widening
`ConversationContextType` is a declared change to the conversations surface,
not something issue #11's diff performs on the way past
(`design-standards.md` §7). Whoever wants it adds the member, the resolver
branch through `store.get_artifact_for_projects`, and the test that a
reference to an artifact in an invisible project answers `404` — in one
change, under its own issue.

This does not remove artifacts from the feature: "attachment references
through artifact/file identifiers" is a *message* concept.
`Message.attachments` carries opaque artifact/file ids on each message,
recorded and returned unvalidated for the same reason
`Issue.dependencies` records ids without this build owning a dependency
graph — and is unaffected by the restriction above.

### Every context reference is resolved and authorization-checked, not just stored

`POST /api/v1/conversations` resolves each `context` entry through the same
`*_for_projects` getter its analog already uses — `get_project_for_caller`,
`get_task_for_projects`, `get_issue_for_projects` — the same functions
`GET /api/v1/sessions/{id}` and `POST /api/v1/epics/{epicId}/issues/{issueId}`
already rely on to make a hidden resource indistinguishable from a
nonexistent one. A context reference the caller cannot see therefore answers
`404`, never a `400` that would confirm the id exists to someone who was not
given it — issue #10's acceptance criterion ("unauthorized entity references
are rejected without disclosing hidden resources") verbatim.

There is no independent `projectId` field on the create request. The
conversation's project is *derived* from `context`: every reference must
resolve to the same project, or the request is rejected with
`400 validation_failed` / `mixed_project`. A conversation is always about one
project's worth of work, the same assumption every other collection in this
API already makes.

### Unread and last-activity, without a "mark as read" endpoint

Issue #10 names no such endpoint, so `ConversationReadStateModel` can only
move as a side effect of an endpoint that already exists:

- `GET .../messages` advances the caller's cursor to the newest message
  **actually returned in that page**, not to "now". A client paging forward
  from the oldest message must not have later, unfetched messages marked
  seen just because an earlier page was fetched.
- `POST .../messages` advances the sender's own cursor to the message just
  sent, so posting never leaves the sender's own conversation reported back
  to them as unread.
- `POST /conversations` marks its creator caught up immediately — they were
  just looking at what they wrote.

`unread` is therefore a field that genuinely changes, in both directions,
under exercise by this build's own endpoints — not a flag that can only ever
read one way, the same discipline `probes.CAPABILITIES` and issue #7's
dropped `dependencies` field are already held to elsewhere in this document.
An empty conversation (`lastActivityAt: null`) is never unread, for anyone.

### Ordering: the conversation list is stable, never "most recent first"

`GET /api/v1/conversations` orders by `createdAt`/`id` — creation order —
**never** by `lastActivityAt`. Sorting by an activity timestamp would move a
conversation's position in the list the instant a new message lands, which
can skip or repeat rows across a client's paginated walk: the direct opposite
of this issue's own acceptance criterion ("pagination preserves stable
ordering"). `lastActivityAt` is still reported on every item, for a client
that wants to sort the page itself.

`GET .../messages` is oldest-first — the order a thread reads in, the same
reasoning `GET /api/v1/missions/{id}/timeline` already gives for a mission's
timeline, and unlike every newest-first collection elsewhere in this API.

### No `revision`, no `ETag`, no `If-Match`

Every other writable entity in this contract publishes a monotonic
`revision` because something can mutate it out from under a concurrent
reader. Nothing here can: a conversation is never edited after creation (no
`PATCH`), and a message is immutable once posted. `ProjectModel` is this
contract's other GET-only, revision-less entity, for the same reason — see
"Optimistic concurrency" below, which this section is a deliberate exception
to, not an oversight.

### Idempotency, reused rather than reinvented

`POST /api/v1/conversations` and `POST .../{id}/messages` both accept
`Idempotency-Key` and follow `POST /api/v1/issues`'s reserve-then-complete
shape exactly, including the same convention
`POST /api/v1/epics/{epicId}/issues/{issueId}` established: the idempotency
record's `endpoint` is the literal route template, not the path with the
concrete id interpolated in — the fingerprint (which does embed the
conversation id and body) is what tells a key reused for a genuinely
different operation apart from a legitimate retry, so a same-key,
different-fingerprint call is answered `409`, never silently replayed. This
is issue #10's "message creation is idempotent for offline retries"
acceptance criterion, and the mechanism that also prevents the duplicate
messages the issue's own test coverage requirement names.

---

## Artifacts, downloads and Android builds (issue #11)

`GET /api/v1/artifacts`, `GET .../{artifactId}`,
`POST .../{artifactId}/download-token`, `GET .../{artifactId}/download`,
`GET /api/v1/builds/android`, `GET .../{buildId}`.

An **artifact** is a retained file this gateway can hand to
CodexBridgeMobile: type, project, name, version, size, origin, checksum,
creation time and retention window. An **Android build** is not a second
entity — it is an artifact of type `apk` plus its APK metadata, keyed by the
artifact's own id, so `GET /api/v1/builds/android/{buildId}` takes an
`ArtifactId` and a client never holds two identifiers for one file.

### Nothing in this build produces an artifact

There is no ingestion path: no executor message, no upload endpoint, no build
hook writes an `artifacts` row. Every artifact this API can serve was created
by a direct call to `store.create_artifact`, which today means a test fixture
or an operator script. Ingestion is a future issue; the catalogue, the
authorization and the download lifecycle are this one's.

That is said out loud for the same reason "Counts read one entity, not three"
is: a mobile client reading these endpoints on this deployment gets an empty
list, and an empty list is worth knowing the reason for.
`capabilities.artifactDownloads` is `true` because the **endpoints are
served**, not because artifacts exist — the flag answers "does this server
speak the artifact API", which is the question a client that would otherwise
meet a `404` is asking.

### The bytes are not behind the session token

`POST .../{artifactId}/download-token` mints a short-lived bearer credential
for exactly one artifact. `GET .../{artifactId}/download` accepts **that**
credential and nothing else: it never looks at a session token and never
consults the permission catalogue.

The split exists because the phone does not do the transfer. Android hands a
multi-megabyte download to the system downloader — a separate process with no
access to the app's session — and giving it the session bearer would put the
credential that can approve a sensitive task into a component whose only job is
fetching a file.

**The credential travels in `Authorization: Bearer`, never in the URL.** The
design note for this issue floated `?token=…`; this codebase has already been
burned by exactly that (issue #15: an executor's machine token reached the
gateway log through a query string) and `security-standards.md` §2 forbids it —
a query string reaches access logs, proxies, browser history and `Referer`. So
the mint response carries a *path* with no credential in it, and the token
separately.

Five things narrow the credential, each named with the test that pins it —
`gateway/app/api/routes/artifacts.py` carries the same list, and the two must
not drift:

- **bound to the artifact** — presenting it on another artifact is refused, so
  a token for a public report cannot fetch a signed APK
  (`test_artifacts.py::test_a_token_minted_for_one_artifact_is_refused_on_another`);
- **bound to the minting account, re-read at download time** — an account the
  operator disables (`::test_a_token_whose_account_was_disabled_stops_working`)
  or narrows (`::test_a_token_stops_at_the_projects_the_account_still_has`)
  after minting cannot still pull the bytes. Same rule refresh rotation already
  applies to a grant;
- **expires in minutes** — `CODEX_BRIDGE_ARTIFACT_DOWNLOAD_TOKEN_TTL_SECONDS`,
  default 300, clamped to `[30, 3600]`
  (`::test_an_expired_token_is_refused_with_the_typed_error`);
- **dies with the sign-in that minted it** — `POST /api/v1/auth/revoke` deletes
  the download tokens of that grant, because a sign-out that leaves an APK
  streaming is the failure that endpoint exists to prevent
  (`test_auth.py::test_signing_out_kills_a_download_token_minted_before_it`).
  Scoped to the **grant**, not the actor: signing out of ChatGPT must not abort
  a transfer the phone started, and an unauthenticated replay of a dead refresh
  token must not reach a live grant's credentials;
- **stored hashed** — through the same `shared.security.hash_token` the OAuth
  access tokens use, so a reader of the database cannot download anything
  (`::test_the_download_token_is_never_stored_in_the_clear`).

Every refusal on the download endpoint is the same `401` with the same message
— absent, unknown, expired, minted for another artifact, belonging to an
account since disabled or narrowed, or killed by a sign-out. Distinguishing
them tells a holder of a token they were never given whether it was ever real,
and which artifact it was for. A revoked token's row is *deleted*, so it
reaches the endpoint as "unknown" and needs no branch of its own.

**A `401` here means "mint a new download token", not "refresh the session".**
Everywhere else on this API it means the second thing, so a client running its
usual refresh-and-retry interceptor on this response will loop. The contract
says so in two machine-readable places: the operation declares its own
`artifactDownloadToken` security scheme rather than `bearerAuth`, and its `401`
is `DownloadTokenRejected` rather than the shared `Unauthenticated`.

### The token is deliberately not single-use

Issue #11 asks for range and resumable downloads in the same breath as
short-lived authorization, and those two pull in opposite directions. A token
consumed by the first request makes a resumed transfer impossible: the
downloader would have to re-authenticate mid-stream, which is the thing this
endpoint exists to avoid. **The lifetime is the control**, and it is short for
that reason. `test_a_token_survives_reuse_inside_its_lifetime` pins the choice
so it stays a decision on the record rather than becoming an accident.

### Range requests

A single `bytes=` range is honoured: `206` with `Content-Range` when it is
satisfiable, `416` with `Content-Range: bytes */<size>` when it is well formed
and starts past the end. Anything else — an unknown unit, a malformed value,
more than one range, an inverted range — is **ignored** and the whole
representation is served with `200`, which RFC 9110 §14.2 explicitly permits.
Answering `416` to a header a client sent speculatively would break that client
for no gain.

### Retention is load-bearing, not a decorative timestamp

Past `retainedUntil` the catalogue still lists the artifact — a client showing
a stale entry deserves an explanation rather than a mystery `404` — and reports
`retained: false`. Minting a token and serving the bytes both answer `409`. A
retention field that only ever described something would be the always-null
field this document refuses to publish, and `retained` is computed from the
server's clock because a client comparing timestamps would disagree with the
server that actually refuses the download.

### Checksums and signing metadata come before the download

`sha256` is on every artifact in the list, on the detail, and on the mint
response. `android.signingFingerprint` is on every APK in the list and the
detail — **not** on the mint response, which carries only what a downloader
needs to fetch and verify bytes (`sizeBytes`, `sha256`, `contentType`). An
earlier cut of this paragraph said "all three"; a council round checked the
response and it has no `android` block, so a client reading the signer from it
would have got nothing. Read the fingerprint from the catalogue, which is where
the decision to download is made anyway. That is
issue #11's acceptance criterion read literally: *before* download or install
means in the catalogue, not only in the transfer, because a client decides
whether to start a 60 MB download from what the list already told it. The
download itself repeats the digest in `X-Artifact-Sha256`, unchanged by
`Range`, so a client streaming to disk can verify without holding the
catalogue response.

A certificate fingerprint is public by construction and is not a credential:
publishing it is what lets an operator refuse an APK signed by anything other
than their own key.

### The stored path never leaves the server

`ArtifactModel.storage_path` is this table's `ProjectModel.path` — see
§"Fields that must never ship". It is relative to `CODEX_BRIDGE_ARTIFACTS_ROOT`
and is excluded from every response by construction, not by a filter applied
late. `gateway/app/services/artifact_storage.py` is the only code that turns it
into a real file, and it checks confinement twice:

- **lexically, at the write** — an absolute path, a backslash, a colon, a `..`
  or `.` segment, an empty segment or any character outside
  `[A-Za-z0-9][A-Za-z0-9._-]*` is refused, so a traversing path never enters
  the table;
- **after resolution, at the read** — the candidate and the root are both
  resolved and anything landing outside the root is refused. `Path.resolve`
  follows symlinks, which is what catches a link planted inside the root
  pointing at `/etc/shadow` — something no amount of string checking can see.

A confined path with no regular file behind it is a typed `404` that names the
artifact and never the path. Same answer for a path that stopped resolving
inside the root: the caller has no business learning that a path exists at all,
and the operator has the `requestId`.

### Authorization

Two catalogued actions, both at read scope: `artifacts.read` (list and read,
including the Android endpoints) and `artifacts.download` (mint a download
token). They are separate even though both require `codexbridge.read`, because
a client decides whether to show a Download control separately from whether to
show the catalogue — the same relationship `sessions.read` and
`sessions.readLogs` already have. `GET /api/v1/auth/me` reports the split, so a
deployment that later withholds bytes while still showing metadata needs no
client change.

Project scope is the same rule as sessions and conversations: applied to the
query, never to the loaded rows, and an artifact in a project the caller cannot
see answers a `404` that is byte-identical to the answer for an id that does
not exist.

### Deploy needs migration 0010

`migrations/0010_artifacts.sql` creates `artifacts`, `android_builds` and
`artifact_download_tokens`, plus the three indexes the catalogue's ordering and
the token sweep read. Apply it with `python3 scripts/apply_migrations.py`.

`schema_guard.REQUIRED_TABLES` names all three, and **that is documentation, not
a boot gate** — a council round checked. `gateway/app/main.py` runs
`Base.metadata.create_all` one statement before `check_schema`, and all three
tables are declared on `Base`, so a gateway started against a database missing
them creates them itself and the guard sees them present. This is true of every
one of `REQUIRED_TABLES`' entries, not just #11's, and
`tests/unit/test_schema_guard.py::test_required_tables_cannot_fire_at_boot_today`
pins it so this paragraph cannot quietly become false again.

What that costs, concretely: a deployment that skips the migration runs on the
`create_all` schema instead of the shipped one — **no indexes**, a `content_type`
column without its default, and no `schema_migrations` row for 0010, so a later
migration's bookkeeping starts from a wrong premise. Nothing warns. Whether
`check_schema` should move ahead of `create_all` (or `create_all` stop covering
migration-owned tables) is a change to how every migration in this project is
gated, not something issue #11 decides on the way past — it is flagged for the
operator in `docs/issues/011-artifacts-downloads-apk/RESUME.md`.

## Events and notifications (issue #13)

`GET /api/v1/events/stream` (Server-Sent Events), `GET /api/v1/events` (the
same events as an ordinary paged read), and `GET`/`PUT
/api/v1/notifications/preferences`.

### Why SSE, and why the polling endpoint is not a consolation prize

SSE rather than WebSocket for three reasons, none of them "we had no
WebSocket" — the gateway already speaks one at `/agent/ws`:

- **Authentication.** Everything on this contract authenticates with
  `Authorization: Bearer`. A browser or mobile WebSocket cannot set that
  header on the handshake, so a WebSocket stream would need a second
  authentication scheme: a token in the URL (forbidden — see
  `.docs/agents/security-standards.md`) or a bespoke post-handshake auth
  frame. SSE rides the scheme that already exists.
- **Resume is in the transport.** `Last-Event-ID` is part of SSE. Issue #13's
  "resume from the last acknowledged event" is the mechanism SSE was designed
  around, with no application protocol on top.
- **One direction is all this needs.** Nothing here asks the client to send
  anything on the channel.

`GET /api/v1/events` delivers the *same* events with the *same* ids. A client
on a network that kills long-lived connections, or one in a background state
where the platform will not hold a socket open, polls it and loses nothing.
Both transports are first-class, and a client may move between them mid-stream
because the position means the same thing on both.

### The resume position is a public integer, not a cursor

Every other collection here pages with an opaque signed cursor. This one does
not, and that is deliberate rather than an oversight: the position is
`Last-Event-ID`, which SSE puts on the wire and the client sends back
verbatim. Wrapping the same position in an opaque cursor for the polling
endpoint would publish two names for one place and make the two transports
incompatible — a client could not hand a stream position to the fallback. The
same reasoning `GET /api/v1/sessions/{sessionId}/logs` already applies to an
append-only log.

The id is monotonic but **not contiguous**: the underlying log also holds
records that are never delivered as events. A skipped number is not a lost
event. Loss is reported explicitly, and only explicitly — see below.

`page.nextAfter` is the last id the page **loaded**, not the last id it
returned. With a `type` filter the two differ, and reporting the last returned
id would make the next request re-scan rows the filter already rejected —
forever, when nothing in the tail matches.

### No silent loss, in both directions

Resume is `id > position`, so an event cannot be delivered twice or skipped
while its record exists. The only way to lose one is for the record itself to
be gone, and that is announced rather than papered over: the stream emits a
`stream.gap` frame **before** delivering anything, and `GET /api/v1/events`
returns a `gap` object beside its items. Delivering first and mentioning the
gap afterwards would let a client act on a partial view believing it was
continuous.

Two reasons, and the second one matters as much as the first:

- `beyond_retention` — the position's record is gone and the log moved past
  it. `oldestAvailableId` says where to restart, because "you lost some" with
  no position leaves a client guessing.
- `cursor_ahead` — the position is beyond anything this log has ever held: a
  position from another deployment, or a database restored from a backup older
  than the client. Unsignalled, the stream would simply never deliver again,
  which is the same silence in the other direction and much harder to diagnose
  from a phone.

Note what this build's retention actually does:
`store.purge_expired_audit_events` deletes authentication rows and nothing
else, so no domain event has ever been purged here and `beyond_retention`
cannot be reached today. The signal exists so that a future retention policy
over domain rows — an operator's decision, not this code's — cannot cause a
silent loss the day it is switched on.

### Authorization is by project, and it is re-checked while the stream runs

A stream opened at 09:00 and still open at 17:00 authorized once, and
everything after that was delivered on an eight-hour-old decision. This one
re-resolves the bearer token on **every poll**: a revoked token, an expired
token, a disabled account and a project removed from the actor's
`allowedProjects` all take effect within one poll interval. The first three end
the stream with `stream.closed` and `reason: unauthenticated`; the fourth
simply stops delivering that project. **A client must not treat an open
connection as proof it is still authorized.**

Project scope is enforced on the query, like everywhere else here, so a page is
never a filtered-down view of rows the caller was allowed to load. `?project=`
only ever *narrows*: naming a project outside `allowedProjects` matches
nothing.

An event whose project cannot be derived is delivered to **nobody**,
administrators included. `audit_events` has no project column — a row's project
comes from the entity it names — and an event that belongs to no project cannot
honestly be shown as belonging to one. Fail closed: an entity type nothing
teaches the derivation about is invisible until someone does.

### Authentication and security events are not on this surface at all

Sign-in, failed sign-in and credential revocation are recorded in the same
audit log these events are derived from. They are **excluded by construction**,
not by a filter someone has to remember: they carry a user id where a project
would be, so they are outside the set of entity types this surface can deliver.
Streaming them would tell any token holder — including one belonging to a
different person — when the operator signs in. Notification-preference changes
are excluded the same way.

### The summary is a whitelist; the stored payload never ships

The internal audit payload is written by thirty-five call sites that were never
audited for what they may contain: `actor_email`, `requested_by_email`,
free-text `reason` and `error` strings from an executor, `context` blobs.
§"Fields that must never ship" applies to every byte of it and no existing
sanitizer covers a response body.

So it is never passed through. Each event type names the handful of payload
keys it may read, free text goes through the same `redact` the session-log
endpoint uses and is truncated to a notification line, and a key nobody
whitelisted does not leave the process. Adding a field to an audit payload
therefore cannot leak it — the default is exclusion. Treat `summary` as a
notification line, never as data: fetch the entity for authoritative state.

### One change is one event, not three

A session, a mission and a decision are three vocabularies over the same
underlying row (§"Missions (issue #7)"). This surface does not triple every
event to match. It emits one, with `entity.kind` naming the vocabulary that
fits what happened — `decision` for the approval lifecycle, `session` for the
run's own — and the id is the same id, so `GET /api/v1/sessions/{id}` and
`GET /api/v1/missions/{id}` both accept it.

One audit record forks on its content: a submission held for approval is a
`decision.requested`, and every other submission is a `session.created`. Both
are the same recorded row, so the fork lives in one place rather than in a
second writer nobody would remember to call.

### `MobileEventType` is closed, and already declares what #11 will emit

A client may switch over it exhaustively, which makes adding a value a
breaking change under §"What is a breaking change". `artifact.created`,
`artifact.updated` and `androidBuild.status_changed` are therefore declared
**now**, by a build that produces none of them — there is no artifact or
Android build record until issue #11. Declaring them costs a client nothing
(they never arrive) and saves a `v2` when they do. A `?type=` filter naming one
is accepted and matches nothing, rather than answering `400`; rejecting it
would make the declared values unusable, which is the opposite of why they were
declared.

### Notification preferences are a hook, not a filter

`GET`/`PUT /api/v1/notifications/preferences` is one document per actor,
always the caller's own — there is no `userId` parameter and no administrator
override, because a preference document is personal data and an endpoint that
could read another account's would be a disclosure with no product behind it.

**There is no push transport in this build.** `pushDeliveryAvailable` is
`false` and nothing reads these rows to decide delivery. They are stored so the
choice survives a reinstall and so a later push integration has something to
read.

**They do not filter `GET /api/v1/events/stream`.** A client that opened the
stream asked for the stream; withholding events from it because of a preference
set on another device is how a phone silently misses the decision its operator
was waiting for — and the failure would be indistinguishable from a quiet
system. Narrow a live connection with that endpoint's `?type=` instead, which
is per-connection state and cannot change underneath it.

**A session that predates the scope grant keeps a token that cannot write.** A
principal's scopes are snapshotted into the token row at sign-in, and
`POST /api/v1/auth/refresh` rotates with `granted & user.scopes &
server_allowlist` — an intersection, so it can only ever narrow. Adding
`codexbridge.notifications.manage` to an account therefore does **not** reach a
phone that is already signed in: it keeps answering `403` on this endpoint,
through every refresh, until the absolute session lifetime expires or the user
signs in again. That is the deliberate behaviour of a rotation that never
escalates — a stolen refresh token must not be able to widen itself — and the
cost is stated here rather than discovered. An operator granting a new scope to
an existing user should expect to tell them to sign in again; a client seeing
`403` on an action `GET /api/v1/auth/me` also reports as not allowed should
offer re-authentication, not an error.

`PUT` is a whole-document replacement, so it is idempotent by construction:
there is no `Idempotency-Key` (nothing to duplicate) and no `ETag`/`If-Match`
(the only writer of a row is the actor it belongs to, so there is no concurrent
third party for an optimistic check to protect against — the same reasoning
§"No `revision`, no `ETag`, no `If-Match`" gives for conversations). Reading
needs only `codexbridge.read`; writing needs
`codexbridge.notifications.manage`, separate on purpose so an operator can
grant a phone the stream without granting it the ability to rewrite what the
account is notified about.

### Limits, and what the rate limiter does not bound

The limiter counts requests per window. One accepted request to
`/events/stream` becomes a connection held open for minutes that takes a
database session on every poll, so the endpoint that is cheapest per request is
the one that can exhaust the pool the rest of the API shares. The gateway
therefore bounds how many streams it holds open at once and answers `503` with
`Retry-After` at that ceiling — refusing rather than queueing, because a
refused client reconnects with its `Last-Event-ID` and loses nothing while a
queued one holds the connection it was refused for. Each stream's lifetime is
bounded too, and ends with `stream.closed` and `reason: max_duration`; every
ending is a reconnect, and every reconnect is exact.

`?type=` is validated before the first byte. Once a `text/event-stream` body
has started there is no status code left to change, and a client that
misspelled a filter would otherwise see an open, empty, permanently silent
connection instead of a `400`.
## Nodes and enrollment (issues #73, #76)

`GET /api/v1/nodes`, `GET .../{nodeId}` are issue #73 Stage 2's fleet-visibility
surface — see `NodeStatus` and `gateway/app/api/routes/nodes.py`'s own docstring
for what they report and why they are administrative rather than
project-scoped. This section covers issue #76's minimal cut on top of that:
`POST /api/v1/nodes/invite`, `POST /api/v1/nodes/enroll`, and
`POST /api/v1/nodes/{nodeId}/revoke`.

### What existed before this cut, in writing

Admitting a machine meant hand-editing `registry.json`, inventing a machine
token in clear text, and restarting the gateway for it to load. `/agent/ws`
closed `4404` for any `executor_id` not already in that file. "Revoking"
access meant deleting the line and restarting — and a socket that was already
open when the operator did that kept working regardless, because nothing ever
told it to stop. Each of the three routes below closes one of those gaps.

### The invite is a bearer secret with a short TTL, not a bound identity

`POST /api/v1/nodes/invite` mints a token, stores only its hash
(`NodeInviteModel.token_hash`), and returns the raw value **once**, in the
response body. It is never written to `audit_events` and never logged. The
token is valid for 15 minutes and exactly one redemption; it is not bound to
any claimed hostname or machine identity. A hostname is mutable and
spoofable — `migrations/0009_control_plane.sql` already refused to trust one
for node identity — so the TTL is the actual boundary, not the binding.

### `POST /api/v1/nodes/enroll` carries no bearer token

Every other endpoint in this contract requires `Authorization: Bearer`. This
one cannot: the node redeeming the invite has no credential of its own yet —
minting its first one is the point of the call. The invite itself is the
gate, checked the same way an OAuth authorization code is
(`store.enroll_node`, mirroring `consume_oauth_authorization_code`): unknown,
already-consumed and expired all answer identically
(`400 validation_failed`), so a probing, unauthenticated caller cannot tell
which reason applied. Rate-limited the same way, and with the same shared
limiter instance, as `POST /oauth/authorize`'s submit route — the only other
endpoint in this codebase that mints a credential for a caller with no
principal.

The response's `machineToken` is shown once, the same rule as the invite
token. `scripts/enroll_node.py` is the reference client: it calls this
endpoint and writes the token straight to a local file with `0600`
permissions, so an operator never has to copy a secret into `.env` by hand.

### The node's id is generated by the gateway, never accepted from the caller

An unauthenticated endpoint that let the caller choose the new node's id
would let anyone holding a live invite collide with an existing node's row.
`nodeId` in the response is a fresh id `enroll_node` generates; `displayName`
is caller-supplied and may repeat.

### Revoking closes the socket in the same request

`POST /api/v1/nodes/{nodeId}/revoke` sets `admissionState` to `revoked` and
`enabled` to `false` on both the node and its bound executor, **and** closes
a live connection if one is open right now (`AgentHub.force_close`), before
the response returns. `connectionClosed` in the response says whether there
was actually a socket to close. Splitting revoke into "stop the next
handshake" and "close what is open" as two separate operator actions would
leave a window where a socket open at the moment of the decision keeps
working — issue #76 names that in writing as the reason "revoking" the old
way was theatre. Revoking does **not** touch the node's local checkouts; the
files on that machine remain an operator concern on the machine itself.

### `admissionState` is not `enabled`

`NodeStatus.admissionState` (`enrolled` or `revoked` in this cut;
`invited`/`suspended` are anticipated but not written yet) is *why* a node
may or may not be dispatched to. `enabled` is *whether* it may be right now.
The two move together on a revoke, but they answer different questions:
`/agent/ws`'s handshake gates on `admissionState` specifically, so a later
reason to disable a node without revoking its credential is not forced to
reuse revocation's enforcement path.

### Authorization

`nodes.invite` and `nodes.revoke` are both administrative
(`codexbridge.admin`), the same posture as `nodes.read` — fleet-wide, no
per-project scope to key off of. `nodes.enroll` has no action: the endpoint
takes no principal at all.
## Discovered resources (issue #73 Stage 3, WK-20260902-gh73-discovery-adoption)

`GET /api/v1/nodes/{nodeId}/discovered-resources`,
`POST /api/v1/discovered-resources/{resourceId}/adopt` and
`POST .../{resourceId}/deny`. The panel's half of "the node proposes, the
panel adopts" (`docs/control-plane.md`): the report half (Stage 3's other PR)
writes only `discovered_resources`; this half is the only REST surface that
may turn a row there into a `ProjectModel`, a `WorkspaceBindingModel`, a
`ScmAssociationModel`, or a `project_authorizations` grant.

### Administrative, not project-scoped — reason, not just form

A discovered candidate is not scoped to any project the caller already sees;
often none exists yet, which is the whole point of the adoption decision. Both
actions (`nodes.discoveries.read`, `nodes.discoveries.decide`) therefore
follow `nodes.read`'s precedent: `codexbridge.admin`, fleet-wide, never
`visible_projects`-scoped. Deciding is a separate action from reading for the
same reason `decisions.read`/`decisions.decide` are separate: seeing the queue
and deciding it are capabilities an operator may grant independently.

### Why `resourcePath`/`rootPath` are allowed on the wire here

"No response exposes a server filesystem path" (this document's own
conventions, and "Fields that must never ship" below) has exactly one standing
exception, pre-registered by the report PR before this one existed
(`docs/control-plane.md`, "resource_key é dado sensível... quando a rota de
adoção existir, cai na mesma regra de local_path"): this endpoint, and only
this endpoint, because an operator deciding whether to adopt a candidate
cannot decide from an opaque id — they need to see which directory it is. The
exception is narrow on purpose: gated by the same administrative scope as
every other node-fleet field, and not extended to any other DTO on this
contract. `ProjectStatus`, `Session`, `Mission` and every MCP tool still never
carry it.

### Why `resourcePath` exists at all, distinct from `resourceKey`

`discovered_resources.resource_key` was written, from Stage 3's report PR
through `migrations/0014_discovery_resource_key_hash.sql`, as the candidate's
raw absolute path — up to 2048 characters — into a column declared
`varchar(255)`. SQLite never enforced that width (type affinity, not a
constraint); MySQL, a declared target via `aiomysql`, does, so a long enough
path was an unhit insert failure. `resource_key` is now
`shared.security.hash_resource_key(path)` — a fixed-width lookup key, never
part of this contract's response — and `resourcePath`, a new, unindexed
column, carries the actual path instead. See `hash_resource_key`'s own
docstring and that migration's comment for why widening the original column
was rejected in favor of hashing.

### `adopt`: exactly one of `projectId`/`newProject`, and two grant origins that can coexist

`grantCapabilities` in the request body is the operator's explicit grant,
recorded `grantedBy: "operator:<userId>"`. Separately, when the candidate's
`rootPath` string-matches a `DiscoveryRoot` on the node's own registration
that carries `autoAuthorize`, that grant is applied too, recorded
`grantedBy: "root-config:<path>"`. Both can apply in the same call — the
underlying `project_authorizations` table allows exactly one row per
`(nodeId, projectId)` (`0009_control_plane.sql`), so the two origins merge
into one row rather than racing that constraint, and `grantedBy` becomes a
`;`-joined set naming every origin that contributed. Neither `autoAuthorize`
nor a node's own configuration can ever reach `modify`/`deliver` —
`shared.protocol.AUTO_AUTHORIZABLE_CAPABILITIES` caps it to `read`/`test`,
enforced when `DiscoveryRoot` is parsed, before any node connects. Only an
explicit `grantCapabilities` naming a human operator can grant those two.

### A node cannot reach `adopt`/`deny` — structurally, not by convention

Both routes require `nodes.discoveries.decide` (`codexbridge.admin`), which
`gateway/app/api/auth.py:current_principal` grants only to a caller presenting
an OAuth access token. The executor WebSocket
(`gateway/app/main.py:agent_ws`) authenticates with a `machine_token`, checked
independently in `main.py` and never turned into an `AuthenticatedPrincipal` —
there is no code path from a connected node's credential to either endpoint.
Issue #73: "a node cannot grant itself project authorization merely by
reporting a discovery" — this is the one door into `project_authorizations`
this build has, and only a human can open it
(`tests/integration/test_discovery_routes.py::
test_a_principal_without_the_administrative_scope_cannot_adopt`,
`tests/unit/test_discovery_store.py::
test_a_matching_auto_authorize_root_grants_nothing_from_a_report_alone`).

### `adopt`/`deny` require a decidable state, and that is what prevents duplication

Only `discovered`/`stale` may be adopted or denied; a candidate already
`adopted`/`authorized`/`denied` answers `409 conflict`. This is not a
defensive check layered on top of the write — it IS what keeps a repeated
`adopt` from creating a second `WorkspaceBindingModel` or
`ScmAssociationModel` for the same candidate: the second call never reaches
the write at all.

### No `revision`, no `ETag`, no `If-Match`

`DiscoveredResourceModel` carries no revision column — same posture
`Conversations` above documents for its own GET-only shapes, extended here to
a row two POST endpoints do mutate: `adopt`/`deny` are one-shot state
transitions guarded by the decidable-state check above, not a general-purpose
update a concurrent writer could race meaningfully. `Idempotency-Key` is what
protects a retry instead, the same shape `POST /api/v1/issues` established.

---

## Authorizations (issue #73 Stage 4, WK-20260902-gh73-authorization-plane)

`POST /api/v1/nodes/{nodeId}/projects/{projectId}/authorize` and
`.../revoke`. The explicit-operator half of writing `project_authorizations`
— separate from discovery adoption (previous section), which is the other
place that table gets written. This is also the FIRST build whose
enforcement actually reads that table: `store.effective_task_modes`, called
from `store.create_task` at the exact spot its old inline `allowed_modes`
check lived, and the executor's own independent mirror in
`agent/codex_bridge_agent/service.py:_handle_dispatch`. A grant made through
either surface takes effect the next time a task is submitted for that
`(node, project)` pair — there is no cache and no side channel.

### Enforcement narrows `allowed_modes`; it never replaces it

A `(node, project)` pair with no `workspace_bindings` row — i.e. one that
never went through discovery adoption — is governed by `allowed_modes` alone,
exactly as before this stage existed, permanently (not a grace period). Once
a binding exists, the effective mode set is `allowed_modes` intersected with
`capabilities_to_modes(...)` of the pair's active `project_authorizations`
row; no row at all intersects with the empty set. The intersection can only
shrink what `allowed_modes` already permitted, per node — see
`docs/control-plane.md`, "Stage 4", for the full walk-through.

### The privilege ladder, and why it does not call `is_admin()`

`nodes.authorizations.manage` is administrative (`codexbridge.admin`), same
class as `nodes.read`/`nodes.discoveries.decide`. Granting `modify` or
`deliver` crosses one more condition, evaluated inside
`permissions.is_allowed` (never a second `if` inside the route):
`principal.can_approve_sensitive or "admin" in principal.roles`.

That condition deliberately does NOT read `principal.is_admin()`, unlike
`decisions.decide`'s own second gate. `is_admin()` is `"admin" in
principal.roles or "codexbridge.admin" in principal.scopes`. `decisions.
decide`'s own scope (`codexbridge.task.approve`) is disjoint from
`codexbridge.admin`, so `is_admin()` genuinely adds a condition there. But
`nodes.authorizations.manage`'s own BASE scope already IS
`codexbridge.admin` — so for this one action, `principal.has_scope(action.
scope)` and `principal.is_admin()` collapse into the same predicate, and
gating on `is_admin()` a second time after the base scope already required
it would be tautological: `can_approve_sensitive` would never once be the
deciding factor, and every `codexbridge.admin`-scoped principal could grant
`modify`/`deliver` regardless of it — the exact escalation this gate exists
to close. Checking the ROLE directly instead keeps the distinction real: a
token can carry `codexbridge.admin` for fleet-visibility reasons
(`nodes.read`) without its holder being trusted for `modify`/`deliver`.
`tests/integration/test_authorization_routes.py::
test_granting_modify_without_can_approve_sensitive_or_admin_role_is_refused`
is the test that would have passed silently if this gate had been written
the naive way.

### `authorize` overwrites; `revoke` never deletes

`POST .../authorize` OVERWRITES the pair's capability set and provenance
rather than merging with whatever it held before — an operator calling this
states the authorization they want NOW. A previously revoked row is
reactivated in place (`revokedAt` cleared), never duplicated:
`project_authorizations_node_project_idx` allows exactly one non-revoked row
per pair. `POST .../revoke` marks the row revoked and never deletes it, so a
later `authorize` call can reactivate the same row and its provenance
survives the gap. Both endpoints record their own `audit_events` entry
(`project_authorization.granted`/`.revoked`); the row itself holds only
current state.

### `revoke` carries no second gate

Taking capability away is never the escalation `authorize`'s
`can_approve_sensitive`/admin-role condition guards against, so `revoke`
needs only the base `nodes.authorizations.manage` scope — a principal who
could never have granted `modify` may still revoke a pair that already
carries it.

---

## Cross-cutting rules every endpoint inherits

Implemented in `gateway/app/api/` (issue #12). An endpoint does not re-invent
any of this; it uses the helper, and the helper is what the contract describes.

### One error envelope

Every non-2xx response under `/api` is an `Error`: `code`, `message`,
`requestId`, `retryable`, and `details` on validation failures. This holds for
the failures no handler writes by hand — request validation, `HTTPException`
raised inside a dependency, and unhandled exceptions — because
`install_error_handlers` converts them.

Handlers are registered application-wide, since FastAPI has no per-router hook,
and each one checks `gateway/app/api/scope.py:is_contract_path` first. Anything
outside `/api` is re-delegated to the framework default, which is what keeps
`POST /mcp` speaking JSON-RPC to the ChatGPT client that exists today.

The handler is keyed on **`starlette.exceptions.HTTPException`**, not FastAPI's
subclass. Starlette resolves handlers by walking the raised class's MRO, so a
handler keyed on the subclass never catches the parent — and the parent is what
the router raises for an unmatched path or a wrong method. Keyed on the
subclass, every mistyped `/api/...` URL returned `{"detail": "Not Found"}`.

Install it with **`install_api_conventions(app)`** and nothing else. The
middleware must be handed `render_unhandled`; wiring the two separately is
possible and the only symptom is on the 500 path, which nobody exercises by
hand.

An `internal_error` body carries a `requestId` and nothing else. Raw driver
errors name hosts, ports and schema; the detail belongs in the server log.

### `requestId`, and what it is not

Assigned per request by `RequestContextMiddleware`, echoed in the
`X-Request-Id` response header and included in every error body, so an operator
handed a screenshot can find the one failing request.

Unhandled exceptions are rendered **inside that middleware**, not by an
`@app.exception_handler(Exception)`. Starlette invokes those from
`ServerErrorMiddleware`, which sits outside every user middleware — after the
request-id context is gone. Installed there, a 500 carried one fresh UUID in the
body, a different one in the log, no `X-Request-Id` header at all, and discarded
the client's value: unlinkable on exactly the failure most worth tracing.

A client-supplied `X-Request-Id` is honoured only when it matches the `Id`
pattern. The value is written into response headers and log lines, so echoing
arbitrary client bytes there is a header-injection and log-forging primitive.

It is **not** `TaskModel.correlation_id`, which is per-task, persisted, and
shared with the executor protocol. See the `requestId` description in the
contract for why merging them would silently defeat the field.

### Pagination

Collections use `PageInfo`. A cursor is opaque and single-purpose: it carries a
digest of the endpoint and its filters, so one issued elsewhere is rejected
rather than reinterpreted — silently paging through the wrong rows is worse than
an error. Every rejection returns the same message, because distinguishing
"malformed" from "valid but issued elsewhere" describes server state to someone
holding a token they were never given.

Cursors are **HMAC-signed**, and callers pass `expect={...}` naming the keys and
types they will read. Both are load-bearing: the scope digest is computed from
public inputs (the path, and the filters the client itself sent), so on its own
it catches typos and authenticates nothing — a forged position went straight
into the caller's query, and `{"after": "3"}` was an unauthenticated remote 500.
The signing secret defaults to a per-process random value, so cursors do not
survive a restart or span replicas; that fails safe. Deployments running more
than one gateway process set `CODEX_BRIDGE_API_CURSOR_SECRET`.

Callers fetch `limit + 1` rows and hand the result to `pagination.paginate`.
That extra row is what makes `hasMore` authoritative without a second count
query — and authoritative is what the contract promises, since a page can be
short simply because authorization filtered rows out.

`limit` above the maximum is clamped, not rejected: a client that guessed the
ceiling wrong should get a smaller page, not a failure.

### Idempotency

`Idempotency-Key` on a write makes the request safe to repeat, which is what
lets a mobile client that lost the network mid-request retry without risking a
double approval.

Records are keyed by **(key, endpoint, actor)**. The same key from a different
actor is a different operation; collapsing them would let one client's retry be
answered with another client's response. The same key with a *different* body is
a client bug and returns `409` — answering it with the stored response would
silently drop the second write.

The flow is **reserve, then complete**: `reserve()` claims the key before the
work, `complete()` attaches the response, `release()` frees the claim if the
write failed. Writing the record only afterwards left a window where two
concurrent retries both saw "no record", both performed the side effect — the
double approval this exists to prevent — and the loser then died on the primary
key with a 500 marked `retryable`, inviting a third attempt. A retry arriving
while the first is still in flight gets `409` with `retryable: true`.

Expired records are swept at startup. There is no scheduler in this deployment
and adding one is a larger change than this issue owns; without the sweep the
table grows without bound, each row holding a full response body.

### Rate limiting

The contract defines `rate_limited`, the `RateLimited` response and the
`Retry-After` header, and `errors.py` maps `429` to the code. **Every served
`/api` route carries the limiter**, as a router-level dependency
(`RateLimitDependency` over `MemoryRateLimiter`): the two `/api/v1` routers and
`/api/version`. The default ceiling is 120 requests per 60 seconds per bucket
(`CODEX_BRIDGE_RATE_LIMIT_REQUESTS_PER_WINDOW`,
`CODEX_BRIDGE_RATE_LIMIT_WINDOW_SECONDS`), so a client should implement
`Retry-After` backoff — the `429` in the contract is real.

The bucket is the caller's address, not the actor: the limiter is a router-level
dependency and is solved before the route-level authentication, so it never sees
a principal. That is deliberate for `POST /api/v1/auth/sign-in`, which is
unauthenticated and is the one endpoint where guessing repeatedly is the whole
attack.

`dependencies=` binds to the routes of the router it is passed to, so a route
added later with a bare `@app.get("/api/v1/...")` would be unlimited. What makes
"every served `/api` route" true is a test —
`tests/integration/test_probes.py::test_every_served_api_route_carries_the_rate_limiter`
— not this paragraph.

`POST /oauth/authorize` is not an `/api` route and now carries the same limiter
anyway, declared on the route itself. It takes a password, it is
unauthenticated, and since the constant-cost guard moved into
`users.authenticate` every attempt — including one with an invented username —
costs a full PBKDF2 derivation. Closing the enumeration oracle made the cheapest
hostile request on the gateway ~190x more expensive to serve, on the one auth
route that would not refuse a caller for repeating it. The `GET` that renders
the form is deliberately unlimited: it touches no credential.

Both password endpoints run the derivation **off the event loop**
(`users.authenticate_async`). A few hundred milliseconds of PBKDF2 with no
`await` in it holds the whole process while it runs: ten concurrent attempts
took `GET /health` from 0.8 ms to 3.3 s, and a liveness probe that times out
restarts a gateway that is merely being probed for accounts. Pinned by
`tests/integration/test_oauth_authorize.py::test_a_flood_of_bad_logins_does_not_stall_the_liveness_probe`.

This section is checked against the running application. It previously said the
opposite — that nothing limited `/api` — for a while after the limiter shipped,
which is a client author deciding not to implement backoff from a false premise.

### Optimistic concurrency

Reads return an `ETag` derived from a monotonic `revision`; writes require
`If-Match`. A mismatch is `412 stale_write` and carries the current `ETag`.

A missing `If-Match` is `428`, not a pass. A client that never sends the header
is a client with no concurrency protection at all, and treating absence as "no
opinion" would make the protection opt-in on exactly the requests likeliest to
forget it. Weak validators (`W/"7"`) never match: RFC 9110 requires strong
comparison for `If-Match`, and a weak tag asserts semantic equivalence — which
is precisely what a second operator approving the same decision is.

The validator is `tasks.revision` (`migrations/0002_api_foundation.sql`), bumped
by all four mutators in `gateway/app/services/store.py` — including
`recover_tasks_after_startup`, which runs unattended on every restart and moves
tasks to `lost` or `expired`. That one was missed at first, and a test asserting
"every mutation" while checking two of four is what let the omission through.
The pre-existing timestamps
could not serve: none of `started_at` / `completed_at` moves when
`approval_state`, `approval_reason` or `last_error` changes, so an ETag built
from them would be identical on both sides of a concurrent approval and no stale
write would ever be caught. That is why issue #2 refused to publish
`stale_write` until this column existed.

### Schema changes are not automatic

`Base.metadata.create_all` runs at startup and issues `CREATE TABLE IF NOT
EXISTS`. It builds a fresh database and **never alters an existing one**, so an
upgraded deployment starts cleanly, creates any brand-new table, and then fails
on the first read touching a new column — an error that reads like a code bug.

Two things close that:

- `gateway/app/db/schema_guard.py` refuses to start when a required table or
  column is missing, naming the object and the migration that adds it;
- `python3 scripts/apply_migrations.py` applies `migrations/*.sql` once each,
  tracked in `schema_migrations`. **Startup never calls it**: applying schema
  changes to a live database is an operator decision, not a side effect of a
  restart.

A database created before that script existed needs one explicit adopt step
first. `0001_init.sql` is Postgres-only — `generated always as identity` is a
syntax error on SQLite — and the databases here were built by `create_all`
rather than by that file, so recording it as applied states the truth instead of
re-running something that never ran:

```bash
python3 scripts/apply_migrations.py --mark-applied 0001_init.sql
python3 scripts/apply_migrations.py
```

---

## Getting the contract to the mobile repository

`scripts/publish_contract.py` writes the document to `contract/<version>/` with
a `manifest.json` carrying its SHA-256, and refreshes `contract/index.json`. The
mechanics, the consumer-side fetch-and-verify commands and the immutability rule
are in **[`testing.md`](./testing.md)**.

**The producing half is done; the consuming half is not.** This repository now
publishes a pinnable, checksummed artifact and refuses to let it drift.
`EDortta/CodexBridgeMobile` does **not** consume it yet: it has no `contract/`
directory, fetches nothing, verifies no digest, and still cites this document by
hand. And **no branch carries `contract/` yet** — not `development`, and `main`
has no `docs/api/` at all; it exists only on the branch that introduced it.
Nothing here is a pin until this work merges *and* the mobile build does the
verifying, and the second half is a change in the other repository.

`tests/contract/test_published_contract_artifact.py` fails when the published
copy falls behind the document, and separately when a version that was already
published no longer hashes to its own manifest — two failures with opposite
remedies, which is why they are reported apart.

Before this existed the document lived here and a consumer copied it by hand:
nothing published it, nothing checksummed it, and nothing detected a diverged
copy, so the drift gate protected the *gateway ↔ document* pair and left the
*document ↔ mobile client* pair — the pair this epic exists for — unguarded.

**One hole is left open on purpose, and it is not small.** Republishing an
edited document under the *same* `info.version` rewrites both the copy and its
manifest, so the digest agrees again and every gate goes green while the bytes
behind a number a client pinned have changed. Only the version-control history
shows it. Enforcing "every change moves `info.version`" in the publisher is the
fix; it was left out here because doing it would have forced a version bump that
belongs to the endpoint work in flight, not to this gate. Until then: **review
any diff that touches `contract/` without adding a directory.**

---

## Working on the contract

The document is validated by the contract suite:

```bash
pip install -e '.[test]'
pytest tests/contract -q
```

The `test` extra requires `openapi-spec-validator>=0.9.0` — a floor, not a pin.
A future major release that renames `validate` or `read_from_filename` would
break this suite on a fresh install; if that happens, pin it rather than working
around it.

CI runs the same suite on every push and pull request
(`.github/workflows/contract.yml`). Before that workflow existed, this gate ran
only when a human remembered to — which is the same reliability as no gate at
all, and it went unnoticed until adversarial review pointed at the empty
`.github/` directory.

`tests/contract` holds six gates — one per file in it — each guarding one pair,
and a green run on one says nothing about the others. The table naming them, and
what each one cannot see, is in [`testing.md`](./testing.md) — read it before
concluding from a green build that the implementation matches the contract.

Changing an endpoint means changing this document **first**. The drift test
exists so that "the implementation and the contract disagree" is a red test and
not a support conversation with the mobile team.
