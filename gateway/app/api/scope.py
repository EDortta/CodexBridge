"""Which requests the API's cross-cutting rules apply to.

One predicate, used by every handler and middleware in this package. It exists
as its own module because the alternative — each handler deciding for itself —
is how two code paths end up disagreeing about what is "the API", and the
disagreement is invisible until an endpoint returns the wrong error shape.

The MCP transport is deliberately outside. `POST /mcp` speaks JSON-RPC to
ChatGPT, and its error shape is fixed by that protocol; wrapping it in this
API's envelope would break the client that exists today in order to serve a
client that does not exist yet.
"""

from __future__ import annotations


# Paths served outside `/api` that are nevertheless part of the mobile contract.
# `/health` and `/ready` are here because a client probes them *before* it can
# know which API version to speak, so they cannot live inside `/api/v1`.
# Issue #3 implements them; listing them now means it inherits the envelope
# rather than having to remember to opt in.
CONTRACT_PATHS = frozenset({"/health", "/ready"})

CONTRACT_PREFIX = "/api"


def is_contract_path(path: str) -> bool:
    """Whether `path` is governed by docs/api/codex-bridge.openapi.yaml."""
    if path in CONTRACT_PATHS:
        return True
    return path == CONTRACT_PREFIX or path.startswith(CONTRACT_PREFIX + "/")
