#!/usr/bin/env python3
"""Refuse a contract change that breaks the minimum API version mobile still supports.

    python3 scripts/check_contract_compatibility.py     # exit 1 and name every break

`scripts/publish_contract.py` makes a version *pinnable*. This makes the pin
*worth something*: it compares the working document against the published copy
of the version named by `x-minimum-supported-version`, and fails when the
difference is one an existing, conforming client cannot survive.

The rules are not invented here. They are `docs/api/README.md` §"What is a
breaking change" and §"What is not breaking", transcribed into a comparison:

    removing an endpoint, a field, an enum value, a response status      breaking
    renaming anything                                                    breaking
    narrowing a type, tightening a constraint, a new required field      breaking
    a required field that stops being required (on a response)           breaking
    changing a `default`, or which credential an operation accepts       breaking
    an endpoint that stops being unauthenticated                         breaking
    adding an endpoint / an optional field / a response field            fine
    relaxing a constraint, widening a type                               fine
    adding a value to `ErrorCode`                                        fine (see below)
    editing `description` / `summary` text                               fine

A constraint counts as a *tightening* only when the thing it constrains already
existed. A brand-new endpoint's `required: true` path parameter constrains
nobody — and getting that wrong is not theoretical: before council round 1 this
gate reported 31 breaking changes against `feature/gh-11` and 21 against
`feature/gh-13`, both purely additive, and not one finding named a pointer a
1.6.0 client could address.

## What this cannot see, stated plainly

Read a green run as *"no mechanically visible break"*, never as *"compatible"*.
**Three** classes of breaking change pass this gate in silence, and all three
are in the README's own list:

- **A meaning change that keeps the name and the type.** `status` growing a new
  interpretation, `limit` counting something else, a field that used to be
  UTC becoming local. No schema diff catches this — the README says so where it
  lists the rule ("the most dangerous kind"). Nothing here changes that.
- **Default sort order.** A `default` *value* is compared; the order rows come
  back in is not expressible in the schema at all.
- **The identity or lifetime of a pagination cursor.** Same reason.

Two more are imprecise rather than silent, which is a different thing:

- **A rename is reported as a removal.** The verdict is right and the pointer is
  right; only the wording is imprecise.
- **Inside `allOf` / `anyOf` / `oneOf`**, members are compared as a set and not
  recursed into, so a constraint tightened *within* an existing branch reports
  as "1 branch removed" rather than naming the constraint. Compared positionally
  instead, reordering two equivalent branches would report two breaks — and a
  gate that cries wolf is a gate that gets deleted rather than obeyed. A branch
  *added* to an `allOf` is caught, because `allOf` is an AND. Five composition
  keywords exist in the document today.

And one is neither, because the gate says so out loud:

- **A restriction keyword this walker does not model** (`dependentRequired`,
  `readOnly`, `uniqueItems`, `if`/`then`, …) makes the gate **fail** with
  "this gate does not model … so it abstained rather than approving". None
  appears in the contract today. Silence over an unread keyword was the failure
  mode; a red build asking for a human is the fix.

Council round 1 found seven more gaps that are now closed rather than
documented, and this list is what it looked like before: `servers`,
path-item-level `parameters`, `components.requestBodies`, a `default` value,
which credential an operation accepts, a branch added to an `allOf`, and a
`required` name removed from a response schema — every one of them green.
`components.securitySchemes` **contents** are still not compared (its removal
is); every operation here carries the same scheme, so teach `_Facts._document`
about the group before that changes.

## Two conservative calls, on purpose

- A **type change is breaking unless the candidate is a strict superset** of the
  baseline's type set (`string` → `[string, "null"]` is widening). Anything else
  — including an exotic widening this rule does not model — reports.
- **`ErrorCode` is the one enum that may grow.** That is not a courtesy to a
  familiar name: the contract itself requires clients to degrade an unknown
  `code` to its HTTP status class, which is what makes the addition safe, and
  the README names it as the single exception. `test_the_error_code_exemption_still_has_a_schema`
  fails if that schema is renamed or removed, so the exemption cannot outlive
  the reason for it — the same rule `test_no_exclusion_outlives_its_route`
  applies to `x-contract-excluded-paths`.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Iterator

import yaml


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DOCUMENT = REPO_ROOT / "docs" / "api" / "codex-bridge.openapi.yaml"
DEFAULT_PUBLISHED = REPO_ROOT / "contract"
DOCUMENT_NAME = "codex-bridge.openapi.yaml"

#: Root extension naming the oldest published contract version this build still
#: promises to serve. It lives in the document rather than in this file so it
#: travels with the published artifact: a consumer that fetched
#: `contract/<v>/codex-bridge.openapi.yaml` can read the floor without cloning
#: this repository. Same reason `x-contract-excluded-paths` lives there.
MINIMUM_VERSION_KEY = "x-minimum-supported-version"

#: Written reason for a floor that is no longer the oldest published version.
#: Raising the floor is a deprecation — it drops the promise to every client
#: still on the old pin — and it is also the cheapest way to make a red
#: compatibility gate green, which is why it may not be a silent one-line diff.
#: `tests/contract/test_contract_compatibility.py::test_raising_the_floor_past_a_published_version_is_written_down`
#: is what enforces it, the same shape as the `reason` on an excluded path.
RAISED_FLOOR_KEY = "x-minimum-supported-version-raised"

OPERATIONS = frozenset(
    {"get", "put", "post", "delete", "options", "head", "patch", "trace"}
)

#: The one enum a minor release may grow. See the module docstring.
ERROR_CODE_ENUM_POINTER = "components.schemas[ErrorCode].enum"

#: Constraints whose *lower* value is the stricter one: shrinking a ceiling
#: rejects input and truncates output a conforming client relies on.
CEILINGS = ("maxLength", "maxItems", "maxProperties", "maximum", "exclusiveMaximum")

#: Constraints whose *higher* value is the stricter one.
FLOORS = ("minLength", "minItems", "minProperties", "minimum", "exclusiveMinimum")

#: Fact kinds that describe something a client can address by name. Their
#: disappearance is the removal the README's first rule is about. Every other
#: kind describes a *restriction*, and a restriction that disappears is a
#: relaxation — which is explicitly not breaking.
ADDRESSABLE = frozenset(
    {"endpoint", "operation", "response", "component", "property", "parameter",
     "header", "media", "server", "serverVariable"}
)

#: Fact kinds that are a restriction, so *appearing* where the baseline had
#: none is a tightening.
TIGHTENING_WHEN_ADDED = frozenset(
    {"required", "pattern", "format", "const", "ceiling", "floor",
     "closedProperties"}
)

#: JSON Schema keywords that *restrict* a value and that this walker does not
#: model. It does not compare them; it reports that one is present so the
#: reviewer knows the gate abstained, instead of the gate abstaining silently.
#: None of them appears in the contract today — the tripwire is what makes the
#: day one arrives a red build rather than an invisible one.
UNMODELLED_RESTRICTIONS = frozenset({
    "dependentRequired", "dependentSchemas", "propertyNames", "patternProperties",
    "prefixItems", "contains", "minContains", "maxContains", "uniqueItems",
    "multipleOf", "not", "if", "then", "else", "readOnly", "writeOnly",
    "unevaluatedProperties", "unevaluatedItems", "discriminator",
})


# --------------------------------------------------------------------------
# Reading the document down to comparable facts
# --------------------------------------------------------------------------


def _canonical(node: Any) -> str:
    """A stable string for an arbitrary sub-document.

    Used only where members are compared as an unordered set (composition
    keywords, enum values): two structurally identical members must produce one
    string, or set arithmetic would report a phantom removal.
    """
    return json.dumps(node, sort_keys=True, default=str)


def _type_set(value: Any) -> frozenset[str]:
    """`type` normalised to a set, because OpenAPI 3.1 allows a list."""
    if isinstance(value, list):
        return frozenset(str(item) for item in value)
    return frozenset({str(value)})


class _Facts:
    """Everything about a document that a client could break against.

    A flat `pointer -> (kind, value)` mapping rather than a tree, so the
    comparison is set arithmetic and every finding already carries the pointer
    that names it. `$ref` is recorded, never followed: the target is walked
    once at its own `components.…` pointer, so following it here would report a
    single component change once per reference site.
    """

    def __init__(self, document: dict) -> None:
        self.facts: dict[str, tuple[str, Any]] = {}
        #: Kept so a `$ref` can be resolved where the *reference site* is what
        #: changed. See `_parameter`.
        self.root = document
        self._document(document)

    def _emit(self, pointer: str, kind: str, value: Any = None) -> None:
        self.facts[pointer] = (kind, value)

    # -- document ----------------------------------------------------------

    def _document(self, document: dict) -> None:
        self._servers(document.get("servers"))

        for path, item in (document.get("paths") or {}).items():
            if not isinstance(item, dict):
                continue
            pointer = f"paths[{path}]"
            self._emit(pointer, "endpoint")
            # OpenAPI lets a path item declare parameters that apply to *every*
            # operation under it. Walking only the operation keys dropped them:
            # a new required one landed invisibly, and hoisting existing ones up
            # — a pure refactor — reported them all as removed.
            inherited = [p for p in (item.get("parameters") or []) if isinstance(p, dict)]
            for key, operation in item.items():
                if key.lower() not in OPERATIONS or not isinstance(operation, dict):
                    continue
                self._operation(operation, f"{pointer}.{key.lower()}", inherited)

        for group, entries in (document.get("components") or {}).items():
            if not isinstance(entries, dict):
                continue
            for name, entry in entries.items():
                pointer = f"components.{group}[{name}]"
                self._emit(pointer, "component")
                if group == "schemas":
                    self._schema(entry, pointer)
                elif group == "parameters":
                    self._parameter(entry, pointer, keyed=False)
                elif group == "responses":
                    self._response(entry, pointer)
                elif group == "headers":
                    self._header(entry, pointer)
                elif group == "requestBodies" and isinstance(entry, dict):
                    self._emit(pointer, "parameter", bool(entry.get("required")))
                    self._content(entry.get("content"), pointer)

    def _servers(self, servers: Any) -> None:
        """`servers` is where a generated client gets its base URL.

        Renaming a server variable renames it in every generated client, which
        §"What is a breaking change" covers under "renaming anything, in either
        direction". Keyed by URL template rather than by list position, so
        reordering two servers is not a rename.
        """
        if not isinstance(servers, list):
            return
        for server in servers:
            if not isinstance(server, dict):
                continue
            url = str(server.get("url", ""))
            pointer = f"servers[{url}]"
            self._emit(pointer, "server")
            for name, variable in (server.get("variables") or {}).items():
                variable_pointer = f"{pointer}.variables[{name}]"
                self._emit(variable_pointer, "serverVariable")
                if isinstance(variable, dict) and "enum" in variable:
                    values = variable["enum"]
                    if isinstance(values, list):
                        self._emit(
                            f"{variable_pointer}.enum",
                            "enum",
                            frozenset(_canonical(value) for value in values),
                        )

    def _operation(
        self, operation: dict, pointer: str, inherited: list[dict] | None = None
    ) -> None:
        self._emit(pointer, "operation")
        # An endpoint that stops being reachable without a credential breaks
        # every client that reached it — the probes are the whole reason a
        # client can decide anything before signing in.
        self._emit(
            f"{pointer}.security",
            "unauthenticated",
            operation.get("security") == [],
        )
        # …and separately, *which* credential. Collapsing the whole block to
        # that one boolean made a scheme swap or an added scope invisible on
        # every authenticated operation in the contract.
        security = operation.get("security")
        if isinstance(security, list):
            self._emit(
                f"{pointer}.security.requirements",
                "securityRequirements",
                frozenset(_canonical(requirement) for requirement in security),
            )
        for parameter in [*(inherited or []), *(operation.get("parameters") or [])]:
            self._parameter(parameter, pointer)
        body = operation.get("requestBody")
        if isinstance(body, dict):
            self._emit(f"{pointer}.requestBody", "requestBody", bool(body.get("required")))
            self._content(body.get("content"), f"{pointer}.requestBody")
        for status, response in (operation.get("responses") or {}).items():
            self._response(response, f"{pointer}.responses[{status}]", kind="response")

    def _parameter(self, parameter: Any, parent: str, keyed: bool = True) -> None:
        if not isinstance(parameter, dict):
            return
        if keyed:
            reference = parameter.get("$ref")
            if isinstance(reference, str):
                # A `$ref` parameter carries neither name nor `in` here, so the
                # reference string is its identity. Its `required` is resolved
                # from the component rather than assumed `False`: council round
                # 2 showed that pointing an existing operation at an
                # already-required component parameter — `IfMatch`, say —
                # passed in silence, because the component itself had not
                # changed and the reference site claimed nothing was required.
                # 41 of the 90 operation parameters in this contract are `$ref`s.
                self._emit(
                    f"{parent}.parameters[{reference}]",
                    "parameter",
                    self._component_parameter_is_required(reference),
                )
                return
            name = parameter.get("name")
            location = parameter.get("in")
            pointer = f"{parent}.parameters[{name}:{location}]"
        else:
            # A component parameter: `parent` already names it, and this
            # deliberately overwrites the bare `component` fact so its
            # `required` flag is compared too.
            pointer = parent
        self._emit(pointer, "parameter", bool(parameter.get("required")))
        self._schema(parameter.get("schema"), f"{pointer}.schema")

    def _component_parameter_is_required(self, reference: str) -> bool:
        """`required` of the component a parameter `$ref` points at."""
        prefix = "#/components/parameters/"
        if not reference.startswith(prefix):
            return False
        component = (self.root.get("components") or {}).get("parameters", {}).get(
            reference[len(prefix):]
        )
        return bool(isinstance(component, dict) and component.get("required"))

    def _header(self, header: Any, pointer: str) -> None:
        if not isinstance(header, dict):
            return
        if isinstance(header.get("$ref"), str):
            self._emit(f"{pointer}.$ref", "ref", header["$ref"])
            return
        self._schema(header.get("schema"), f"{pointer}.schema")

    def _response(self, response: Any, pointer: str, kind: str = "component") -> None:
        if not isinstance(response, dict):
            return
        if kind == "response":
            self._emit(pointer, "response")
        if isinstance(response.get("$ref"), str):
            self._emit(f"{pointer}.$ref", "ref", response["$ref"])
            return
        for name, header in (response.get("headers") or {}).items():
            header_pointer = f"{pointer}.headers[{name}]"
            self._emit(header_pointer, "header")
            self._header(header, header_pointer)
        self._content(response.get("content"), pointer)

    def _content(self, content: Any, pointer: str) -> None:
        if not isinstance(content, dict):
            return
        for media_type, media in content.items():
            media_pointer = f"{pointer}.content[{media_type}]"
            self._emit(media_pointer, "media")
            if isinstance(media, dict):
                self._schema(media.get("schema"), f"{media_pointer}.schema")

    def _schema(self, schema: Any, pointer: str) -> None:
        if not isinstance(schema, dict):
            return

        reference = schema.get("$ref")
        if isinstance(reference, str):
            self._emit(f"{pointer}.$ref", "ref", reference)
            return

        if "type" in schema:
            self._emit(f"{pointer}.type", "type", _type_set(schema["type"]))
        if "format" in schema:
            self._emit(f"{pointer}.format", "format", schema["format"])
        if "pattern" in schema:
            self._emit(f"{pointer}.pattern", "pattern", schema["pattern"])
        if "const" in schema:
            self._emit(f"{pointer}.const", "const", _canonical(schema["const"]))
        if isinstance(schema.get("enum"), list):
            self._emit(
                f"{pointer}.enum",
                "enum",
                frozenset(_canonical(value) for value in schema["enum"]),
            )
        if isinstance(schema.get("required"), list):
            self._emit(
                f"{pointer}.required",
                "required",
                frozenset(str(name) for name in schema["required"]),
            )
        for name in CEILINGS:
            if name in schema:
                self._emit(f"{pointer}.{name}", "ceiling", schema[name])
        for name in FLOORS:
            if name in schema:
                self._emit(f"{pointer}.{name}", "floor", schema[name])

        if "default" in schema:
            # A client that omits the field gets the server's default. Moving it
            # changes that client's behaviour with no code change on either
            # side — the same invisible flip §"What is a breaking change" names
            # for default sort order.
            self._emit(f"{pointer}.default", "default", _canonical(schema["default"]))

        # Tripwire. Every keyword above is modelled; a restriction keyword this
        # walker does not know about would otherwise be dropped in silence, and
        # the honesty list would keep claiming a completeness it lost. Reporting
        # it as "reviewed by hand" is the fail-loud version of a blind spot.
        unmodelled = sorted(UNMODELLED_RESTRICTIONS & set(schema))
        if unmodelled:
            self._emit(
                f"{pointer}.<unmodelled>",
                "unmodelled",
                _canonical({name: schema[name] for name in unmodelled}),
            )

        extra = schema.get("additionalProperties")
        if extra is False:
            self._emit(f"{pointer}.additionalProperties", "closedProperties", True)
        elif isinstance(extra, dict):
            self._schema(extra, f"{pointer}.additionalProperties")

        for keyword in ("allOf", "anyOf", "oneOf"):
            members = schema.get(keyword)
            if isinstance(members, list):
                # Set, not sequence: see the module docstring.
                self._emit(
                    f"{pointer}.{keyword}",
                    "composition",
                    frozenset(_canonical(member) for member in members),
                )

        for name, sub in (schema.get("properties") or {}).items():
            sub_pointer = f"{pointer}.properties[{name}]"
            self._emit(sub_pointer, "property")
            self._schema(sub, sub_pointer)

        self._schema(schema.get("items"), f"{pointer}.items")


def facts(document: dict) -> dict[str, tuple[str, Any]]:
    """Comparable facts for one OpenAPI document."""
    return _Facts(document).facts


# --------------------------------------------------------------------------
# Comparing two of them
# --------------------------------------------------------------------------


Finding = tuple[str, str]  # (pointer, what went wrong)


def _removals(before: dict, after: dict) -> Iterator[Finding]:
    """Facts the baseline had and the candidate does not.

    Only `ADDRESSABLE` kinds count. Every other kind is a *restriction*, and a
    restriction that disappears is a relaxation — a vanished `pattern`,
    `maxLength` or `enum` widens what the API accepts and returns, which
    §"What is not breaking" lists explicitly.
    """
    for pointer in sorted(set(before) - set(after)):
        kind, _ = before[pointer]
        if kind in ADDRESSABLE:
            yield pointer, (
                f"this {kind} was removed or renamed. A client that addresses "
                "it by name stops working."
            )
        elif kind == "required":
            # The whole `required` list vanished. On a *response* schema that is
            # a break: a generated client makes a required field non-nullable
            # and reads it unconditionally. It is a relaxation only on a
            # request-only schema, which a pointer cannot tell — most schemas
            # here are shared. Reported, with the direction named, so a
            # reviewer can say which it is instead of the gate guessing.
            yield pointer, (
                "every field here stopped being required. On a response that "
                "breaks a client reading them unconditionally; on a "
                "request-only schema it is a relaxation — say which in review."
            )
        elif kind == "default":
            yield pointer, (
                "the default was removed. A client that omits this field no "
                "longer gets the value it was written against."
            )


def _new_addressables(before: dict, after: dict) -> tuple[str, ...]:
    """Pointers of things the candidate introduces wholesale.

    A constraint is only a *tightening* when the thing it constrains already
    existed. Without this, adding an endpoint whose new query parameter carries
    a `pattern`, or adding an optional field with a `maxLength`, reported as
    breaking — three of the changes §"What is not breaking" lists by name. Two
    sibling branches are adding endpoints right now, so the gate would have gone
    red on exactly the work it is supposed to wave through.
    """
    return tuple(
        pointer
        for pointer in sorted(set(after) - set(before))
        if after[pointer][0] in ADDRESSABLE
    )


def _additions(before: dict, after: dict) -> Iterator[Finding]:
    """Facts the candidate gained. Only a *restriction* that appears is breaking."""
    fresh = _new_addressables(before, after)
    for pointer in sorted(set(after) - set(before)):
        kind, value = after[pointer]
        if any(pointer.startswith(f"{ancestor}.") for ancestor in fresh):
            # Born inside something that is itself new: nothing existed to
            # tighten. Applies to a new *required parameter* too — required on
            # an endpoint no client has ever called constrains nobody.
            # `test_a_compatible_change_is_left_alone[add_a_realistic_endpoint]`
            # is what keeps this branch honest: it carries a required path
            # parameter, a constrained query parameter, a required request body
            # and a response `required`, all at once.
            continue
        if kind == "requestBody" and value:
            # An existing operation that starts demanding a body. Council round
            # 2: 28 of the 40 operations here carry none today, and every
            # existing caller of one that gains a required body starts getting
            # 4xx. The `required` *inside* its schema is suppressed above —
            # the media type is new — so without this branch the whole change
            # was silent.
            yield pointer, (
                "this operation now requires a request body where it accepted "
                "none. Existing callers send nothing and start failing."
            )
        elif kind == "unmodelled":
            yield pointer, (
                f"this schema uses restriction keyword(s) this gate does not "
                f"model, so it abstained rather than approving: {value}. Review "
                "the change against docs/api/README.md §\"What is a breaking "
                "change\" by hand."
            )
        elif kind == "parameter" and value:
            yield pointer, "a new *required* parameter. Existing callers do not send it."
        elif kind == "required":
            yield pointer, (
                f"{sorted(value)} became required where nothing was; a message "
                "that omits them is now invalid."
            )
        elif kind == "enum":
            # `type: string` -> `enum: [a, b]` closes an open field. The
            # symmetric case (an `enum` disappearing) is a widening and is
            # deliberately not reported; see `_removals`.
            yield pointer, (
                f"an enum where the value was previously unconstrained; only "
                f"{sorted(value)} are accepted now."
            )
        elif kind in TIGHTENING_WHEN_ADDED:
            yield pointer, (
                f"a constraint that did not exist before ({kind}={value!r}). "
                "Input a client sends today may now be rejected."
            )


def _changes(before: dict, after: dict) -> Iterator[Finding]:
    """Facts present in both, compared in the direction that hurts a client."""
    for pointer in sorted(set(before) & set(after)):
        kind, old = before[pointer]
        new_kind, new = after[pointer]
        if kind != new_kind:
            yield pointer, f"changed from {kind} to {new_kind}."
            continue

        if kind == "type":
            # A strict superset is a widening (`string` -> `[string, "null"]`).
            # Everything else reports, including a widening this rule does not
            # model: over-reporting a rare relaxation beats missing a narrowing.
            if old != new and not old < new:
                yield pointer, f"type narrowed from {sorted(old)} to {sorted(new)}."
        elif kind == "enum":
            gone = sorted(old - new)
            if gone:
                yield pointer, (
                    f"enum value(s) {gone} removed. A client that receives or "
                    "sends them stops working."
                )
            arrived = sorted(new - old)
            if arrived and not pointer.endswith(ERROR_CODE_ENUM_POINTER):
                yield pointer, (
                    f"enum value(s) {arrived} added. Only `ErrorCode` may grow, "
                    "because the contract requires clients to degrade an unknown "
                    "code to its HTTP status class."
                )
        elif kind == "required":
            arrived = sorted(new - old)
            if arrived:
                yield pointer, f"{arrived} became required."
            departed = sorted(old - new)
            if departed:
                # See `_removals` for why this is reported rather than waved
                # through as a relaxation.
                yield pointer, (
                    f"{departed} stopped being required. On a response that "
                    "breaks a client reading them unconditionally; on a "
                    "request-only schema it is a relaxation — say which in review."
                )
        elif kind == "composition":
            gone = sorted(old - new)
            if gone:
                yield pointer, f"{len(gone)} branch(es) removed from the composition."
            arrived = sorted(new - old)
            if arrived and pointer.endswith(".allOf"):
                # `allOf` is an AND: a new branch is a new constraint on every
                # value that already validated. `oneOf`/`anyOf` are ORs, where
                # a new branch widens, so only `allOf` reports here.
                yield pointer, (
                    f"{len(arrived)} branch(es) added to an `allOf`, which "
                    "narrows every value that validated before."
                )
        elif kind == "securityRequirements":
            lost = sorted(old - new)
            if lost:
                yield pointer, (
                    "the credential this operation accepts changed; it no "
                    f"longer accepts {lost}. A client holding one stops working."
                )
        elif kind == "default":
            if old != new:
                yield pointer, (
                    f"the default changed from {old} to {new}. A client that "
                    "omits this field silently gets different behaviour."
                )
        elif kind == "unmodelled":
            # Only on a *change*. Yielding unconditionally would make the first
            # `readOnly: true` anywhere in the contract a permanent red build,
            # since the keyword would still be there tomorrow — and a gate that
            # cannot be made green by fixing the thing it complains about is a
            # gate that gets deleted. Council round 2 flagged this before it
            # could happen: no such keyword is in the contract today.
            if old != new:
                yield pointer, (
                    f"this schema's unmodelled restriction keyword(s) changed, "
                    f"and this gate does not compare them, so it abstained "
                    f"rather than approving: {new}. Review by hand against "
                    "docs/api/README.md §\"What is a breaking change\"."
                )
        elif kind == "ceiling":
            if _lt(new, old):
                yield pointer, f"ceiling lowered from {old!r} to {new!r}."
        elif kind == "floor":
            if _lt(old, new):
                yield pointer, f"floor raised from {old!r} to {new!r}."
        elif kind in ("pattern", "const", "format", "ref"):
            if old != new:
                yield pointer, f"{kind} changed from {old!r} to {new!r}."
        elif kind == "unauthenticated":
            if old and not new:
                yield pointer, (
                    "this operation no longer declares `security: []`. A client "
                    "that reached it without a credential now cannot."
                )
        elif kind == "requestBody":
            if new and not old:
                yield pointer, "the request body became required."
        elif kind == "parameter":
            if new and not old:
                yield pointer, "an optional parameter became required."


def _lt(left: Any, right: Any) -> bool:
    """`left < right` for constraint values, `False` when they are not comparable.

    A constraint written as a string in one document and a number in the other
    is a document bug, not a compatibility verdict; refusing to compare beats
    raising `TypeError` out of a gate.
    """
    try:
        return bool(left < right)
    except TypeError:
        return False


def incompatibilities(baseline: dict, candidate: dict) -> list[str]:
    """Every breaking change in `candidate` relative to `baseline`.

    Pure: two parsed documents in, findings out. The CLI below is a thin shell
    around it so a test can enumerate mutations without paying for a subprocess
    each time, and so a caller can reuse the classifier.

    Ordered **by pointer**, not by the rendered sentence. Removing one endpoint
    reports the endpoint and everything under it; sorting the sentences put
    `paths[/health].get.…properties[status]` above `paths[/health]`, because
    `.` sorts below `:`. The first line of a CI failure is the one that gets
    read, and it has to be the endpoint, not a leaf of it.
    """
    before = facts(baseline)
    after = facts(candidate)
    findings: list[Finding] = []
    findings += _removals(before, after)
    findings += _additions(before, after)
    findings += _changes(before, after)
    return [f"{pointer}: {text}" for pointer, text in sorted(findings)]


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------


def _load(path: Path) -> dict:
    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(document, dict):
        raise SystemExit(f"{path} is not a YAML mapping")
    return document


def minimum_supported_version(document: dict) -> str | None:
    value = document.get(MINIMUM_VERSION_KEY)
    return value if isinstance(value, str) and value.strip() else None


def baseline_path(document: dict, published: Path) -> Path:
    version = minimum_supported_version(document)
    if version is None:
        raise SystemExit(
            f"the document declares no `{MINIMUM_VERSION_KEY}`, so there is no "
            "floor to check compatibility against. Add it, naming a version "
            "published under contract/."
        )
    return published / version / DOCUMENT_NAME


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--document", type=Path, default=DEFAULT_DOCUMENT)
    parser.add_argument(
        "--published",
        type=Path,
        default=DEFAULT_PUBLISHED,
        help="Directory holding the published versions. Defaults to contract/.",
    )
    parser.add_argument(
        "--baseline",
        type=Path,
        default=None,
        help="Compare against this document instead of the published minimum.",
    )
    args = parser.parse_args(argv)

    if not args.document.is_file():
        print(f"No such contract document: {args.document}", file=sys.stderr)
        return 1
    candidate = _load(args.document)

    baseline_file = args.baseline or baseline_path(candidate, args.published)
    if not baseline_file.is_file():
        print(
            f"the minimum supported version names {baseline_file}, which does not "
            "exist. Publish it (`python3 scripts/publish_contract.py`) or point "
            f"`{MINIMUM_VERSION_KEY}` at a version that is published.",
            file=sys.stderr,
        )
        return 1

    findings = incompatibilities(_load(baseline_file), candidate)
    if findings:
        print(
            f"{len(findings)} breaking change(s) against the minimum supported "
            f"contract version ({baseline_file}):",
            file=sys.stderr,
        )
        for finding in findings:
            print(f"  - {finding}", file=sys.stderr)
        print(
            "\nA breaking change needs a new namespace (/api/v2) or a migration "
            "the operator accepted — see docs/api/README.md §\"What is a "
            "breaking change\". If the change is not breaking and this gate is "
            "wrong, say so in the pull request rather than editing the baseline: "
            "a published version is what a client pinned.",
            file=sys.stderr,
        )
        return 1

    print(f"No breaking change against {baseline_file}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
