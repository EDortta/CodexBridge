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
| `/api/v1/**` | **yes** | the mobile-facing public API |
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
