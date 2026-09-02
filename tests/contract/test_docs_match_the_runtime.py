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

import re
from pathlib import Path

import pytest
from fastapi.routing import iter_route_contexts
from starlette.routing import Route as StarletteRoute

from gateway.app.api.rate_limit import RateLimitDependency
from gateway.app.main import app


REPO_ROOT = Path(__file__).resolve().parents[2]
API_README = REPO_ROOT / "docs" / "api" / "README.md"
API_TESTING = REPO_ROOT / "docs" / "api" / "testing.md"
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
    # `app.routes` holds one `_IncludedRouter` per `include_router()` call
    # rather than that router's flattened routes (FastAPI's lazy router
    # include), and the router-level `dependencies=[Depends(RateLimitDependency(...))]`
    # that actually guards these routes is only folded into the *effective*
    # dependant, not the sub-router's own unresolved one. `iter_route_contexts`
    # is the same recursion FastAPI's own `get_openapi` uses to see through
    # `_IncludedRouter`, and its `dependant` is the merged one.
    for route_context in iter_route_contexts(app.routes):
        path = route_context.path
        if not isinstance(route_context.original_route, StarletteRoute) or not path or not path.startswith("/api"):
            continue
        dependant = getattr(route_context, "dependant", None)
        if dependant is None:
            continue
        if any(
            isinstance(dependency.call, RateLimitDependency)
            for dependency in dependant.dependencies
            if dependency.call is not None
        ):
            limited.append(path)
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


@pytest.mark.parametrize(
    "denial",
    [
        # §"Getting the contract to the mobile repository", before issue #14.
        "Today there is none",
        "Nothing publishes it, nothing checksums it",
        # §Versioning.
        "Nothing enforces this today",
        # §"What the gate does not cover".
        "Body-level conformance is issue #14's scope. Until it lands",
        "nobody reads the `info.version` field as a working pin before #14 lands",
    ],
)
def test_the_api_readme_does_not_deny_the_publication_machinery_that_ships(denial: str) -> None:
    """§"Getting the contract to the mobile repository" described its own absence.

    It was written when "a consumer copies it by hand" was true, and it is the
    section a mobile developer reads *first* when asking how to get the
    contract. Left alone after issue #14, it would send that reader to copy the
    file by hand while a published, checksummed, pinnable artifact sat in
    `contract/` — the exact failure §"Rate limiting" already had once, in the
    document a client author reaches for.

    The precondition is asserted, not assumed: these sentences are only stale if
    the machinery that makes them false is really there.
    """
    published = sorted(
        path.name for path in (REPO_ROOT / "contract").glob("*") if path.is_dir()
    )
    assert published, "nothing is published under contract/; the denials are not stale yet"
    for script in ("publish_contract.py", "check_contract_compatibility.py"):
        assert (REPO_ROOT / "scripts" / script).is_file(), f"scripts/{script} is missing"

    prose = " ".join(API_README.read_text(encoding="utf-8").split())
    assert denial not in prose, (
        f"docs/api/README.md still says {denial!r}, while contract/ publishes "
        f"{published} and both contract scripts exist"
    )


def _contract_test_files() -> list[str]:
    return sorted(
        path.name for path in (REPO_ROOT / "tests" / "contract").glob("test_*.py")
    )


def test_the_testing_doc_counts_the_gates_that_exist() -> None:
    """`docs/api/testing.md` enumerates the gates; the enumeration must be true.

    Council round 1: the heading said "The four gates" over a five-row table
    while `tests/contract/` held six files, and the one missing from both it and
    `README.md` was `test_proxy_routes.py` — which is also the gate the same
    document went on to deny existed. A count is the cheapest thing in a
    document to leave behind, and this file is `docs/required-reading.md`'s
    **obrigatório** reading for anyone touching the contract.
    """
    files = _contract_test_files()
    prose = " ".join(API_TESTING.read_text(encoding="utf-8").split())
    spelled = {4: "four", 5: "five", 6: "six", 7: "seven", 8: "eight"}[len(files)]

    assert f"## The {spelled} gates" in prose, (
        f"tests/contract/ holds {len(files)} gate files {files}, and "
        f"docs/api/testing.md does not say \"The {spelled} gates\". Update the "
        "heading and the table together."
    )
    missing = [name for name in files if name not in prose]
    assert not missing, (
        f"docs/api/testing.md's gate table does not name {missing}. A reader "
        "uses it as the enumeration it claims to be."
    )


@pytest.mark.parametrize(
    "denial",
    [
        # Said while `test_proxy_routes.py` asserted precisely the opposite.
        "end-to-end reachability of a contracted route is not verified by this repository's tests.**",
        # Cited the Incus edge, retired 2026-08-10, as the live front door.
        "the nginx edge in `deploy/incus/` decides separately what it forwards",
        # Claimed an immutability `publish()` does not provide.
        "editing `contract/1.6.0/…` in place fails rather than quietly rewriting what a client already pinned. Ship a new version instead.",
        # Claimed the mobile repository already consumes the artifact.
        "`EDortta/CodexBridgeMobile` fetches that directory and verifies the digest",
    ],
)
def test_the_contract_docs_do_not_deny_what_ships(denial: str) -> None:
    """Sentences that were false when written, pinned so they cannot come back.

    Same mechanism as the rate-limiter denials above and the same reason: each
    of these was a statement about machinery, in the document a contract author
    or the mobile team reaches for first, that the code contradicted.

    Preconditions asserted, not assumed — a denial is only stale while the thing
    it denies is really there.
    """
    assert (REPO_ROOT / "tests" / "contract" / "test_proxy_routes.py").is_file()
    assert (REPO_ROOT / "deploy" / "nginx").is_dir(), "the live vhosts moved"
    assert "RETIRED" in (
        REPO_ROOT / "deploy" / "incus" / "codexbridge_edge_proxy.py"
    ).read_text(encoding="utf-8")[:200]

    for document in _contract_prose_documents():
        prose = " ".join(document.read_text(encoding="utf-8").split())
        assert denial not in prose, (
            f"{document.relative_to(REPO_ROOT)} still says {denial!r}, and it is "
            "not true of the code in this commit."
        )


def _contract_prose_documents() -> list[Path]:
    """Every document that describes the contract machinery in prose.

    Council round 2: the denial loop covered `README.md` and `testing.md`, and
    the issue's own `RESUME.md` — added by the same commit that retired those
    sentences — reinstated one of them (`deploy/incus/`) plus stale test counts.
    A handoff note is the first thing the next agent reads; leaving it outside
    the gate that polices the other two is the asymmetric-robustness shape
    `design-standards.md` §3 warns about.
    """
    documents = [API_README, API_TESTING]
    documents += sorted((REPO_ROOT / "docs" / "issues").rglob("RESUME.md"))
    return documents

def test_every_field_cited_as_never_shipping_is_actually_listed_there() -> None:
    """A pointer whose target does not contain the rule is worse than no pointer.

    `docs/api/README.md` §"Fields that must never ship" is cited as the
    authority by `migrations/0010_artifacts.sql`, `models/entities.py`, the
    tests, `routes/missions.py` and `docs/required-reading.md`. Issue #11 added `ArtifactModel.storage_path` and
    five such citations while the section itself still named only
    `ProjectModel.path` — so the next author, concretely whoever writes the
    ingestion path, would follow the pointer and not find the rule. A council
    round's second-caller lens found it.

    Checked by name rather than by prose: what a reader needs from that section
    is the identifier they are about to expose.
    """
    prose = " ".join(API_README.read_text(encoding="utf-8").split())
    start = prose.index("## Fields that must never ship")
    section = prose[start : prose.index("## Probes:", start)]

    for field in ("ProjectModel.path", "ArtifactModel.storage_path"):
        assert field in section, (
            f"{field} is treated across the codebase as a field that must never "
            'ship, and §"Fields that must never ship" does not name it'
        )


def test_no_shipped_file_still_promises_a_boot_gate_for_a_table_only_migration() -> None:
    """`REQUIRED_TABLES` does not fail a boot, and five files used to say it does.

    `gateway/app/main.py:startup` runs `Base.metadata.create_all` before
    `check_schema`, so a missing *table* is created rather than reported —
    pinned by
    `tests/unit/test_schema_guard.py::test_required_tables_cannot_fire_at_boot_today`.
    A council round found the correction reaching one document while
    `scripts/install.sh`, `deploy/README.md`, `scripts/apply_migrations.py`,
    `gateway/app/db/schema_guard.py` and `docs/required-reading.md` all still
    told an operator the service would crash-loop until they ran the migration.
    An operator who believes that skips the step and gets a schema with no
    indexes, no column defaults and no `schema_migrations` row, silently.

    Checked by requiring each of those files to carry the qualification, not by
    forbidding a phrase: the promise is *true* for `REQUIRED_COLUMNS` and
    `FORBIDDEN_COLUMNS`, so a blanket ban would delete a correct statement.
    `docs/installation.md` and `docs/security.md` are deliberately absent from
    this list — their claims are about `FORBIDDEN_COLUMNS` (migration 0004),
    which does fire.
    """
    must_qualify = {
        "scripts/install.sh": ("only adds TABLES", "REQUIRED_COLUMNS"),
        "deploy/README.md": ("only\n  adds *tables*", "silently"),
        "scripts/apply_migrations.py": ("missing *table* is not caught", "create_all"),
        "gateway/app/db/schema_guard.py": ("does not currently fail a boot", "create_all"),
        "docs/required-reading.md": ("REQUIRED_TABLES", "não"),
    }
    missing = []
    for name, needles in must_qualify.items():
        text = (REPO_ROOT / name).read_text(encoding="utf-8")
        for needle in needles:
            if needle not in text:
                missing.append(f"{name}: {needle!r}")
    assert not missing, (
        "these files promise a startup failure for a missing table and no longer "
        f"carry the qualification that it does not happen: {missing}"
    )


def test_the_env_example_does_not_claim_the_artifacts_root_is_the_checkout() -> None:
    """The one file an operator copies must not describe a default it does not have.

    `settings.artifacts_root` defaults to `data/artifacts` resolved against the
    process working directory at import — `/opt/codex-bridge/data/artifacts`
    under the systemd unit, and somewhere else for anything started elsewhere.
    `.env.example` said `<checkout>/data/artifacts`, which reads as a fixed,
    knowable location and invites leaving the variable unset. Two council
    lenses found it; `gateway/app/core/config.py` and `docs/security.md` had
    already been corrected around it.
    """
    text = (REPO_ROOT / ".env.example").read_text(encoding="utf-8")
    assert "CODEX_BRIDGE_ARTIFACTS_ROOT" in text
    assert "<checkout>/data/artifacts" not in text, (
        ".env.example still describes the unset artifacts root as living under the "
        "checkout; it resolves against the process working directory"
    )
    assert "working directory" in text, (
        ".env.example must say what the unset default actually resolves against"
    )


def test_the_installation_guide_names_every_setting_security_md_calls_mandatory() -> None:
    """`docs/security.md` says this one must be set at deploy; step 4 never named it.

    `.env.example` ships the line commented out, so building
    `/etc/codex-bridge/env` from it leaves the root unset — and a wrong root
    makes every download answer a typed `404` that names no path, which is a
    silent failure by design. Found by a council round's second-caller lens.
    """
    installation = (REPO_ROOT / "docs" / "installation.md").read_text(encoding="utf-8")
    assert "CODEX_BRIDGE_ARTIFACTS_ROOT" in installation, (
        "docs/security.md calls CODEX_BRIDGE_ARTIFACTS_ROOT mandatory for a deployment "
        "and docs/installation.md never names it"
    )


def test_no_document_names_a_capability_flag_the_probe_does_not_report() -> None:
    """A `false` flag a client can read is the point; a *missing* key is not one.

    Issue #13 shipped three artifacts asserting `GET /api/version` reports
    `pushNotifications: false` — the model, the route module and the migration.
    It reports no such key, so a client branching on
    `capabilities.pushNotifications === false` reads `undefined` and takes the
    wrong branch for the one capability the delivery went out of its way to
    describe as absent (council round 1, both the claim auditor and the second
    caller, independently).

    Scanned across the trees a client author actually reads. The check is
    "named as a capability", not "mentioned": the real name for this signal,
    `pushDeliveryAvailable`, lives in the preferences body and is not a
    `/api/version` flag at all.
    """
    from gateway.app.api.routes.probes import CAPABILITIES

    pattern = re.compile(r"`?GET /api/version`?[^\n]{0,200}?`(\w+)`\s*:\s*(?:true|false)")
    offenders: list[str] = []
    for tree in ("gateway", "migrations", "docs"):
        for path in sorted((REPO_ROOT / tree).rglob("*")):
            if path.suffix not in {".py", ".sql", ".md", ".yaml"} or not path.is_file():
                continue
            text = path.read_text(encoding="utf-8")
            for match in pattern.finditer(" ".join(text.split())):
                if match.group(1) not in CAPABILITIES:
                    offenders.append(f"{path.relative_to(REPO_ROOT)}: {match.group(1)}")

    assert not offenders, (
        "these claim GET /api/version reports a capability flag it does not have: "
        f"{offenders}. Either add the flag to probes.CAPABILITIES (only if a "
        "served endpoint honours it) or stop naming it."
    )


def test_the_codemap_names_the_canonical_checkout_not_a_worktree() -> None:
    """`governancekit map` stamps the root it was run from, and agents run in worktrees.

    Issue #13 was developed in `CodexBridge--gh-13` and committed a map whose
    `Root:`/`Refresh:` lines pointed at that throwaway directory, so anyone on
    `development` following the document's own refresh command would target a
    path that does not exist on their machine (council round 1, the claim
    auditor). The map's *content* is identical either way; only the provenance
    header is wrong, which is what makes it easy to ship.
    """
    header = " ".join(CODEMAP.read_text(encoding="utf-8").split()[:60])
    stray = re.findall(r"/[\w./-]*CodexBridge--[\w.-]+", header)
    assert not stray, (
        f"docs/codemap.md names a worktree as the project root: {stray}. "
        "Regenerate against the canonical checkout, or correct the header."
    )


def test_the_audit_payload_writer_count_is_the_real_one() -> None:
    """Five files tell a reader how many writers can put a key in an audit payload.

    That number is the whole premise of issue #13's whitelist: a reader auditing
    what may leak enumerates the writers. The delivery said "eleven" in five
    places while there were 31 — so an auditor following the prose would stop
    after roughly a third of them (council round 1, the claim auditor).
    """
    import ast

    spelled = {11: "eleven", 31: "thirty-one", 35: "thirty-five", 51: "fifty-one"}
    count = 0
    for path in (REPO_ROOT / "gateway").rglob("*.py"):
        if path.name == "audit.py":
            continue
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", None)
            if name == "record_event":
                count += 1

    truth = spelled.get(count)
    assert truth is not None, (
        f"there are now {count} record_event call sites and this test has no word "
        f"for it; add one to `spelled` and update the prose that names the number"
    )
    wrong = sorted(
        str(path.relative_to(REPO_ROOT))
        for tree in ("gateway", "docs", "tests")
        for path in (REPO_ROOT / tree).rglob("*")
        if path.is_file()
        and path.suffix in {".py", ".md"}
        and any(
            f"{word} call sites" in " ".join(path.read_text(encoding="utf-8").split())
            for word in spelled.values()
            if word != truth
        )
    )
    assert not wrong, (
        f"there are {count} ({truth}) record_event call sites; these still name a "
        f"different number: {wrong}"
    )
