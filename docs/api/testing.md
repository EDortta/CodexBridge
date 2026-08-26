# Testing against the contract, and consuming it from the mobile repository

- work_id: WK-20260826-gh14-contract-tests
- data: 2026-08-26
- owner: Esteban D.Dortta
- issue: #14 (epic #1)

`README.md` in this directory holds the *rules*. This file holds the *mechanics*:
which gate runs when, what each one can and cannot see, how to publish a version,
and how `EDortta/CodexBridgeMobile` pins one.

Everything described here runs from `pytest tests/contract`, which
`.github/workflows/contract.yml` runs on every push and pull request. No gate
below needs a separate CI step, no network, and no gateway process: the app is
imported and driven in-process. It is **not** true that they touch no database
— `TestClient(app)` runs the startup hook, which creates the default SQLite file
in the working directory, and `/ready` probes it. No Postgres is involved and no
migration is applied.

---

## The four gates, and the pair each one guards

The contract is a chain, and each link has its own test file. Reading a green
run as "everything matches" is the mistake this table exists to prevent — each
gate sees exactly one pair.

| pair | file | what a red run means |
|---|---|---|
| gateway ↔ document | `test_openapi_document.py` | a route exists on one side only |
| runtime body ↔ document | `test_declared_examples_are_real.py` | a response body does not match the schema, or an example lies |
| document ↔ published artifact | `test_published_contract_artifact.py` | `contract/` is behind, or a published version was edited |
| document ↔ minimum supported version | `test_contract_compatibility.py` | the change breaks a client on the pinned floor |
| prose ↔ runtime | `test_docs_match_the_runtime.py` | a document states a runtime fact that stopped being true |

---

## Publishing a version

The document is the source; `contract/` is what a consumer downloads.

```bash
python3 scripts/publish_contract.py            # write contract/<info.version>/
python3 scripts/publish_contract.py --check    # verify only; exit 1 on drift
```

Publishing writes three things and nothing else — no timestamp, no hostname, no
user name, because `--check` works by regenerating and comparing bytes:

```
contract/<version>/codex-bridge.openapi.yaml   byte-identical copy of the document
contract/<version>/manifest.json               contractVersion + sha256 of that copy
contract/index.json                            every published version, and the latest
```

**Changing the document means republishing.** `pytest tests/contract` fails
until you do, and the failure names the stale file. That is deliberate: the
gate is the only thing standing between a merged contract change and a mobile
team reading yesterday's YAML.

**A published version directory is immutable.** `--check` recomputes every
manifest digest, so editing `contract/1.6.0/…` in place fails rather than
quietly rewriting what a client already pinned. Ship a new version instead.

---

## Consuming a pinned version from `EDortta/CodexBridgeMobile`

Fetch the version directory, verify the digest, and keep the digest in the
mobile repository. The pin is the *digest*, not the version number — a number
alone is what the contract had before this existed.

`main` below is the versioned deploy cut of `EDortta/CodexBridge`; it moves, and
that is what the digest check is for. A build that must be reproducible should
name a tag or a commit sha in `REF` instead.

```bash
VERSION=1.6.0
REF=main
BASE=https://raw.githubusercontent.com/EDortta/CodexBridge/$REF/contract/$VERSION

curl -fsSL "$BASE/codex-bridge.openapi.yaml" -o codex-bridge.openapi.yaml
curl -fsSL "$BASE/manifest.json"             -o manifest.json

# Refuse to build against a document that is not the one that was published.
python3 - <<'PY'
import hashlib, json, sys
manifest = json.load(open("manifest.json"))
digest = hashlib.sha256(open(manifest["document"], "rb").read()).hexdigest()
sys.exit(0 if digest == manifest["sha256"] else "contract digest mismatch")
PY
```

`contract/index.json` names `latest` and every version published so far, for a
consumer that has not pinned yet. Following `latest` automatically is a choice
to be unpinned; say so out loud if you make it.

---

## The floor: `x-minimum-supported-version`

The document declares the oldest published version this build still promises to
serve:

```yaml
x-minimum-supported-version: '1.6.0'
```

It lives in the document, not in a constant here, so it travels with the
artifact: a consumer that fetched `contract/<v>/codex-bridge.openapi.yaml` reads
the floor without cloning this repository.

```bash
python3 scripts/check_contract_compatibility.py
```

compares the working document against the published copy of that version and
exits 1, naming every incompatible pointer, on anything §"What is a breaking
change" forbids. The output is a list of JSON pointers, most general first:

```
paths[/api/v1/projects].get.responses[200]: this response was removed or renamed. …
components.schemas[Error].properties[retryable]: this property was removed or renamed. …
```

Raising the floor is a deliberate act, not housekeeping: it drops the promise to
every client still on the older pin and needs the same conversation with the
mobile team that a deprecation does.

### What the compatibility gate cannot see

Read a green run as *"no mechanically visible break"*, never as *"compatible"*.
Four classes pass, three of them straight from the README's own list:

- **a meaning change that keeps the name and the type** — the README calls this
  "the most dangerous kind, because no schema diff catches it", and nothing here
  changes that;
- **default sort order**, and the **identity or lifetime of a pagination cursor**;
- a **rename is reported as a removal** — the verdict is right, the wording is not;
- a constraint tightened **inside** an `allOf` / `anyOf` / `oneOf` branch:
  composition members are compared as a set and not recursed into, because
  comparing them positionally would report two breaks every time two equivalent
  branches are reordered.

---

## Fixtures for the mobile client

The response examples in the document are checked, one parametrized test per
example, against the schema they illustrate
(`test_declared_examples_are_real.py::test_a_declared_example_satisfies_its_own_schema`).
So they are usable as fixtures directly out of the pinned YAML — an example that
contradicts its own schema cannot be merged.

There is **no fixture generator in this repository**, and no fixture files are
committed. Extract them from the pinned document with whatever the mobile build
already uses for YAML; every example lives under
`paths.<path>.<method>.responses.<status>.content.<media>.example` or
`.examples.<name>.value`.

## A local mock server

**Nothing here vendors, wraps or tests a mock server.** The published document
is a plain OpenAPI 3.1 file, so any tool that reads one works, and the pinned
copy is the right input because it is the copy the client was built against:

```bash
npx @stoplight/prism-cli mock contract/1.6.0/codex-bridge.openapi.yaml
```

That command is a pointer, not a supported path: it is not in CI, not in
`pyproject.toml`, and no test in this repository exercises it. A mock replays
the document, so it agrees with the contract by construction and proves nothing
about the gateway — which is what the gates in the table above are for.

To develop against the **real** gateway instead, override the `host` server
variable; its default is production
(`docs/api/codex-bridge.openapi.yaml`, `servers`).

---

## Running the gates locally

```bash
pip install -e '.[test]'
pytest tests/contract -q          # every gate in the table above
pytest -q                         # the whole suite
```

`tests/contract` needs no running gateway: it imports `gateway.app.main.app` and
drives it through `TestClient` in-process, against the default SQLite file. That
is also its limit — the nginx edge in `deploy/incus/` decides separately what it
forwards, so **end-to-end reachability of a contracted route is not verified by
this repository's tests.**
