"""Prose that states a runtime fact, checked against the runtime.

`tests/contract/test_openapi_document.py` guards the machine-readable half of
the contract. This file guards the half a human actually reads first, and only
for statements that are mechanically checkable — a document saying `/api` is
unlimited while every `/api` route carries the limiter is not a style question,
it is the client author deciding whether to implement `Retry-After` backoff from
a false premise.

Scope, deliberately narrow: sentences that were *observed* to go stale, pinned
one at a time. A general "the docs are true" test is not a thing that exists.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from starlette.routing import Route as StarletteRoute

from gateway.app.api.rate_limit import RateLimitDependency
from gateway.app.main import app


REPO_ROOT = Path(__file__).resolve().parents[2]
API_README = REPO_ROOT / "docs" / "api" / "README.md"
CODEMAP = REPO_ROOT / "docs" / "codemap.md"


def _codemap_ignored_directories(indexed: str) -> set[str]:
    """The directory names the map's own generator skips, read from the map.

    `docs/codemap.md` prints them under "Ignored Paths" as
    `- Built-in: \\`.git\\`, \\`build\\`, …`. Reading them from the document keeps
    this gate in step with whatever `governancekit map` currently ignores,
    instead of hardcoding a second list that drifts — `build/` alone holds a
    stale copy of nine gateway modules, and a hardcoded list that forgot it
    would fail on a perfectly fresh map.
    """
    for line in indexed.splitlines():
        if line.startswith("- Built-in:"):
            return {item.strip(" `") for item in line.split(":", 1)[1].split(",")}
    raise AssertionError(
        "docs/codemap.md has no 'Built-in:' line under Ignored Paths; this test "
        "cannot tell which directories the map is allowed to skip."
    )


def test_the_codemap_names_every_module_it_claims_to_index() -> None:
    """`.docs/agents/programmer.md` tells the next agent to read this instead of scanning.

    An index that omits a module is worse than no index: a reader following it
    concludes the thing is not there. Issue #4 added
    `gateway/app/api/{permissions,timestamps}.py` and
    `gateway/app/api/routes/auth.py` and did not regenerate the map, so the whole
    authorization catalogue and all four `/api/v1/auth` endpoints were invisible
    to it — while it still advertised a `require_scope` that no longer exists.

    **Every tree, not just `gateway/`.** The first cut of this gate walked
    `gateway/` alone, which is the shape of the defect it was written for and
    not the shape of the map: `docs/codemap.md` also indexes `shared/`,
    `agent/`, `scripts/`, `deploy/` and `tests/`, so a reader has every reason
    to trust it there, and a module added under any of them would have gone
    missing again with a green suite. A guard that covers one of several paths
    reads as covering all of them (`design-standards.md` §3).

    Regenerate with `governancekit --root . map`. Nothing does it automatically:
    `.git/hooks/` carries only samples, so this test is the reminder.
    """
    import ast

    indexed = CODEMAP.read_text(encoding="utf-8")
    ignored = _codemap_ignored_directories(indexed)

    def defines_a_symbol(path: Path) -> bool:
        """Whether the map would give this module a section of its own.

        `gateway/app/version.py` holds one constant and no `def`/`class`, so it
        appears in the tree and gets no section. Requiring one for it would make
        this test red on a perfectly fresh map — a gate that cries wolf is a
        gate that gets deleted.
        """
        tree = ast.parse(path.read_text(encoding="utf-8"))
        return any(
            isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
            for node in tree.body
        )

    missing = sorted(
        str(path.relative_to(REPO_ROOT))
        for path in REPO_ROOT.rglob("*.py")
        if not ignored & set(path.relative_to(REPO_ROOT).parts)
        and path.name != "__init__.py"
        and defines_a_symbol(path)
        and f"### `{path.relative_to(REPO_ROOT)}`" not in indexed
    )

    assert not missing, (
        "docs/codemap.md is stale — these modules have no entry: "
        f"{missing}. Regenerate with `governancekit --root . map`."
    )


def _rate_limited_api_routes() -> list[str]:
    """Served `/api` routes the limiter guards — the runtime fact the prose asserts.

    That *every* such route is guarded is already asserted by
    `tests/integration/test_probes.py::test_every_served_api_route_carries_the_rate_limiter`
    and is not re-asserted here. This is the precondition: a denial is only
    stale if the thing it denies is actually there.
    """
    limited: list[str] = []
    for route in app.routes:
        if not isinstance(route, StarletteRoute) or not route.path.startswith("/api"):
            continue
        if any(
            isinstance(dependency.call, RateLimitDependency)
            for dependency in route.dependant.dependencies
            if dependency.call is not None
        ):
            limited.append(route.path)
    return limited


@pytest.mark.parametrize(
    "denial",
    [
        "No middleware applies a limit to `/api`",
        "there are no `/api` endpoints",
        "do not read the contract's `429` as implemented",
        "guards `POST /mcp` only",
    ],
)
def test_the_api_readme_does_not_deny_the_limiter_that_ships(denial: str) -> None:
    """§"Rate limiting — vocabulary only, so far" outlived the wiring.

    It was written when the statement was true and left untouched by the sweep
    that added the auth section — which declared `429` on all four new
    `/api/v1/auth/*` operations and wrote the opposite assertion into
    `docs/security.md` in the same delivery. Two project documents in direct
    contradiction about one fact, and the one a client author reaches for was
    the wrong one.
    """
    limited = _rate_limited_api_routes()
    assert limited  # precondition: the denial really is false

    # Whitespace-normalized: the file is hard-wrapped at ~78 columns, so every
    # sentence worth checking straddles a newline and a literal search for one
    # silently finds nothing. A gate that cannot fail is worse than no gate.
    prose = " ".join(API_README.read_text(encoding="utf-8").split())

    assert denial not in prose, (
        f"docs/api/README.md still says {denial!r}, while {len(limited)} served "
        "/api routes carry RateLimitDependency"
    )
