"""Contract tests for the canonical OpenAPI document.

Two things are checked here, and they fail for different reasons:

1. the document is a valid OpenAPI 3.1 description (a typo in the YAML is a
   broken contract, not a cosmetic problem);
2. the document and the running application agree about which public routes
   exist — in both directions.

Check 2 is the anti-drift gate. A route the application serves but the contract
omits is an undocumented public surface; a path the contract promises but the
application does not serve is a lie the mobile team will build against.

What this gate does NOT check: response and request *bodies*. It compares route
inventories only, so an endpoint returning a shape the contract does not
describe passes here. Body-level conformance is issue #14's scope
(`docs/api/README.md`, "What the gate does not cover"). Do not read a green run
as "the implementation matches the contract" — read it as "the same endpoints
exist on both sides".
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient
from openapi_spec_validator import validate
from openapi_spec_validator.readers import read_from_filename
from starlette.routing import Route as StarletteRoute
from starlette.routing import WebSocketRoute as StarletteWebSocketRoute

from gateway.app.main import app


REPO_ROOT = Path(__file__).resolve().parents[2]
SPEC_PATH = REPO_ROOT / "docs" / "api" / "codex-bridge.openapi.yaml"

# Starlette adds these itself for any GET route; they are never declared.
IMPLICIT_METHODS = {"HEAD", "OPTIONS"}

# Pseudo-method used to inventory WebSocket routes. They carry no HTTP method,
# and leaving them out entirely is how a public surface becomes invisible to a
# route-inventory gate. It can never collide with a documented operation:
# OpenAPI 3.1 has no `websocket` path-item key, so `_contract_routes` cannot
# emit it from a valid document.
WEBSOCKET_METHOD = "WEBSOCKET"

# The eight operation keys OpenAPI 3.1 allows in a path item. Matched as an
# allowlist: a denylist of non-operation keys silently turns anything OpenAPI
# adds later — `$ref` is already legal there — into a method name.
OPENAPI_OPERATIONS = frozenset(
    {"get", "put", "post", "delete", "options", "head", "patch", "trace"}
)

# The one path allowed under /api outside the versioned namespace. It exists so
# a client can discover which namespaces the server speaks *before* committing
# to one, which it cannot do from inside a namespace. Documented in
# docs/api/README.md, "The /api/version carve-out".
UNVERSIONED_API_PATHS = {"/api/version"}


def _is_api_path(path: str) -> bool:
    """Whether `path` is in the public API namespace.

    `/api` itself counts. Testing only `startswith("/api/")` left the bare path
    outside every namespace rule, so a namespace-index route at `/api` could be
    waived through the exclusion list and ship unversioned with the suite green.
    """
    return path == "/api" or path.startswith("/api/")


@pytest.fixture(scope="module")
def spec() -> dict:
    return yaml.safe_load(SPEC_PATH.read_text(encoding="utf-8"))


def _normalize(path: str) -> str:
    """Collapse path *parameter names* while preserving path *converters*.

    The contract uses camelCase parameter names for the mobile client while the
    Python handlers use snake_case; that difference is intentional and must not
    register as drift. A Starlette converter is a different matter: `{p:path}`
    matches an unbounded number of segments and `{n:int}` rejects the slug
    identifiers `components.schemas.Id` permits. Collapsing those into a plain
    `{}` would let a route masquerade as a documented one, so the converter is
    kept and only the name is dropped.

    An unbalanced brace is preserved verbatim rather than normalized. Dropping
    an unterminated parameter would turn `/tasks/{task_id` — which FastAPI
    accepts and serves as a literal path — into `/tasks/`, which can collide
    with a genuinely documented collection path and let the typo pass the gate
    as if it were the documented route. `test_route_paths_are_well_formed`
    reports it as its own readable failure.
    """
    out: list[str] = []
    depth = 0
    param: list[str] = []
    for char in path:
        if char == "{":
            depth += 1
            if depth == 1:
                param = []
                continue
        if char == "}":
            if depth == 0:
                # Unmatched closing brace: keep it literal so it cannot collapse
                # into some other path.
                out.append(char)
                continue
            depth -= 1
            if depth == 0:
                name = "".join(param)
                converter = name.partition(":")[2]
                out.append(f"{{:{converter}}}" if converter else "{}")
                continue
        if depth:
            param.append(char)
        else:
            out.append(char)
    if depth:
        # Unterminated parameter: emit the raw remainder, braces included.
        out.append("{" + "".join(param))
    return "".join(out)


def _brace_error(path: str) -> str | None:
    """Describe an unbalanced brace in `path`, or None when it is well formed."""
    depth = 0
    for char in path:
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth < 0:
                return "closing brace with no matching '{'"
    return "unterminated '{'" if depth else None


def _route_entries(route: object) -> set[tuple[str, str]]:
    """Every (path, METHOD) pair one route object exposes.

    Deliberately typed against Starlette's base classes rather than FastAPI's
    `APIRoute`. Not every route on a FastAPI app is an `APIRoute`: anything
    installed by the framework or mounted directly is a plain
    `starlette.routing.Route`, and an `isinstance(route, APIRoute)` filter drops
    those silently. That is how FastAPI's own `/openapi.json`, `/docs`,
    `/docs/oauth2-redirect` and `/redoc` stayed invisible to the first cut of
    this gate while it reported green. Those four are switched off now
    (`test_generated_openapi_is_not_served`), but the blind spot was in the
    filter, not in them.
    """
    path = getattr(route, "path", None)
    if path is None:
        return set()
    if isinstance(route, StarletteWebSocketRoute):
        return {(_normalize(path), WEBSOCKET_METHOD)}
    if isinstance(route, StarletteRoute):
        return {
            (_normalize(path), method)
            for method in (route.methods or set())
            if method not in IMPLICIT_METHODS
        }
    return set()


def _app_routes() -> set[tuple[str, str]]:
    """Every (path, METHOD) pair the application exposes, HTTP and WebSocket."""
    pairs: set[tuple[str, str]] = set()
    for route in app.routes:
        pairs |= _route_entries(route)
    return pairs


def _contract_routes(spec: dict) -> set[tuple[str, str]]:
    """Operations the document declares.

    Selected by an allowlist of the eight OpenAPI operation keys rather than by
    skipping the known non-operation ones. A denylist has to be extended every
    time OpenAPI grows a path-item key: `$ref` is legal there today and would
    have inventoried as a method named `$REF`.
    """
    pairs: set[tuple[str, str]] = set()
    for path, operations in (spec.get("paths") or {}).items():
        for key in operations:
            if key.lower() not in OPENAPI_OPERATIONS:
                continue
            pairs.add((_normalize(path), key.upper()))
    return pairs


def _excluded_routes(spec: dict) -> set[tuple[str, str]]:
    pairs: set[tuple[str, str]] = set()
    for entry in spec.get("x-contract-excluded-paths") or []:
        if not isinstance(entry, dict):
            continue
        path = entry.get("path")
        if not isinstance(path, str):
            continue
        methods = entry.get("methods")
        for method in methods if isinstance(methods, list) else []:
            pairs.add((_normalize(path), str(method).upper()))
    return pairs


def test_specification_is_valid_openapi() -> None:
    spec_dict, base_uri = read_from_filename(str(SPEC_PATH))
    validate(spec_dict, base_uri=base_uri)


def test_every_exclusion_is_well_formed(spec: dict) -> None:
    """An exclusion with no reason is a silent escape; §"Contract scope" forbids it."""
    for entry in spec.get("x-contract-excluded-paths") or []:
        assert isinstance(entry, dict), (
            "each exclusion must be a mapping with path/methods/reason, not "
            f"{type(entry).__name__}: {entry!r}"
        )
        path = entry.get("path")
        assert isinstance(path, str) and path, f"exclusion entry has no path: {entry!r}"
        methods = entry.get("methods")
        assert isinstance(methods, list) and methods, f"excluded path {path!r} lists no methods"
        reason = entry.get("reason")
        assert isinstance(reason, str) and reason.strip(), f"excluded path {path!r} has no reason"


def test_gate_sees_every_route_the_app_exposes() -> None:
    """No route class may be invisible to the inventory.

    Without this, a route type the helper does not recognise contributes nothing
    and the gate reports green while the surface is undocumented — which is
    exactly how `/openapi.json`, `/docs`, `/docs/oauth2-redirect` and `/redoc`
    escaped the first cut of this file.
    """
    invisible = [
        f"{type(route).__name__} {getattr(route, 'path', '<no path>')}"
        for route in app.routes
        if not _route_entries(route)
    ]
    assert not invisible, (
        f"routes the gate cannot see, so cannot check: {invisible}. Mounting a "
        "sub-application (`Mount`) or a host router (`Host`) fails here on "
        "purpose: their child routes are not inventoried, so the gate would "
        "report green over an unexamined surface. Teach `_route_entries` to "
        "recurse into it before adding one."
    )


def test_generated_openapi_is_not_served() -> None:
    """The canonical document is the only description of this gateway.

    FastAPI generates an OpenAPI document by introspecting the application and
    serves it at `/openapi.json`, with Swagger UI and ReDoc on top. That document
    lists the internal MCP and OAuth surfaces and carries none of this contract's
    rules, so publishing it alongside the canonical file put two public
    descriptions of one gateway on the wire — and the one a consumer reaches by
    convention was not the canonical one.

    `gateway/app/main.py` disables all three. This test fails if any of them
    comes back, whether by removing the arguments or by a FastAPI default
    changing underneath.
    """
    client = TestClient(app)
    for path in ("/openapi.json", "/docs", "/docs/oauth2-redirect", "/redoc"):
        response = client.get(path)
        assert response.status_code == 404, (
            f"{path} is served again ({response.status_code}); the gateway must "
            "expose no OpenAPI description other than the canonical contract"
        )
    assert app.openapi_url is None
    assert app.docs_url is None
    assert app.redoc_url is None


def test_no_public_route_is_missing_from_the_contract(spec: dict) -> None:
    undocumented = _app_routes() - _contract_routes(spec) - _excluded_routes(spec)
    assert not undocumented, (
        "these routes are served but appear neither in `paths` nor in "
        f"`x-contract-excluded-paths` of {SPEC_PATH.name}: {sorted(undocumented)}"
    )


def test_no_contract_path_is_unimplemented(spec: dict) -> None:
    unimplemented = _contract_routes(spec) - _app_routes()
    assert not unimplemented, (
        f"{SPEC_PATH.name} promises routes the gateway does not serve: {sorted(unimplemented)}"
    )


def test_no_exclusion_outlives_its_route(spec: dict) -> None:
    """A stale exclusion pre-authorizes whatever later claims that path.

    An entry whose route was renamed or deleted stays valid forever and silently
    covers any future route that reuses the path — the exclusion would never
    surface as undocumented.
    """
    orphaned = _excluded_routes(spec) - _app_routes()
    assert not orphaned, (
        "`x-contract-excluded-paths` excludes routes the gateway no longer "
        f"serves; delete these entries: {sorted(orphaned)}"
    )


def test_contract_and_exclusions_do_not_overlap(spec: dict) -> None:
    """A route cannot be both public API and deliberately out of scope."""
    overlap = _contract_routes(spec) & _excluded_routes(spec)
    assert not overlap, f"routes listed as both contract and excluded: {sorted(overlap)}"


def test_served_api_routes_are_versioned_and_contracted(spec: dict) -> None:
    """`/api/**` is the public namespace and cannot be excluded out of the contract.

    Checking the namespace rule against `paths` alone would be enforceable by
    evasion: a developer whose new `/api/tasks` route fails the undocumented-route
    check can read that failure message, add the route to
    `x-contract-excluded-paths`, and ship an unversioned public API surface with
    the whole suite green. The rule therefore runs against what the app *serves*.
    """
    served_api = {(path, method) for path, method in _app_routes() if _is_api_path(path)}
    contracted = _contract_routes(spec)
    excluded = _excluded_routes(spec)

    # OpenAPI 3.1 has no way to describe a WebSocket operation, so a WebSocket
    # under /api cannot be put in `paths` and would otherwise make the suite
    # unsatisfiable — no contract edit could turn it green. It is allowed in the
    # exclusion list, where it still has to carry a written reason, and its
    # protocol still has to be documented somewhere the reason names.
    http_api = {(path, method) for path, method in served_api if method != WEBSOCKET_METHOD}
    ws_api = served_api - http_api

    escaped = sorted(http_api - contracted)
    assert not escaped, (
        "routes under /api are public API and must appear in `paths`; they may "
        f"never be waived through `x-contract-excluded-paths`: {escaped}"
    )

    undeclared_ws = sorted(ws_api - excluded)
    assert not undeclared_ws, (
        "WebSocket routes under /api cannot be expressed in OpenAPI and must be "
        f"declared in `x-contract-excluded-paths` with a reason: {undeclared_ws}"
    )

    unversioned = sorted(
        (path, method)
        for path, method in served_api
        if not path.startswith("/api/v1/") and path not in UNVERSIONED_API_PATHS
    )
    assert not unversioned, f"paths under /api outside the /api/v1 namespace: {unversioned}"


def test_contract_declares_no_unversioned_api_path(spec: dict) -> None:
    """The same namespace rule, applied to what the document promises."""
    stray = [
        path
        for path in (spec.get("paths") or {})
        if _is_api_path(path) and not path.startswith("/api/v1/") and path not in UNVERSIONED_API_PATHS
    ]
    assert not stray, f"contract declares /api paths outside /api/v1: {stray}"


def test_route_paths_are_well_formed(spec: dict) -> None:
    """An unbalanced brace is a typo the router accepts and serves literally.

    FastAPI registers `@app.get("/tasks/{task_id")` without complaint and serves
    it as a literal path. Reported here by name, because every other assertion in
    this file would report it as a mysterious path mismatch.
    """
    malformed = []
    for route in app.routes:
        path = getattr(route, "path", None)
        if isinstance(path, str) and (problem := _brace_error(path)):
            malformed.append(f"served {path!r}: {problem}")
    for path in (spec.get("paths") or {}):
        if problem := _brace_error(path):
            malformed.append(f"contract {path!r}: {problem}")
    assert not malformed, f"path templates with unbalanced braces: {malformed}"


@pytest.mark.parametrize(
    ("served", "documented", "equivalent"),
    [
        ("/sessions/{session_id}", "/sessions/{sessionId}", True),
        ("/artifacts/{path:path}", "/artifacts/{filePath}", False),
        ("/tasks/{task_id:int}", "/tasks/{taskId}", False),
        ("/a/{x}/{y}", "/a/{xy}", False),
    ],
)
def test_normalize_matches_names_but_not_converters(served: str, documented: str, equivalent: bool) -> None:
    """snake_case vs camelCase is not drift; a converter difference is.

    `{p:path}` matches an unbounded number of segments and `{n:int}` rejects the
    slug identifiers the contract's `Id` schema permits. A helper that collapses
    both to `{}` lets those routes pass as their documented single-segment
    counterparts.
    """
    assert (_normalize(served) == _normalize(documented)) is equivalent


def test_reported_contract_version_matches_the_document(spec: dict) -> None:
    """`GET /api/version` must not claim a contract version the file disagrees with.

    A client that pins a contract version has no other way to learn what the
    server actually speaks. If these two drift, the pin is decoration: the client
    believes it validated compatibility and did not.
    """
    from gateway.app.api.routes.probes import API_CONTRACT_VERSION

    assert API_CONTRACT_VERSION == spec["info"]["version"], (
        "probes.API_CONTRACT_VERSION and info.version disagree; a change to the "
        "document must move both"
    )


def _without_pending(spec: dict) -> dict:
    """The document minus its own pending-components ledger.

    The ledger quotes each pointer, so counting references across the whole
    document would find every pending entry referencing itself — a check that
    can never fail is worse than no check.
    """
    return {key: value for key, value in spec.items() if key != "x-pending-components"}


def test_every_declared_component_is_referenced_or_owned(spec: dict) -> None:
    """A component nothing points at is a claim the API behaves that way.

    `parameters` and `responses` were added by issue #12 and referenced by
    nothing, so the document described request and response shapes no endpoint
    produced. A client reading the contract has no way to tell the difference.

    Unused is allowed — the shapes are worth settling before #9 writes endpoints
    — but only when `x-pending-components` names the issue that will use it. Same
    rule as `x-contract-excluded-paths`: on purpose, and in writing.
    """
    import json as _json

    pending = {
        entry.get("pointer"): entry.get("issue")
        for entry in (spec.get("x-pending-components") or [])
        if isinstance(entry, dict)
    }
    for pointer, issue in pending.items():
        assert isinstance(issue, int), f"pending component {pointer!r} names no issue"

    components = spec.get("components") or {}
    document = _json.dumps(_without_pending(spec))
    unreferenced: list[str] = []
    for group in ("parameters", "responses", "headers", "schemas"):
        for name in (components.get(group) or {}):
            pointer = f"#/components/{group}/{name}"
            if document.count(f'"{pointer}"') == 0 and pointer not in pending:
                unreferenced.append(pointer)
    assert not unreferenced, (
        "declared, referenced by nothing, and not listed in `x-pending-components` "
        f"with the issue that will use it: {unreferenced}"
    )


def test_no_pending_component_is_stale(spec: dict) -> None:
    """An entry whose component is now wired must be removed.

    Otherwise the pending list becomes a permanent exemption and stops meaning
    "not yet" — the same failure `test_no_exclusion_outlives_its_route` catches
    on the route side.
    """
    import json as _json

    document = _json.dumps(_without_pending(spec))
    stale = [
        entry["pointer"]
        for entry in (spec.get("x-pending-components") or [])
        if document.count(f'"{entry["pointer"]}"') > 0
    ]
    assert not stale, f"now referenced; remove from `x-pending-components`: {stale}"
