# RESUME — WK-20260826-gh14-contract-tests (issue #14, epic #1)

- work_id: WK-20260826-gh14-contract-tests
- data: 2026-08-26
- branch: `feature/gh-14/contract-integration-compat-tests`
- status: **merged** via **PR #60** (2026-09-02), on `main`. Not deployed.

## Next Step (DO THIS FIRST)

Nothing is pending on this issue. What it leaves behind is a **standing rule**,
and it is the one thing a later session has to know: whoever merges a branch
that changed `docs/api/codex-bridge.openapi.yaml` must run

```bash
python3 scripts/publish_contract.py
```

and commit `contract/`. `pytest tests/contract` fails until they do and the
message names the command — but the person seeing it will not have read this,
so say it in the pull request. Done for `1.7.0` (#11), `1.8.0` (#13) and
`1.9.0` (#75); `contract/index.json` names `1.9.0` as latest.

Verified against the real sibling branches, read-only: the compatibility gate
reports **0 breaking changes** for both `feature/gh-11` (1.7.0) and
`feature/gh-13` (1.8.0). Their merges will fail only the publish check, which
the command above fixes.

## Current state

Merged and on `main`; not deployed. Nothing under
`gateway/`, `agent/`, `shared/` or `migrations/` was touched
(`git diff --stat 2e18820..HEAD -- gateway/ agent/ shared/ migrations/` is
empty), no endpoint was added, and `info.version` /
`probes.API_CONTRACT_VERSION` were both still `1.6.0` on this branch — #11, #13
and #75 own the version bumps, and after the merges the pair reads `1.9.0`.

The delivery is anti-drift **machinery**, and it iterates the contract's own
paths dynamically. No test in it names an endpoint.

## What issue #14 asked for, and where each half came from

| acceptance criterion | already met before this work | added here |
|---|---|---|
| PRs fail when the implementation diverges from the contract | route-inventory drift, both directions: `tests/contract/test_openapi_document.py:290` and `:298`; run on every push/PR by `.github/workflows/contract.yml:29` | **response-body** divergence, which `docs/api/README.md` §"What the gate does not cover" named as the open half: `tests/contract/test_declared_examples_are_real.py` validates live bodies against the declared schemas and rejects a top-level field the contract omits |
| representative success **and** failure examples tested | behaviour-level, in `tests/integration` — `test_probes.py:53,140,154` and `test_api_conventions.py:151,164,173,186` — asserted against expectations **written in Python** | the same responses asserted against the **document**: all 24 declared examples validated against the schema each illustrates, drivable success bodies against the declared schema, failure bodies against `components/schemas/Error` |
| a machine-consumable contract artifact / the mobile repo can pin a version | nothing. `docs/api/README.md` said so in as many words: *"Today there is none […] a consumer copies it by hand"* | `scripts/publish_contract.py` → `contract/<version>/{codex-bridge.openapi.yaml,manifest.json}` + `contract/index.json`, with `tests/contract/test_published_contract_artifact.py` |
| breaking changes detected before merge | nothing. `info.version` was a number with no comparison behind it; `test_openapi_document.py:414` only asserts the runtime **reports** the same number | `x-minimum-supported-version` + `scripts/check_contract_compatibility.py` + `tests/contract/test_contract_compatibility.py` |
| CI output identifies the incompatible endpoint/schema | route drift already named `(path, method)` pairs | every compatibility finding is a JSON pointer, most-general-first, asserted by `test_the_gate_names_the_incompatible_endpoint_in_its_output` and by the whole mutation matrix — each mutation returns the pointer it broke and the finding must name it |

Building a second route-drift gate would have been duplicate coverage; it was
not built.

## The two mechanisms

**Artifact publication.** `scripts/publish_contract.py` copies the document
byte-for-byte into `contract/<info.version>/`, writes a `manifest.json` with its
SHA-256, and refreshes `contract/index.json`. Nothing carries a timestamp,
hostname or user name, because `--check` verifies by regenerating into a temp
tree and comparing bytes. `--check` *also* re-hashes every previously published
version against its own manifest. Consumer-side commands: `docs/api/testing.md`.

**Minimum supported version.** Declared as `x-minimum-supported-version` at the
root of the OpenAPI document — in the document, not in a repo constant, so it
travels with the published artifact.
`scripts/check_contract_compatibility.py` flattens both documents into
`pointer → (kind, value)` facts and diffs them in the direction that hurts a
client. A constraint counts as a tightening only when the thing it constrains
already existed.

The baseline is the **published copy** `contract/<floor>/codex-bridge.openapi.yaml`,
not a second snapshot under `tests/contract/baselines/`. That is a deliberate
deviation from the plan: `contract/<floor>/` is already an immutable,
digest-verified copy of exactly those bytes, and a byte-identical third copy
would be one more thing to drift.

## Changed files

New: `scripts/publish_contract.py`, `scripts/check_contract_compatibility.py`,
`contract/index.json`, `contract/1.6.0/{codex-bridge.openapi.yaml,manifest.json}`,
`docs/api/testing.md`,
`tests/contract/{test_published_contract_artifact,test_contract_compatibility,test_declared_examples_are_real}.py`,
this file and `council-round-{1,2}.json` beside it.

Changed: `docs/api/codex-bridge.openapi.yaml` (only `x-minimum-supported-version`
and one Conventions paragraph that had gone stale — no endpoint, no version
move), `docs/api/README.md`, `docs/required-reading.md`,
`tests/contract/test_docs_match_the_runtime.py`, `pyproject.toml`, `docs/codemap.md`.

## Checks

`PYTHONPATH=. .venv/bin/python -m pytest -q` from the worktree → **652 passed,
3 skipped**. Baseline on the same worktree before this session's new tests: 561
passed, 3 skipped — so **+91 tests**, no regression, the same 3 skips (the
opt-in `RUN_REAL_CODEX_TESTS` real-process tests).
`pytest tests/contract -q` → **128 passed** (26 before).

The known `test_agent_ws_handshake.py` flake did not appear: `codex_bridge.db`
was deleted before each full run.

Not validated:

- **Postgres, and any deployed environment.** Nothing here needs a database
  beyond the SQLite file `TestClient` creates; `scripts/apply_migrations.py` was
  never run.
- **Authenticated endpoints' response bodies.** The body-conformance gate drives
  only operations the document marks `security: []`; a session fixture lives in
  `tests/integration`. Stated in the module docstring and in
  `docs/api/README.md`, not implied away.
- **`format` keywords.** `jsonschema` does not assert `format` by default and it
  is left off, so `format: date-time` is unenforced — and the contract's actual
  rule (RFC 3339 *with* `Z`) is not expressible in a schema at all.
- **The consumer-side recipe in `docs/api/testing.md`.** Never run against
  `raw.githubusercontent.com`: **no branch carries `contract/` yet**, so the
  URLs do not resolve until this work merges. Said plainly in the document.
- **The mock-server line** (`npx @stoplight/prism-cli`). Documented as a pointer
  and not a supported path: not in CI, not in `pyproject.toml`, not exercised.
- **End-to-end reachability.** `tests/contract/test_proxy_routes.py` checks the
  vhost *configuration* in `deploy/nginx/` statically; no test in this
  repository sends a request to a real host.

## Risks accepted

1. **Republishing under the same `info.version` rewrites a pin.** `publish()`
   overwrites the version directory and its manifest together, so the digest
   agrees again and every gate goes green while the bytes behind a pinned number
   have changed. Only the version-control history shows it. Closing it means
   enforcing "every change moves `info.version`" in the publisher, which would
   have forced a version bump belonging to #11/#13. Written into
   `docs/api/README.md` and `docs/api/testing.md` with the mitigation: **move
   `info.version` whenever you change the document, and review any diff that
   touches `contract/` without adding a directory.**
2. **Three classes of breaking change pass the compatibility gate in silence**,
   all three from the README's own list: a meaning change under an unchanged
   name and type, default sort order, and cursor identity/lifetime. Two more are
   imprecise rather than silent (a rename reads as a removal; a constraint
   tightened inside an existing `allOf` branch reads as "1 branch removed"). One
   is neither — an unmodelled restriction keyword makes the gate *fail*, saying
   it abstained. Still uncompared: the **contents** of a `securitySchemes` entry.
3. **A `required` removal on a request-only schema reports**, which is a
   deliberate false positive: a JSON pointer cannot tell request from response
   and most schemas here are shared. The message names the direction so a
   reviewer resolves it instead of the gate guessing.
4. **The floor equals the current version today** (`1.6.0` both), so the live
   comparison cannot fail on a version bump. Not vacuous — it still catches an
   in-place removal under 1.6.0 — but its full value arrives when #11/#13 move
   `info.version` above the floor.
5. **`x-minimum-supported-version` is a one-line addition to a file two sibling
   branches are editing.** Small merge surface, but a real one.
6. **Editing the YAML and running only `pytest tests/integration` gives no
   signal.** Not fixed: `.github/workflows/contract.yml` runs `pytest
   tests/contract` on every push and PR, and `testpaths` makes a bare `pytest -q`
   cover it. Coupling unrelated suites would cost more than it buys.
7. **Commit `a0063fd`'s message says "Thirteen breaking mutations"; there were
   fourteen** at that commit and there are **21** now. The message is immutable;
   the count is corrected here and nowhere else repeats it.

## Coordination with #11 and #13

Both bump `info.version` (1.7.0, 1.8.0) and add endpoints, and neither knows
this machinery exists. On merge:

- `test_published_contract_artifact.py` goes red until `scripts/publish_contract.py`
  is run and `contract/` committed — the intended behaviour, and every failure
  message now names the command rather than raising a bare `FileNotFoundError`
  (walked end to end on a scratch copy);
- `test_contract_compatibility.py` compares the new document against
  `contract/1.6.0/` — **0 findings for both branches, measured**;
- `test_declared_examples_are_real.py` picks up any new unauthenticated GET and
  any new declared example automatically — nothing to edit.

**Do not make a red compatibility gate green by raising
`x-minimum-supported-version`.** That silences it permanently;
`test_raising_the_floor_past_a_published_version_is_written_down` now refuses it
without a written reason.

## Council — 2 rounds, `.docs/agents/council.md`

Machine-readable records: `council-round-1.json`, `council-round-2.json` beside
this file, both also registered with `governancekit council --record`.

### Round 1 — lenses: sweep skeptic, claim auditor, second caller

**26 raised · 26 survived §2 · 24 became tests · 4 questions left open.**

Every finding arrived with trigger, wrong result, file:line and a reproduction,
so all 26 survived §2. Four were declared duplicates across lenses (claim 5 =
sweep 3, claim 6 = sweep 11, second 1 = sweep 1, second 3 = claim 3), leaving 22
distinct defects.

The one that mattered most: **the gate reported every purely additive release as
breaking.** Measured against the real sibling branches, `feature/gh-11` produced
**31** breaking findings and `feature/gh-13` **21**, and not one named a pointer
a 1.6.0 client could address. OpenAPI forces `required: true` on every path
parameter, so it would have fired on every endpoint carrying one, forever. Both
are **0** now. The self-test that should have caught it added an endpoint with
no parameters, no body and no response schema — the one shape that dodged the
defect.

Second worst: **a test certified a break as compatible.**
`drop_a_required_request_field` was meant to prove a request-side relaxation
safe; the schema it mutated was `Actor`, which is response-only.

Seven further classes were silently green and are now caught, each with a
mutation that fails without the fix: `servers` (never walked), path-item-level
`parameters` (invisible in, phantom removals out), `components.requestBodies`,
a changed or deleted `default`, which credential an operation accepts, a branch
added to an `allOf`, and a `required` name removed from a response schema.
Raising the floor — the cheapest way to disarm the whole gate — now needs a
written reason. The example sweep reached 5 of 24 examples while two documents
claimed every one; all 24 are checked. The undocumented-field check skipped
every `$ref` and `allOf` response, which is every error shape in the contract.

Questions left open (recorded, not closed): `securitySchemes` entry contents;
the republish-under-the-same-version hole; the deliberate request-side false
positive; and the floor being equal to the current version today.

### Round 2 — verification, plus regression hunt on the round-1 fixes

**6 raised · 6 survived §2 · 2 became tests · 4 questions left open** (the four
carried from round 1, now all recorded as accepted risks above).

Round 2 verified all 26 round-1 findings by reproduction: **23 fully closed**,
3 partial or re-broken. It then found 6 problems in the fixes themselves:

| # | what | classification | closed by |
|---|---|---|---|
| NEW-1 | an existing operation gaining a **required request body** passed in silence — 28 of 40 operations carry none today; round 1's suppression removed a signal that had existed by accident | `introduzido-pela-r1` | `demand_a_request_body_where_there_was_none` |
| NEW-2 | pointing an existing operation at an already-**required component parameter** passed in silence; the `$ref` site assumed `required: False` and the component itself was unchanged. 41 of 90 operation parameters are `$ref`s | `pré-existente` | `point_an_operation_at_a_required_component_parameter` |
| NEW-3 | the corrected `curl` recipe still 404s — the fix swapped one wrong branch name for another; **no branch carries `contract/`** | `introduzido-pela-r1` (the false claim); `aberto-da-r1` (the recipe not resolving) | both documents now say no branch carries it yet |
| NEW-4 | this RESUME.md, added by the fix commit, reinstated the retired `deploy/incus/` citation and carried stale counts and an empty Council section | `introduzido-pela-r1` | rewritten; `test_the_contract_docs_do_not_deny_what_ships` now scans every `docs/issues/**/RESUME.md` too |
| NEW-5 | the checker enforced three rules the **normative** README list did not contain, while claiming to transcribe it — the cry-wolf mechanism the design exists to avoid | `introduzido-pela-r1` | the five rules are now in §"What is a breaking change" |
| NEW-6 | a dangling test id in the script docstring | `introduzido-pela-r1` | corrected |

Round 2 also caught a cry-wolf trap before it could fire: the unmodelled-keyword
tripwire yielded unconditionally, so the first `readOnly: true` anywhere in the
contract would have made the build permanently red with no way to fix it. It now
reports only on a *change*.

Round 2's clean probes are worth recording: the new suppression does **not**
hide a genuine break (existing endpoint + new required parameter, existing schema
+ new required property, optional-to-required flips all still report);
`_declared_properties` is cycle-safe; and `servers` / path-item parameters /
`requestBodies` introduce no phantom findings on either sibling branch (0 removed
and 0 changed facts on both).
