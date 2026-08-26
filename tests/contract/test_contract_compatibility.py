"""The gate that fails a pull request before it breaks the pinned mobile client.

`test_openapi_document.py` binds the gateway to the document. `test_published_contract_artifact.py`
binds the document to the copy `EDortta/CodexBridgeMobile` downloads. Neither
says anything about *what changed*: republishing after removing a field leaves
both of them green, and the mobile build finds out at runtime.

This file guards the third pair — **the document against the oldest version it
still promises to serve**, declared as `x-minimum-supported-version` in the
document itself and published under `contract/<version>/`. The rules are
`docs/api/README.md` §"What is a breaking change" / §"What is not breaking";
`scripts/check_contract_compatibility.py` is where they are transcribed.

Two kinds of test here, deliberately separated:

- the **mutation matrix**, which is where the classifier's teeth are proven. It
  takes the real document, breaks it one way at a time, and asserts the gate
  fires and names the right pointer — and, just as important, takes the changes
  §"What is not breaking" allows and asserts the gate stays quiet. A gate that
  cries wolf gets deleted rather than obeyed.
- the **live check**, which runs the real pair.

While the floor equals the current version the live pair is byte-identical and
the live check cannot fail on a *version bump*. It is still not vacuous: it
compares the working document against an immutable published copy, so editing
`1.6.0` in place — removing a field without bumping anything — fails here, and
fails differently from `--check` in the artifact test. That one fires on any
byte change including a typo fix; this one fires only on a change a client
cannot survive, and the remedies are different (republish vs. a new namespace).

**What is not tested here, because it cannot be:** a change of *meaning* that
keeps a field's name and type, a change of default sort order, and the identity
or lifetime of a pagination cursor. All three are in the README's breaking list
and none is visible to a schema diff — the README says so itself where it calls
the first one "the most dangerous kind". A green run here means "no
mechanically visible break", never "compatible".
"""

from __future__ import annotations

import copy
import importlib.util
import subprocess
import sys
from pathlib import Path
from typing import Callable

import pytest
import yaml


REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "check_contract_compatibility.py"
SPEC_PATH = REPO_ROOT / "docs" / "api" / "codex-bridge.openapi.yaml"
CONTRACT_DIR = REPO_ROOT / "contract"


def _load_checker():
    """Import the classifier from `scripts/`, which is not an importable package.

    `tests/unit/test_apply_migrations.py` drives its script purely as a
    subprocess, and the two live-pair tests below do the same so that the thing
    CI runs is the thing under test, exit code included. The mutation matrix
    does not: it is ~20 cases against a pure function over two parsed
    documents, and a subprocess per case would buy nothing but a slower suite
    and a stack trace one level further from the assertion.
    """
    spec = importlib.util.spec_from_file_location("check_contract_compatibility", SCRIPT)
    assert spec and spec.loader, f"cannot import {SCRIPT}"
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


checker = _load_checker()


def run(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
    )


@pytest.fixture(scope="module")
def spec() -> dict:
    return yaml.safe_load(SPEC_PATH.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def baseline(spec: dict) -> dict:
    """The published copy of the minimum supported version.

    Read from `contract/`, never re-derived from the working document: the
    point of a baseline is that it is the bytes a client already holds.

    Guarded, because an unguarded module fixture is how one missing file
    becomes twenty-three identical `FileNotFoundError` tracebacks with the one
    actionable sentence buried under them. Council round 1 walked the merge of
    a sibling branch and counted exactly that.
    """
    path = checker.baseline_path(spec, CONTRACT_DIR)
    if not path.is_file():
        pytest.fail(
            f"the contract's `{checker.MINIMUM_VERSION_KEY}` names "
            f"{checker.minimum_supported_version(spec)}, and {path} does not "
            "exist. Run `python3 scripts/publish_contract.py` and commit "
            "contract/, or point the floor at a version that is published."
        )
    return yaml.safe_load(path.read_text(encoding="utf-8"))


# --------------------------------------------------------------------------
# The floor is declared, and it names something a client can actually fetch
# --------------------------------------------------------------------------


def test_the_document_declares_a_minimum_supported_version(spec: dict) -> None:
    """Without it there is no floor, and this whole file has nothing to compare against."""
    version = checker.minimum_supported_version(spec)
    assert version, (
        "the contract declares no `x-minimum-supported-version`. The mobile "
        "client has no way to learn which pinned version this build still "
        "promises to serve, and the compatibility gate has no baseline."
    )


def test_the_minimum_supported_version_is_published(spec: dict) -> None:
    """A floor naming an unpublished version is a floor over nothing."""
    version = checker.minimum_supported_version(spec)
    published = CONTRACT_DIR / version / "codex-bridge.openapi.yaml"
    assert published.is_file(), (
        f"`x-minimum-supported-version` names {version}, which is not published "
        f"under contract/{version}/. Either publish it "
        "(`python3 scripts/publish_contract.py`) or name a version that is."
    )


def test_the_minimum_supported_version_is_not_ahead_of_the_document(spec: dict) -> None:
    """A floor above the ceiling means the build serves nothing it promises.

    Compared as semver tuples where both are three integers, and skipped
    otherwise rather than guessed at: a wrong verdict from a version scheme
    this rule does not understand is worse than no verdict.
    """
    floor = checker.minimum_supported_version(spec)
    current = spec["info"]["version"]

    def parts(version: str):
        pieces = version.split(".")
        return tuple(int(p) for p in pieces) if len(pieces) == 3 and all(p.isdigit() for p in pieces) else None

    low, high = parts(floor), parts(current)
    if low is None or high is None:
        pytest.skip(f"not both semver: floor={floor!r} current={current!r}")
    assert low <= high, (
        f"`x-minimum-supported-version` is {floor} while `info.version` is "
        f"{current}: the floor is above the version this build implements."
    )


def test_raising_the_floor_past_a_published_version_is_written_down(spec: dict) -> None:
    """The one edit that silently disarms this whole file.

    Council round 1: faced with a red compatibility gate, the cheapest green is
    not to fix the break — it is to move `x-minimum-supported-version` up to
    `info.version`. The gate then compares the document against a published copy
    of itself and can never fire again, and the promise to every client still on
    the old pin is dropped with no test, no warning, and a one-line diff nobody
    reads as a policy change.

    So the floor must be the **oldest** published version. Raising it is
    legitimate — but it is a deprecation, and this contract's own rule for a
    deliberate exception is that it is written down where the machine can see
    it: the same shape as `x-contract-excluded-paths`, which
    `test_every_exclusion_is_well_formed` refuses without a `reason`.
    """
    floor = checker.minimum_supported_version(spec)
    published = sorted(
        (path.name for path in CONTRACT_DIR.iterdir() if path.is_dir()),
        key=_version_key,
    )
    assert published, "nothing is published, so there is no floor to check"
    oldest = published[0]
    if floor == oldest:
        return

    waiver = spec.get(checker.RAISED_FLOOR_KEY)
    assert isinstance(waiver, str) and waiver.strip(), (
        f"`x-minimum-supported-version` is {floor} while contract/{oldest}/ is "
        "still published, so this build has stopped promising to serve a "
        "version a client may have pinned. That is a deprecation, not "
        f"housekeeping: record why in `{checker.RAISED_FLOOR_KEY}`, naming the "
        "mobile release that stopped using it. If the floor was raised to get "
        "past a red compatibility gate, fix the break instead — that is the "
        "one thing this gate exists to prevent."
    )


def _version_key(version: str) -> tuple:
    parts = version.split(".")
    if len(parts) == 3 and all(part.isdigit() for part in parts):
        return (0, tuple(int(part) for part in parts), "")
    return (1, (), version)


def test_the_error_code_exemption_still_has_a_schema(spec: dict) -> None:
    """The one enum allowed to grow must still be the one the reason applies to.

    `ErrorCode` may gain a value because the contract obliges clients to
    degrade an unknown `code` to its HTTP status class. If that schema is
    renamed or removed, the exemption in the classifier silently starts
    applying to nothing — or, worse, keeps a name that now means something
    else. Same rule as `test_no_exclusion_outlives_its_route`: an exemption may
    not outlive its reason.
    """
    assert "ErrorCode" in (spec.get("components") or {}).get("schemas", {}), (
        "the classifier exempts `ErrorCode` from the added-enum-value rule and "
        "the contract no longer declares that schema; revisit "
        "scripts/check_contract_compatibility.py::ERROR_CODE_ENUM_POINTER"
    )
    assert isinstance(spec["components"]["schemas"]["ErrorCode"].get("enum"), list)


# --------------------------------------------------------------------------
# The live pair
# --------------------------------------------------------------------------


def test_the_document_is_compatible_with_the_minimum_supported_version() -> None:
    """The acceptance criterion: a breaking change is caught before merge.

    Run as a subprocess so the exit code CI reads is what is asserted.
    """
    result = run()
    assert result.returncode == 0, (
        "the working contract breaks the minimum version mobile still "
        f"supports:\n{result.stderr}{result.stdout}"
    )


def test_the_gate_names_the_incompatible_endpoint_in_its_output(tmp_path: Path) -> None:
    """"CI output identifies the incompatible endpoint/schema" — asserted, not assumed.

    A gate that exits 1 with "incompatible" and nothing else sends the reader
    back to diff two 3,700-line documents by hand.
    """
    broken = tmp_path / "codex-bridge.openapi.yaml"
    document = yaml.safe_load(SPEC_PATH.read_text(encoding="utf-8"))
    victim, _ = next(iter(document["paths"].items()))
    document["paths"].pop(victim)
    broken.write_text(yaml.safe_dump(document, sort_keys=False), encoding="utf-8")

    result = run("--document", str(broken), "--baseline", str(SPEC_PATH))
    assert result.returncode == 1
    assert f"paths[{victim}]" in result.stderr, result.stderr
    assert "breaking change" in result.stderr


def test_the_gate_refuses_a_floor_that_is_not_published(tmp_path: Path) -> None:
    """Pointing the floor at a version nobody can download is not a green run."""
    document = yaml.safe_load(SPEC_PATH.read_text(encoding="utf-8"))
    document[checker.MINIMUM_VERSION_KEY] = "0.0.1"
    path = tmp_path / "codex-bridge.openapi.yaml"
    path.write_text(yaml.safe_dump(document, sort_keys=False), encoding="utf-8")

    result = run("--document", str(path))
    assert result.returncode == 1
    assert "0.0.1" in result.stderr
    assert "publish" in result.stderr


def test_a_document_with_no_declared_floor_is_an_error(tmp_path: Path) -> None:
    document = yaml.safe_load(SPEC_PATH.read_text(encoding="utf-8"))
    document.pop(checker.MINIMUM_VERSION_KEY, None)
    path = tmp_path / "codex-bridge.openapi.yaml"
    path.write_text(yaml.safe_dump(document, sort_keys=False), encoding="utf-8")

    result = run("--document", str(path))
    assert result.returncode == 1
    assert checker.MINIMUM_VERSION_KEY in result.stderr


def test_a_document_compared_with_itself_reports_nothing(baseline: dict) -> None:
    """The precondition every other case rests on.

    A classifier that reported a break on an unchanged document would make the
    matrix below pass for the wrong reason, and the live gate red forever.
    """
    assert checker.incompatibilities(baseline, copy.deepcopy(baseline)) == []


# --------------------------------------------------------------------------
# The mutation matrix — one break at a time, against the real document
# --------------------------------------------------------------------------


def _first_path(document: dict) -> str:
    """Whatever endpoint the document happens to declare first.

    Never a literal path. Two sibling branches are adding endpoints to this
    document right now; a test naming `/api/v1/projects` would be a hidden
    dependency on an endpoint set that is deliberately in flux, and the
    machinery here is meant to be indifferent to it.
    """
    return next(iter(document["paths"]))


def _error_schema(document: dict) -> dict:
    """`Error` — the envelope §"One error envelope" makes every endpoint return.

    Used as the mutation subject because it is the one schema the contract
    guarantees exists for as long as the contract does, so the matrix does not
    have to name an endpoint-specific shape.
    """
    return document["components"]["schemas"]["Error"]


def remove_an_endpoint(document: dict) -> str:
    victim = _first_path(document)
    document["paths"].pop(victim)
    return f"paths[{victim}]"


def remove_an_operation(document: dict) -> str:
    victim = _first_path(document)
    method = next(k for k in document["paths"][victim] if k in checker.OPERATIONS)
    document["paths"][victim].pop(method)
    return f"paths[{victim}].{method}"


def remove_a_response_status(document: dict) -> str:
    victim = _first_path(document)
    method = next(k for k in document["paths"][victim] if k in checker.OPERATIONS)
    responses = document["paths"][victim][method]["responses"]
    status = sorted(responses)[-1]
    responses.pop(status)
    return f"paths[{victim}].{method}.responses[{status}]"


def remove_a_response_field(document: dict) -> str:
    _error_schema(document)["properties"].pop("retryable")
    return "components.schemas[Error].properties[retryable]"


def rename_a_response_field(document: dict) -> str:
    properties = _error_schema(document)["properties"]
    properties["isRetryable"] = properties.pop("retryable")
    return "components.schemas[Error].properties[retryable]"


def remove_an_enum_value(document: dict) -> str:
    document["components"]["schemas"]["ErrorCode"]["enum"].pop()
    return "components.schemas[ErrorCode].enum"


def _some_other_enum(document: dict) -> tuple[str, dict]:
    """A component schema carrying an `enum` that is not `ErrorCode`.

    Found rather than named: `ErrorCode` is the one enum a minor release may
    grow, and the rule under test is that *every other* enum is closed. A test
    naming one by hand would go vacuous the day that schema is renamed.
    """
    for name, schema in document["components"]["schemas"].items():
        if name != "ErrorCode" and isinstance(schema, dict) and isinstance(schema.get("enum"), list):
            return name, schema
    pytest.skip("the contract declares no closed enum other than `ErrorCode`")


def add_a_value_to_another_enum(document: dict) -> str:
    name, schema = _some_other_enum(document)
    schema["enum"] = [*schema["enum"], "a-value-no-client-expects"]
    return f"components.schemas[{name}].enum"


def close_an_open_field_with_an_enum(document: dict) -> str:
    """`type: string` -> `enum: [...]`: yesterday's valid value may be rejected today."""
    _error_schema(document)["properties"]["message"]["enum"] = ["only", "these"]
    return "components.schemas[Error].properties[message].enum"


def narrow_a_type(document: dict) -> str:
    _error_schema(document)["properties"]["message"]["type"] = "integer"
    return "components.schemas[Error].properties[message].type"


def tighten_a_ceiling(document: dict) -> str:
    _error_schema(document)["properties"]["message"]["maxLength"] = 8
    return "components.schemas[Error].properties[message].maxLength"


def add_a_pattern(document: dict) -> str:
    _error_schema(document)["properties"]["message"]["pattern"] = "^only-this$"
    return "components.schemas[Error].properties[message].pattern"


def make_a_field_required(document: dict) -> str:
    _error_schema(document)["properties"]["hint"] = {"type": "string"}
    _error_schema(document)["required"].append("hint")
    return "components.schemas[Error].required"


def change_a_reference(document: dict) -> str:
    _error_schema(document)["properties"]["code"]["$ref"] = "#/components/schemas/Id"
    return "components.schemas[Error].properties[code].$ref"


def require_authentication_on_an_open_endpoint(document: dict) -> str:
    for path, item in document["paths"].items():
        for method, operation in item.items():
            if method in checker.OPERATIONS and operation.get("security") == []:
                operation.pop("security")
                return f"paths[{path}].{method}.security"
    pytest.skip("the contract declares no unauthenticated operation to close")


def stop_requiring_a_response_field(document: dict) -> str:
    """A response field that becomes optional is a break, not a relaxation.

    Council round 1: the first cut treated every `required` removal as a
    relaxation, and the "compatible" fixture that was supposed to prove the
    request-side case safe actually mutated `Actor` — a response-only schema —
    so the matrix *certified* this break as compatible. A generated client
    makes a required field non-nullable and reads it unconditionally.
    """
    schema = _error_schema(document)
    schema["required"] = [name for name in schema["required"] if name != "retryable"]
    return "components.schemas[Error].required"


def swap_the_credential_an_operation_accepts(document: dict) -> str:
    """Collapsing `security` to "is it empty" hid every scheme and scope change."""
    for path, item in document["paths"].items():
        for method, operation in item.items():
            if method in checker.OPERATIONS and operation.get("security"):
                operation["security"] = [{"someOtherScheme": ["admin"]}]
                return f"paths[{path}].{method}.security.requirements"
    pytest.skip("the contract declares no authenticated operation")


def add_a_branch_to_an_all_of(document: dict) -> str:
    """`allOf` is an AND: a new branch narrows every value that validated before.

    Only removals were compared, so appending `maxLength: 4` to `ProjectId`
    truncated every project identifier in the contract with the gate green.
    """
    for name, schema in document["components"]["schemas"].items():
        if isinstance(schema, dict) and isinstance(schema.get("allOf"), list):
            schema["allOf"] = [*schema["allOf"], {"maxLength": 4}]
            return f"components.schemas[{name}].allOf"
    pytest.skip("the contract uses no `allOf`")


def change_a_default(document: dict) -> str:
    """A client that omits the field gets different behaviour and no error."""
    for name, parameter in document["components"]["parameters"].items():
        schema = parameter.get("schema")
        if isinstance(schema, dict) and "default" in schema:
            schema["default"] = "a-value-nobody-was-written-against"
            return f"components.parameters[{name}].schema.default"
    pytest.skip("no component parameter declares a `default`")


def rename_a_server_variable(document: dict) -> str:
    """`servers` was not walked at all; every generated client embeds it."""
    for server in document.get("servers") or []:
        variables = server.get("variables") or {}
        for name in list(variables):
            variables[f"{name}Renamed"] = variables.pop(name)
            return f"servers[{server.get('url', '')}].variables[{name}]"
    pytest.skip("the contract declares no server variable")


def add_a_required_parameter_to_a_path_item(document: dict) -> str:
    """Path-item parameters apply to every operation under the path.

    The walker looked only at operation keys, so this landed invisibly — and
    hoisting existing parameters up here, a pure refactor, reported them all as
    removed.
    """
    path = _first_path(document)
    document["paths"][path]["parameters"] = [
        {"name": "tenantId", "in": "query", "required": True, "schema": {"type": "string"}}
    ]
    method = next(k for k in document["paths"][path] if k in checker.OPERATIONS)
    return f"paths[{path}].{method}.parameters[tenantId:query]"


def demand_a_request_body_where_there_was_none(document: dict) -> str:
    """An operation that starts requiring a body every existing caller omits.

    Council round 2. 28 of the 40 operations in this contract carry no request
    body, and the `required` *inside* a newly added body is correctly suppressed
    — the media type is new — so without a rule for the body itself the whole
    change was silent.
    """
    for path, item in document["paths"].items():
        for method, operation in item.items():
            if method in checker.OPERATIONS and "requestBody" not in operation:
                operation["requestBody"] = {
                    "required": True,
                    "content": {
                        "application/json": {
                            "schema": {
                                "type": "object",
                                "required": ["reason"],
                                "properties": {"reason": {"type": "string"}},
                            }
                        }
                    },
                }
                return f"paths[{path}].{method}.requestBody"
    pytest.skip("every operation in the contract already has a request body")


def point_an_operation_at_a_required_component_parameter(document: dict) -> str:
    """A `$ref` to an already-required component parameter, added to an operation.

    Council round 2: the reference site claimed nothing was required and the
    component itself had not changed, so nothing fired — while every existing
    caller of that operation now omits a required header. 41 of the 90 operation
    parameters in this contract are `$ref`s.
    """
    required = next(
        (
            name
            for name, entry in document["components"]["parameters"].items()
            if isinstance(entry, dict) and entry.get("required")
        ),
        None,
    )
    if required is None:
        pytest.skip("no component parameter is declared required")
    reference = f"#/components/parameters/{required}"
    for path, item in document["paths"].items():
        for method, operation in item.items():
            if method not in checker.OPERATIONS:
                continue
            existing = operation.get("parameters") or []
            if any(p.get("$ref") == reference for p in existing if isinstance(p, dict)):
                continue
            operation["parameters"] = [*existing, {"$ref": reference}]
            return f"paths[{path}].{method}.parameters[{reference}]"
    pytest.skip("every operation already references that parameter")


def use_a_restriction_keyword_the_gate_does_not_model(document: dict) -> str:
    """The tripwire: abstaining loudly beats abstaining silently.

    `dependentRequired` rejects requests a conforming client sends today. The
    gate does not model it — so it says so and fails, rather than printing "no
    breaking change" over a keyword it never read.
    """
    _error_schema(document)["dependentRequired"] = {"code": ["message"]}
    return "components.schemas[Error].<unmodelled>"


BREAKING: list[Callable[[dict], str]] = [
    remove_an_endpoint,
    remove_an_operation,
    remove_a_response_status,
    remove_a_response_field,
    rename_a_response_field,
    remove_an_enum_value,
    add_a_value_to_another_enum,
    close_an_open_field_with_an_enum,
    narrow_a_type,
    tighten_a_ceiling,
    add_a_pattern,
    make_a_field_required,
    change_a_reference,
    require_authentication_on_an_open_endpoint,
    # Added in council round 1; every one of these was green before.
    stop_requiring_a_response_field,
    swap_the_credential_an_operation_accepts,
    add_a_branch_to_an_all_of,
    change_a_default,
    rename_a_server_variable,
    add_a_required_parameter_to_a_path_item,
    use_a_restriction_keyword_the_gate_does_not_model,
    # Added in council round 2; both were green after round 1.
    demand_a_request_body_where_there_was_none,
    point_an_operation_at_a_required_component_parameter,
]


@pytest.mark.parametrize("mutate", BREAKING, ids=lambda fn: fn.__name__)
def test_a_breaking_change_is_caught_and_named(
    baseline: dict, mutate: Callable[[dict], str]
) -> None:
    """Every rule in §"What is a breaking change" that a schema diff can see.

    The mutation returns the pointer it broke, and the finding must name it:
    "the gate went red" is worth much less to whoever reads the CI log than
    "the gate went red at this pointer".
    """
    candidate = copy.deepcopy(baseline)
    pointer = mutate(candidate)
    findings = checker.incompatibilities(baseline, candidate)

    assert findings, f"{mutate.__name__} is a breaking change and the gate stayed green"
    assert any(finding.startswith(f"{pointer}:") for finding in findings), (
        f"the gate fired but never named {pointer}. It said: {findings}"
    )


def add_an_endpoint(document: dict) -> None:
    document["paths"]["/api/v1/something-new"] = {
        "get": {
            "operationId": "getSomethingNew",
            "responses": {"200": {"description": "New."}},
        }
    }


def add_a_realistic_endpoint(document: dict) -> None:
    """An endpoint shaped like one someone would actually add.

    Council round 1, and the single worst defect this delivery had. The fixture
    above adds an operation with no parameters, no request body and no response
    schema — the one shape that dodges `_additions`. Against the *real*
    `feature/gh-11` and `feature/gh-13` branches, both purely additive, the gate
    reported **31** and **21** breaking changes; not one touched a pointer a
    1.6.0 client can address.

    A path parameter is `required: true` by OpenAPI rule, so the defect fired on
    every endpoint with one, forever. This fixture carries a path parameter, a
    constrained optional query parameter, a required request body and a response
    schema with its own `required` — every trigger at once.
    """
    document["paths"]["/api/v1/widgets/{widgetId}"] = {
        "get": {
            "operationId": "getWidget",
            "security": [{"bearerAuth": []}],
            "parameters": [
                {
                    "name": "widgetId",
                    "in": "path",
                    "required": True,
                    "schema": {"type": "string", "maxLength": 64, "pattern": "^[a-z-]+$"},
                },
                {
                    "name": "fields",
                    "in": "query",
                    "required": False,
                    "schema": {"type": "string", "enum": ["short", "full"]},
                },
            ],
            "requestBody": {
                "required": True,
                "content": {
                    "application/json": {
                        "schema": {
                            "type": "object",
                            "required": ["name"],
                            "properties": {"name": {"type": "string", "maxLength": 40}},
                        }
                    }
                },
            },
            "responses": {
                "200": {
                    "description": "A widget.",
                    "content": {
                        "application/json": {
                            "schema": {
                                "type": "object",
                                "required": ["id", "createdAt"],
                                "properties": {
                                    "id": {"$ref": "#/components/schemas/Id"},
                                    "createdAt": {"$ref": "#/components/schemas/Timestamp"},
                                },
                            }
                        }
                    },
                }
            },
        }
    }


def add_a_component_schema(document: dict) -> None:
    """A new schema arrives with its own `required` and constraints, and is referenced."""
    document["components"]["schemas"]["WidgetSummary"] = {
        "type": "object",
        "required": ["id", "label"],
        "properties": {
            "id": {"$ref": "#/components/schemas/Id"},
            "label": {"type": "string", "maxLength": 80, "pattern": "^[A-Za-z ]+$"},
        },
    }


def hoist_parameters_to_the_path_item(document: dict) -> None:
    """A pure refactor: path-item parameters apply to every operation under it.

    Reported five phantom removals before the walker learned to inherit them.
    """
    for path, item in document["paths"].items():
        for method, operation in item.items():
            if method in checker.OPERATIONS and operation.get("parameters"):
                item["parameters"] = operation.pop("parameters")
                return
    pytest.skip("no operation in the contract declares parameters to hoist")


def add_an_optional_response_field(document: dict) -> None:
    _error_schema(document)["properties"]["hint"] = {"type": "string"}


def add_a_value_to_error_code(document: dict) -> None:
    document["components"]["schemas"]["ErrorCode"]["enum"].append("brand_new_code")


def relax_a_ceiling(document: dict) -> None:
    _error_schema(document)["properties"]["message"]["maxLength"] = 65536


def drop_a_pattern(document: dict) -> None:
    for schema in document["components"]["schemas"].values():
        if isinstance(schema, dict) and "pattern" in schema:
            schema.pop("pattern")
            return
    pytest.skip("no schema in the contract carries a `pattern` to relax")


def widen_a_type(document: dict) -> None:
    _error_schema(document)["properties"]["message"]["type"] = ["string", "null"]


def rewrite_prose(document: dict) -> None:
    _error_schema(document)["description"] = "Completely different explanatory text."
    document["info"]["description"] = "Also rewritten."
    for item in document["paths"].values():
        for method, operation in item.items():
            if method in checker.OPERATIONS:
                operation["summary"] = "Reworded."
                operation["description"] = "Reworded, at length."


COMPATIBLE: list[Callable[[dict], None]] = [
    add_an_endpoint,
    add_a_realistic_endpoint,
    add_a_component_schema,
    hoist_parameters_to_the_path_item,
    add_an_optional_response_field,
    add_a_value_to_error_code,
    relax_a_ceiling,
    drop_a_pattern,
    widen_a_type,
    rewrite_prose,
]


@pytest.mark.parametrize("mutate", COMPATIBLE, ids=lambda fn: fn.__name__)
def test_a_compatible_change_is_left_alone(
    baseline: dict, mutate: Callable[[dict], None]
) -> None:
    """§"What is not breaking", asserted as loudly as its opposite.

    This half is not decoration. A classifier that flags an added optional
    field blocks every ordinary pull request, and the first person who needs to
    ship on a Friday deletes the gate rather than argues with it. The
    false-positive side is what decides whether this survives.
    """
    candidate = copy.deepcopy(baseline)
    mutate(candidate)
    findings = checker.incompatibilities(baseline, candidate)
    assert findings == [], (
        f"{mutate.__name__} is listed under §\"What is not breaking\" and the "
        f"gate flagged it: {findings}"
    )
