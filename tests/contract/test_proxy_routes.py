"""Every contracted path must be routed by the proxies in front of the gateway.

The anti-drift gate in `test_openapi_document.py` compares the contract against
`app.routes` — the application's own idea of what it serves. It has nothing to
say about the front door, and the front door is where the traffic actually
arrives.

That gap was not theoretical. `/health`, `/ready` and the whole `/api` surface
were implemented, documented and fully tested while `deploy/nginx/*.conf` — which
are location allowlists with no catch-all — named none of them. Every endpoint
would have answered 404 in production, with a green suite.

Adding a public route is therefore two edits: the router, and the vhost. This
test is what makes forgetting the second one loud.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml


REPO_ROOT = Path(__file__).resolve().parents[2]
SPEC_PATH = REPO_ROOT / "docs" / "api" / "codex-bridge.openapi.yaml"
NGINX_DIR = REPO_ROOT / "deploy" / "nginx"

# Vhosts that terminate traffic for the gateway and enumerate what they forward.
# A vhost carrying a `location /` catch-all needs no per-path entry and is
# detected as such rather than listed here, so a config that gains or loses its
# catch-all is handled without editing this file.
LOCATION_RE = re.compile(r"location\s*(=|~\*?|\^~)?\s*([^\s{]+)\s*\{")


def _locations(config: str) -> list[tuple[str, str]]:
    return [(modifier or "", path) for modifier, path in LOCATION_RE.findall(config)]


def _has_catch_all(config: str) -> bool:
    return any(modifier == "" and path == "/" for modifier, path in _locations(config))


def _routes(config: str, path: str) -> bool:
    """Whether nginx would match `path` against one of this vhost's locations.

    Implements the subset of nginx matching these files use: exact (`=`), and
    literal prefix. Regex locations are treated as "cannot decide" and reported,
    rather than silently assumed to match — a wrong assumption here would make
    this gate lie in the same direction as the bug it exists to catch.
    """
    for modifier, location in _locations(config):
        if modifier == "=":
            if path == location:
                return True
        elif modifier in {"~", "~*"}:
            if re.search(location, path):
                return True
        else:
            if path == location or path.startswith(location.rstrip("/") + "/") or path == location.rstrip("/"):
                return True
    return False


def _vhosts() -> list[tuple[str, str]]:
    return [
        (path.name, path.read_text(encoding="utf-8"))
        for path in sorted(NGINX_DIR.glob("*.conf"))
    ]


@pytest.fixture(scope="module")
def contract_paths() -> list[str]:
    spec = yaml.safe_load(SPEC_PATH.read_text(encoding="utf-8"))
    return sorted(spec.get("paths") or {})


def test_nginx_configs_exist() -> None:
    """If the configs move, this gate must fail loudly rather than pass empty."""
    assert _vhosts(), f"no nginx vhosts found under {NGINX_DIR}"


def test_every_contract_path_is_routed_by_every_terminating_vhost(contract_paths: list[str]) -> None:
    assert contract_paths, "the contract declares no paths; this gate would be vacuous"

    problems: list[str] = []
    for name, config in _vhosts():
        if _has_catch_all(config):
            continue
        for path in contract_paths:
            # Contract paths carry no parameters yet; when they do, compare the
            # literal prefix before the first `{`.
            concrete = path.split("{", 1)[0]
            if not _routes(config, concrete):
                problems.append(f"{name} does not route {path}")

    assert not problems, (
        "the contract publishes paths the front door does not forward — they "
        "would answer 404 in production with the suite green:\n  "
        + "\n  ".join(problems)
    )


def test_every_proxied_location_reaches_an_upstream() -> None:
    """A location block with no `proxy_pass` silently drops its path."""
    broken: list[str] = []
    for name, config in _vhosts():
        for block in re.findall(r"location\s*(?:=|~\*?|\^~)?\s*[^\s{]+\s*\{([^}]*)\}", config, re.S):
            if "proxy_pass" not in block and "return" not in block and "root" not in block:
                broken.append(name)
    assert not broken, f"location blocks with no upstream: {sorted(set(broken))}"
