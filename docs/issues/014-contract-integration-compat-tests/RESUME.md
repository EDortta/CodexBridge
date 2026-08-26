# RESUME — WK-20260826-gh14-contract-tests (issue #14, epic #1)

- work_id: WK-20260826-gh14-contract-tests
- data: 2026-08-26
- branch: `feature/gh-14/contract-integration-compat-tests`

## Next Step (DO THIS FIRST)

Nothing is pushed and no PR exists. The branch is three (soon four) commits
ahead of `development` and the full suite is green.

**Before merging, and before merging #11 or #13:** whoever merges a branch that
changed `docs/api/codex-bridge.openapi.yaml` must run

```bash
python3 scripts/publish_contract.py
```

and commit `contract/`. `tests/contract` fails until they do, and the failure
message names the file — but the person seeing it will not have read this, so
say it in the pull request.

## Current state

Committed on the branch, not pushed, not merged, not deployed. Nothing under
`gateway/`, `agent/`, `shared/` or `migrations/` was touched
(`git diff --stat 2e18820..HEAD -- gateway/ agent/ shared/ migrations/` is
empty), no endpoint was added, and `info.version` /
`probes.API_CONTRACT_VERSION` are both still `1.6.0` — #11 and #13 own the
version bumps.

The delivery is anti-drift **machinery**, and it iterates the contract's own
paths dynamically. No test in it names an endpoint.

## What issue #14 asked for, and where each half came from

| acceptance criterion | already met before this work | added here |
|---|---|---|
| PRs fail when the implementation diverges from the contract | route-inventory drift, both directions: `tests/contract/test_openapi_document.py:290` (`test_no_public_route_is_missing_from_the_contract`) and `:298` (`test_no_contract_path_is_unimplemented`); run on every push/PR by `.github/workflows/contract.yml:29` | **response-body** divergence, which `docs/api/README.md` §"What the gate does not cover" named as the open half: `tests/contract/test_declared_examples_are_real.py` validates live bodies against the declared schemas and rejects a top-level field the contract omits |
| representative success **and** failure examples tested | behaviour-level, in `tests/integration` — `test_probes.py:53,140,154` (health / ready / 503) and `test_api_conventions.py:151,164,173,186` (422 / HTTPException / 500 / 429 envelopes) — asserted against expectations **written in Python** | the same responses asserted against the **document**: every declared example validated against its own schema, every drivable success body against the declared schema, and failure bodies against `components/schemas/Error` |
| a machine-consumable contract artifact / the mobile repo can pin a version | nothing. `docs/api/README.md` §"Getting the contract to the mobile repository" said so in as many words: *"Today there is none […] a consumer copies it by hand"* | `scripts/publish_contract.py` → `contract/<version>/{codex-bridge.openapi.yaml,manifest.json}` + `contract/index.json`, with `tests/contract/test_published_contract_artifact.py` |
| breaking changes detected before merge | nothing. `info.version` was a number with no comparison behind it; `test_openapi_document.py:414` only asserts the runtime **reports** the same number | `x-minimum-supported-version` in the document + `scripts/check_contract_compatibility.py` + `tests/contract/test_contract_compatibility.py` |
| CI output identifies the incompatible endpoint/schema | route drift already named `(path, method)` pairs | every compatibility finding is a JSON pointer, most-general-first, asserted by `test_the_gate_names_the_incompatible_endpoint_in_its_output` and by the whole mutation matrix (each mutation returns the pointer it broke and the finding must name it) |

Building a second route-drift gate would have been duplicate coverage; it was
not built.

## The two mechanisms

**Artifact publication.** `scripts/publish_contract.py` copies the document
byte-for-byte into `contract/<info.version>/`, writes a `manifest.json` with its
SHA-256, and refreshes `contract/index.json` (`latest` + every version). Nothing
carries a timestamp, a hostname or a user name, because `--check` verifies by
regenerating into a temp tree and comparing bytes — a field that moved between
two runs would make the gate fire on itself. `--check` *also* re-hashes every
previously published version against its own manifest, which is the check that
makes a pin mean anything. Consumer-side commands: `docs/api/testing.md`.

**Minimum supported version.** Declared as `x-minimum-supported-version` at the
root of the OpenAPI document — in the document, not in a repo constant, so it
travels with the published artifact and a consumer reads the floor without
cloning this repository (the same argument `docs/api/README.md` makes for
`x-contract-excluded-paths` living there).
`scripts/check_contract_compatibility.py` flattens both documents into
`pointer → (kind, value)` facts and diffs them in the direction that hurts a
client.

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
this file.

Changed: `docs/api/codex-bridge.openapi.yaml` (only `x-minimum-supported-version`
and one Conventions paragraph that had gone stale — no endpoint, no version
move), `docs/api/README.md`, `docs/required-reading.md`,
`tests/contract/test_docs_match_the_runtime.py`, `pyproject.toml`
(`jsonschema` declared in the `test` extra rather than resting on a transitive
dependency), `docs/codemap.md`.

## Checks

`PYTHONPATH=. .venv/bin/python -m pytest -q` from the worktree → **615 passed,
3 skipped**. Baseline on the same worktree before this session's new tests: 561
passed, 3 skipped — so +54 tests, no regression, same 3 skips.
`pytest tests/contract -q` → 91 passed (26 before).

The known `test_agent_ws_handshake.py` flake did not appear: `codex_bridge.db`
was deleted before each full run.

Not validated:

- **Postgres, and any deployed environment.** Nothing here needs a database
  beyond the SQLite file `TestClient` creates; `scripts/apply_migrations.py` was
  never run.
- **Authenticated endpoints' response bodies.** The body-conformance gate drives
  only operations the document marks `security: []`; a session fixture lives in
  `tests/integration` and reaching across suites would put the authorization
  model's setup into the contract suite. Stated in the module docstring and in
  `docs/api/README.md`, not implied away.
- **`format` keywords.** `jsonschema` does not assert `format` by default and it
  is left off, so `format: date-time` is unenforced — and the contract's actual
  rule (RFC 3339 *with* `Z`) is not expressible in a schema at all, as the
  document's own Conventions section says.
- **The consumer-side recipe in `docs/api/testing.md`.** The `curl` +
  digest-verify snippet was never run against `raw.githubusercontent.com`; the
  branch is not pushed, so the URL it names does not resolve yet.
- **The mock-server line** (`npx @stoplight/prism-cli`). Documented explicitly as
  a pointer and not a supported path: not in CI, not in `pyproject.toml`, not
  exercised by any test.
- **End-to-end reachability** through the nginx edge in `deploy/incus/` —
  unchanged and still unverified by this repository's tests.

## Risks accepted

1. **Republishing under the same `info.version` rewrites a pin.** `publish()`
   overwrites the version directory and its manifest together, so the digest
   agrees again and every gate goes green while the bytes behind a number a
   client pinned have changed. Only the version-control history shows it.
   Closing it in the publisher means enforcing "every change moves
   `info.version`", which would have forced a version bump belonging to #11/#13.
   Written into `docs/api/README.md` §"Getting the contract to the mobile
   repository" with the mitigation: **review any diff that touches `contract/`
   without adding a directory.**
2. **The compatibility gate is honest about four blind spots**, three of them
   from the README's own breaking list: a meaning change under an unchanged name
   and type, default sort order / cursor identity and lifetime, a rename
   reported as a removal, and a tightening inside an `allOf`/`anyOf`/`oneOf`
   branch (members compared as a set, because positional comparison would report
   two breaks on every harmless reorder). Enumerated in the module docstring and
   in `docs/api/testing.md`.
3. **The floor equals the current version today** (`1.6.0` both), so the live
   compatibility comparison cannot fail on a version bump. It is not vacuous —
   it compares the working document against an immutable published copy, so an
   in-place removal under `1.6.0` fails it — but its full value arrives when
   #11/#13 move `info.version` above the floor.
4. **`x-minimum-supported-version` is a one-line addition to a file two sibling
   branches are editing.** Small merge surface, but a real one.

## Coordination with #11 and #13

Both bump `info.version` (1.7.0, 1.8.0) and add endpoints, and neither knows
this machinery exists. On merge:

- `test_published_contract_artifact.py` goes red until `scripts/publish_contract.py`
  is run and `contract/` committed — the intended behaviour, and the message
  names the command;
- `test_contract_compatibility.py` compares the new document against
  `contract/1.6.0/`. Adding endpoints and optional fields is compatible and
  passes; anything else fails with the pointer;
- `test_declared_examples_are_real.py` picks up any new unauthenticated GET and
  any new declared example automatically — nothing to edit.

## Council

<!-- filled in below -->
