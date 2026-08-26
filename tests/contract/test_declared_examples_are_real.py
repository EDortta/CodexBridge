"""Response **bodies**, checked against the contract — the half the route gate skips.

`docs/api/README.md` §"What the gate does not cover" is explicit about the hole
this file fills:

> It compares **route inventories**: `(path, method)` on both sides. It does not
> read a single `requestBody` or `responses` block. […] Body-level conformance
> is issue #14's scope.

Three claims are checked, and each fails for its own reason:

1. **A declared example must satisfy the schema it illustrates.** The mobile
   team codes against the example long before it codes against the schema; an
   example that lies costs more than a missing one, because it is trusted.
2. **A response the gateway actually returns must satisfy the declared schema**,
   and must carry no top-level field the contract does not describe. That is
   the body-level mirror of the route-drift gate: an undocumented field is an
   undocumented public surface.
3. **A failure response must be the declared `Error` envelope** — the contract
   calls it "the single error envelope returned by every endpoint in this
   contract for every non-2xx response. An endpoint that returns anything else
   is a contract violation, not a variant."

### Why this is not the coverage `tests/integration` already has

`tests/integration/test_probes.py` and `test_api_conventions.py` assert
behaviour against expectations **written in Python** — `body["status"] ==
"degraded"`, `body["code"] == "not_found"`. Those are a second, independent
statement of the contract, and two independent statements drift: the YAML can
gain a required field, or lose one, and every one of those tests stays green.
Nothing in this repository validated a live response against the schema in the
document until this file. The assertion here is deliberately *not* a restatement
of the expected fields — it is `the document says so`.

### What is driven, and what is not

Operations are discovered from the document, never listed here: two sibling
branches are adding endpoints right now, and a hardcoded list would be a hidden
dependency on an endpoint set in flux. The filter is a property the document
states about itself — `security: []`, a GET, no path parameters — so an
unauthenticated probe added tomorrow is covered without editing this file.

**not validated: authenticated endpoints.** Driving them needs the sign-in
fixtures that live in `tests/integration`, and reaching across suites to build a
session here would put the authorization model's setup in the contract suite.
Their success and failure bodies are exercised in `tests/integration` against
hand-written expectations, which is the weaker form described above. Closing
that is a follow-up, not something this file quietly pretends to do.

**not validated: `format` keywords.** `jsonschema` does not assert `format` by
default and it is left off here, so `format: date-time` on a `Timestamp` is not
enforced by these tests. The stricter rule the contract actually wants — RFC
3339 *with* an explicit `Z` — is not expressible in the schema at all, as the
document's own Conventions section says.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Iterator

import pytest
import yaml
from fastapi.testclient import TestClient
from jsonschema import Draft202012Validator

from gateway.app.main import app


REPO_ROOT = Path(__file__).resolve().parents[2]
SPEC_PATH = REPO_ROOT / "docs" / "api" / "codex-bridge.openapi.yaml"

OPERATIONS = frozenset({"get", "put", "post", "delete", "options", "head", "patch", "trace"})

SPEC: dict = yaml.safe_load(SPEC_PATH.read_text(encoding="utf-8"))


def _validator(fragment: dict) -> Draft202012Validator:
    """A validator for one schema fragment that can still follow the document's `$ref`s.

    The fragment is republished as the root of a synthetic document that keeps
    the real `components`, so `#/components/schemas/Id` resolves to the same
    place it resolves to in the contract. Handing the bare fragment to the
    validator instead would make every internal pointer dangle — and a
    validator that cannot resolve a `$ref` raises rather than passing, so the
    failure would at least be loud; this makes it correct.
    """
    return Draft202012Validator({**fragment, "components": SPEC["components"]})


def _resolve_response(response: Any) -> dict | None:
    """A response object, following a `#/components/responses/…` reference.

    Reusable error responses are declared once and `$ref`-ed from dozens of
    operations. Skipping them would leave `InternalError` — the shape a client
    meets on the worst day — unchecked.
    """
    if not isinstance(response, dict):
        return None
    reference = response.get("$ref")
    if isinstance(reference, str):
        prefix = "#/components/responses/"
        if not reference.startswith(prefix):
            return None
        return (SPEC.get("components") or {}).get("responses", {}).get(
            reference[len(prefix):]
        )
    return response


def _declared_examples(media: dict) -> Iterator[tuple[str, Any]]:
    """Every example in one media-type object, `example` and `examples` alike."""
    if "example" in media:
        yield "example", media["example"]
    for name, entry in (media.get("examples") or {}).items():
        if isinstance(entry, dict) and "value" in entry:
            yield f"examples[{name}]", entry["value"]


def _example_cases() -> list[tuple[str, dict, Any]]:
    """(label, schema, example) for every response example the document declares."""
    cases: list[tuple[str, dict, Any]] = []
    for path, item in (SPEC.get("paths") or {}).items():
        if not isinstance(item, dict):
            continue
        for method, operation in item.items():
            if method.lower() not in OPERATIONS or not isinstance(operation, dict):
                continue
            for status, raw in (operation.get("responses") or {}).items():
                response = _resolve_response(raw)
                if not response:
                    continue
                for media_type, media in (response.get("content") or {}).items():
                    schema = (media or {}).get("schema")
                    if not isinstance(schema, dict):
                        continue
                    for label, value in _declared_examples(media):
                        cases.append(
                            (f"{method.upper()} {path} {status} {media_type} {label}",
                             schema, value)
                        )
    return cases


EXAMPLE_CASES = _example_cases()


def _drivable_operations() -> list[tuple[str, str, dict]]:
    """Operations this suite can call with no credential and no path parameter.

    Discovered from a property the document states about itself (`security: []`),
    so a probe added later is covered without editing this file, and an endpoint
    that stops being unauthenticated drops out here — where
    `test_contract_compatibility.py` will have already failed the change.
    """
    found: list[tuple[str, str, dict]] = []
    for path, item in (SPEC.get("paths") or {}).items():
        if "{" in path or not isinstance(item, dict):
            continue
        for method, operation in item.items():
            if method.lower() != "get" or not isinstance(operation, dict):
                continue
            if operation.get("security") == []:
                found.append((path, method.lower(), operation))
    return found


DRIVABLE = _drivable_operations()


@pytest.fixture(scope="module")
def client() -> TestClient:
    return TestClient(app)


# --------------------------------------------------------------------------
# 1. A declared example satisfies the schema it illustrates
# --------------------------------------------------------------------------


def test_the_document_declares_response_examples_at_all() -> None:
    """Anti-vacuity: the parametrized test below is empty if discovery breaks.

    A helper that silently returns `[]` turns a parametrized suite into zero
    tests and a green run — the loudest kind of false coverage there is.
    """
    assert EXAMPLE_CASES, (
        "no response example was discovered in the contract. Either the "
        "document declares none, or `_example_cases` stopped finding them."
    )


@pytest.mark.parametrize(
    ("body", "why"),
    [
        ({}, "every required field missing"),
        (
            {"code": "not_found", "message": "x", "requestId": "not valid!!", "retryable": False},
            "`requestId` violating the `Id` pattern, which lives behind a `$ref`",
        ),
        (
            {"code": "invented_code", "message": "x", "requestId": "req-1", "retryable": False},
            "a `code` outside `ErrorCode`, also behind a `$ref`",
        ),
    ],
    ids=["missing-required", "bad-ref-pattern", "bad-ref-enum"],
)
def test_the_validator_rejects_what_the_schema_forbids(body: dict, why: str) -> None:
    """Everything below is worthless if `_validator` accepts anything.

    Two of the three cases are only caught by following a `$ref` into
    `components`, which is the part of the wiring that would fail silently: a
    validator built on the bare fragment cannot resolve those pointers, and
    "no errors" is indistinguishable from "conforms".
    """
    schema = SPEC["components"]["schemas"]["Error"]
    assert list(_validator(schema).iter_errors(body)), (
        f"the validator accepted a body with {why}; it is not checking anything"
    )


@pytest.mark.parametrize(
    ("label", "schema", "example"), EXAMPLE_CASES, ids=[case[0] for case in EXAMPLE_CASES]
)
def test_a_declared_example_satisfies_its_own_schema(
    label: str, schema: dict, example: Any
) -> None:
    """An example that contradicts its schema misleads the reader who trusts it most."""
    errors = sorted(_validator(schema).iter_errors(example), key=lambda e: list(e.path))
    assert not errors, (
        f"the example for {label} does not satisfy the schema it illustrates: "
        + "; ".join(f"{list(error.path) or '<root>'}: {error.message}" for error in errors[:5])
    )


# --------------------------------------------------------------------------
# 2. The gateway returns what the document says it returns
# --------------------------------------------------------------------------


def test_at_least_one_operation_can_be_driven() -> None:
    """Anti-vacuity, again: `security: []` disappearing must not read as green."""
    assert DRIVABLE, (
        "no unauthenticated GET without path parameters was found in the "
        "contract, so nothing below actually calls the gateway."
    )


@pytest.mark.parametrize(
    ("path", "method", "operation"), DRIVABLE, ids=[f"{p}" for p, _, _ in DRIVABLE]
)
def test_the_gateway_returns_the_declared_shape(
    client: TestClient, path: str, method: str, operation: dict
) -> None:
    """The success half of "representative examples are tested".

    Asserted against the document, not against a field list written here: that
    is the whole difference between this and the probe tests in
    `tests/integration`, which restate the contract in Python and therefore
    cannot notice the document changing.
    """
    response = client.request(method.upper(), path)
    status = str(response.status_code)

    declared = _resolve_response((operation.get("responses") or {}).get(status))
    assert declared is not None, (
        f"{method.upper()} {path} answered {status} and the contract declares no "
        f"{status} response for it. Declared: {sorted(operation.get('responses') or {})}"
    )

    media = (declared.get("content") or {}).get("application/json")
    assert media, f"the contract declares no application/json body for {path} {status}"

    body = response.json()
    errors = sorted(_validator(media["schema"]).iter_errors(body), key=lambda e: list(e.path))
    assert not errors, (
        f"the body {method.upper()} {path} returned does not satisfy the schema "
        f"the contract declares for {status}: "
        + "; ".join(f"{list(error.path) or '<root>'}: {error.message}" for error in errors[:5])
    )


@pytest.mark.parametrize(
    ("path", "method", "operation"), DRIVABLE, ids=[f"{p}" for p, _, _ in DRIVABLE]
)
def test_the_gateway_returns_no_field_the_contract_omits(
    client: TestClient, path: str, method: str, operation: dict
) -> None:
    """The body-level mirror of the undocumented-route check.

    Schema validation alone cannot see this: none of these objects sets
    `additionalProperties: false`, so an extra top-level field is valid and
    invisible. It is still an undocumented part of the public surface, and a
    client written from the contract will never read it — which is how a field
    ships, gets depended on by one consumer, and is then impossible to remove.

    Top level only, on purpose. Recursing would demand a `properties` block for
    every nested object including the deliberately open ones (`capabilities` is
    `additionalProperties: {type: boolean}` by design), and a gate that fires on
    a documented design decision is a gate that gets deleted.
    """
    response = client.request(method.upper(), path)
    declared = _resolve_response((operation.get("responses") or {}).get(str(response.status_code)))
    schema = ((declared or {}).get("content") or {}).get("application/json", {}).get("schema", {})
    body = response.json()
    if not isinstance(body, dict) or not isinstance(schema.get("properties"), dict):
        pytest.skip(f"{path} {response.status_code} is not a described JSON object")

    undeclared = sorted(set(body) - set(schema["properties"]))
    assert not undeclared, (
        f"{method.upper()} {path} returns top-level field(s) {undeclared} that "
        f"{SPEC_PATH.name} does not describe. Add them to the schema or stop "
        "returning them; an undocumented field is an undocumented public surface."
    )


# --------------------------------------------------------------------------
# 3. The failure half: every non-2xx is the declared envelope
# --------------------------------------------------------------------------


def _unmatched_api_path(client: TestClient):
    """A path under the public namespace that no route claims."""
    return client.get("/api/v1/no-such-resource-exists-here")


def _wrong_method_on_a_contracted_path(client: TestClient):
    """A method the contract does not declare for a path it does declare.

    The path is taken from the document rather than named here, for the same
    reason as everywhere else in this file.
    """
    path, _, _ = DRIVABLE[0]
    return client.post(path)


FAILURE_TRIGGERS = [
    ("unmatched path under /api/v1", _unmatched_api_path),
    ("method not allowed on a contracted path", _wrong_method_on_a_contracted_path),
]


@pytest.mark.parametrize(
    ("label", "trigger"), FAILURE_TRIGGERS, ids=[label for label, _ in FAILURE_TRIGGERS]
)
def test_a_failure_response_is_the_declared_error_envelope(
    client: TestClient, label: str, trigger
) -> None:
    """`Error` is a promise about *every* non-2xx, so it is checked against the schema.

    `tests/integration/test_api_conventions.py` already asserts these two
    triggers return a sane envelope — by checking fields it names in Python.
    This asserts the same responses against `components.schemas.Error` as the
    document declares it, which is the assertion that notices the document
    gaining a required field the gateway does not send.
    """
    response = trigger(client)
    assert 400 <= response.status_code < 600, (
        f"{label} did not fail: HTTP {response.status_code}"
    )

    errors = sorted(
        _validator(SPEC["components"]["schemas"]["Error"]).iter_errors(response.json()),
        key=lambda e: list(e.path),
    )
    assert not errors, (
        f"the body returned for {label} (HTTP {response.status_code}) is not the "
        "`Error` envelope the contract promises for every non-2xx response: "
        + "; ".join(f"{list(error.path) or '<root>'}: {error.message}" for error in errors[:5])
    )
