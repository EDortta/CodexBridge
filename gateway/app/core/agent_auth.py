"""Credential resolution for the `/agent/ws` handshake — issue #15.

The executor machine token used to arrive only as a query parameter, so every
component that logs a request line recorded it verbatim. The fix is to accept it
from a header instead, keeping the query form working for one release so the
gateway and the agent can be deployed independently.

Resolution lives here, apart from the endpoint, because the interesting part is
a decision — which credential was presented, and by which route — and a decision
is worth testing without standing up a WebSocket, a database and a registry.
"""

from __future__ import annotations

from enum import Enum


class TokenSource(str, Enum):
    """How the executor presented its machine token."""

    HEADER = "header"
    QUERY = "query"
    ABSENT = "absent"


def resolve_executor_token(
    *,
    header_token: str | None,
    query_token: str | None,
) -> tuple[str | None, TokenSource]:
    """Pick the credential to verify and report where it came from.

    The header wins when both are present: an agent that already sends the
    header is on the new path, and a stale query parameter left behind by a
    proxy or an old config must not silently downgrade it.

    Empty strings count as absent. A blank `?token=` is not a presented
    credential, and treating it as one would hand `secure_compare` an empty
    string to check against the registry.
    """
    header = (header_token or "").strip()
    if header:
        return header, TokenSource.HEADER

    query = (query_token or "").strip()
    if query:
        return query, TokenSource.QUERY

    return None, TokenSource.ABSENT
