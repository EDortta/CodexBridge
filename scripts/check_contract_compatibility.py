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
    an endpoint that stops being unauthenticated                         breaking
    adding an endpoint / an optional field / a response field            fine
    relaxing a constraint, widening a type                               fine
    adding a value to `ErrorCode`                                        fine (see below)
    editing `description` / `summary` text                               fine

## What this cannot see, stated plainly

Read a green run as *"no mechanically visible break"*, never as *"compatible"*.
Four classes of breaking change pass this gate, and three of them are in the
README's own list:

- **A meaning change that keeps the name and the type.** `status` growing a new
  interpretation, `limit` counting something else, a field that used to be
  UTC becoming local. No schema diff catches this — the README says so where it
  lists the rule ("the most dangerous kind"). Nothing here changes that.
- **Default sort order, and the identity or lifetime of a pagination cursor.**
  Neither is expressible in the schema.
- **A rename is reported as a removal**, because that is what a rename looks
  like from the outside: the verdict is right, the wording is imprecise.
- **Inside `allOf` / `anyOf` / `oneOf`**, members are compared as a set and not
  recursed into, so a constraint tightened *within* a composition branch is
  invisible. Compared positionally instead, reordering two equivalent branches
  would report two breaks — and a gate that cries wolf is a gate that gets
  deleted rather than obeyed. Five such keywords exist in the document today.
- **Inside a `securitySchemes` entry.** Its *removal* reports, like any
  component; changing an existing one (bearer to apiKey, a different header
  name) does not. Every operation in this contract carries the same scheme, so
  the case has never arisen — teach `_Facts._document` about the group before it
  does.

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
     "header", "media"}
)

#: Fact kinds that are a restriction, so *appearing* where the baseline had
#: none is a tightening.
TIGHTENING_WHEN_ADDED = frozenset(
    {"required", "pattern", "format", "const", "ceiling", "floor",
     "closedProperties"}
)


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
        self._document(document)

    def _emit(self, pointer: str, kind: str, value: Any = None) -> None:
        self.facts[pointer] = (kind, value)

    # -- document ----------------------------------------------------------

    def _document(self, document: dict) -> None:
        for path, item in (document.get("paths") or {}).items():
            if not isinstance(item, dict):
                continue
            pointer = f"paths[{path}]"
            self._emit(pointer, "endpoint")
            for key, operation in item.items():
                if key.lower() not in OPERATIONS or not isinstance(operation, dict):
                    continue
                self._operation(operation, f"{pointer}.{key.lower()}")

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

    def _operation(self, operation: dict, pointer: str) -> None:
        self._emit(pointer, "operation")
        # An endpoint that stops being reachable without a credential breaks
        # every client that reached it — the probes are the whole reason a
        # client can decide anything before signing in.
        self._emit(
            f"{pointer}.security",
            "unauthenticated",
            operation.get("security") == [],
        )
        for parameter in operation.get("parameters") or []:
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
                # A `$ref` parameter carries neither name nor `in` here; the
                # reference string is its identity, and its `required` lives on
                # the component, which is walked separately.
                self._emit(f"{parent}.parameters[{reference}]", "parameter", False)
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


def _additions(before: dict, after: dict) -> Iterator[Finding]:
    """Facts the candidate gained. Only a *restriction* that appears is breaking."""
    for pointer in sorted(set(after) - set(before)):
        kind, value = after[pointer]
        if kind == "parameter" and value:
            yield pointer, "a new *required* parameter. Existing callers do not send it."
        elif kind == "required":
            yield pointer, (
                f"{sorted(value)} became required where nothing was. A request "
                "that omits them is now rejected."
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
        elif kind == "composition":
            gone = sorted(old - new)
            if gone:
                yield pointer, f"{len(gone)} branch(es) removed from the composition."
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
