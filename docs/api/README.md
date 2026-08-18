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

Body-level conformance is issue #14's scope. Until it lands, read a green run as
*"the same endpoints exist on both sides"*, never as *"the implementation matches
the contract"*.

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
  the content changes is what makes a pin meaningless. Nothing enforces this
  today — see "Getting the contract to the mobile repository".

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
- changing the meaning of an existing field while keeping its name and type
  — the most dangerous kind, because no schema diff catches it;
- changing the HTTP status or the `code` returned for an existing failure;
- changing default sort order, or the identity/lifetime of a pagination cursor.

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
  are addressed by `ProjectId` and nothing else;
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

Today there is none: the document lives in this repository and a consumer copies
it by hand. Nothing publishes it, nothing checksums it, and nothing detects that
a copy has diverged — so the drift gate protects the *gateway ↔ document* pair
and leaves the *document ↔ mobile client* pair, which is the pair this epic
exists for, unguarded.

That gap is issue #14's scope ("publish a machine-consumable contract artifact
for the mobile project", "the mobile repository can consume a pinned contract
version"). It is recorded here rather than left implicit so that nobody reads
the `info.version` field as a working pin before #14 lands.

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

Changing an endpoint means changing this document **first**. The drift test
exists so that "the implementation and the contract disagree" is a red test and
not a support conversation with the mobile team.
