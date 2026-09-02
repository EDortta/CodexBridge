"""Credential resolution for the `/agent/ws` handshake — issue #15.

The executor machine token used to arrive as a query parameter, so every
component that logs a request line recorded it verbatim. The fix was to accept
it from the `X-Executor-Token` header instead, keeping the query form working
for one release so the gateway and the agent could be deployed independently.
That release has shipped: the query form is gone, and a handshake that presents
a credential only in the URL is now refused like any other anonymous one.

Resolution lives here, apart from the endpoint, because the interesting part is
a decision — whether a credential was presented at all — and a decision is worth
testing without standing up a WebSocket, a database and a registry.
"""

from __future__ import annotations


def resolve_executor_token(*, header_token: str | None) -> str | None:
    """Return the credential to verify, or `None` when none was presented.

    Empty and whitespace-only headers count as absent. A blank
    `X-Executor-Token:` is not a presented credential, and treating it as one
    would hand `secure_compare` an empty string to check against the registry —
    a comparison that exists only to be rejected, and that a registry entry with
    an empty `machine_token` would accept.
    """
    header = (header_token or "").strip()
    return header or None
