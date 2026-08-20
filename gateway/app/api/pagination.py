"""Cursor pagination for collections, and the offset scheme logs keep.

The contract makes a cursor opaque and single-purpose: one obtained from a
different endpoint, or from the same endpoint under different filters, is not
valid here and must be rejected rather than silently reinterpreted. That is
enforced by binding a digest of the scope into the cursor itself, so an
out-of-place cursor fails a comparison instead of paging through the wrong rows.

Append-only log streams are deliberately NOT cursor-paged. `store.get_logs` is
addressed by a monotonic integer offset and the MCP client already consumes the
same rows that way; wrapping an offset in a cursor would give one table two
paging vocabularies, and the contract makes changing a cursor's identity a
breaking change — so the wrapper could never be undone inside v1.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
from datetime import datetime, timezone

from gateway.app.api.errors import ApiError, VALIDATION_FAILED


DEFAULT_LIMIT = 50
MAX_LIMIT = 200

# Cursors are signed, not merely tagged. The scope digest is computed from public
# inputs — the endpoint path and the filters the client itself sent — so an
# unsigned cursor is forgeable by anyone who can read this file, and the decoded
# position flows straight into a query. A forged `{"after": "3"}` or `{"nope": 1}`
# was an unauthenticated remote 500.
#
# The default secret is random per process, which means cursors do not survive a
# restart or span replicas. That is the safe direction to fail: the client is
# told to restart pagination, and nothing is silently trusted. Deployments
# running more than one gateway process set CODEX_BRIDGE_API_CURSOR_SECRET.
_PROCESS_SECRET = secrets.token_bytes(32)


def _signing_key() -> bytes:
    from gateway.app.core.config import settings

    configured = getattr(settings, "api_cursor_secret", None)
    return configured.encode("utf-8") if configured else _PROCESS_SECRET


def scope_digest(endpoint: str, filters: dict | None = None) -> str:
    """Identity of "this endpoint under these filters", for cursor binding."""
    payload = json.dumps(
        {"endpoint": endpoint, "filters": filters or {}},
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


# A cursor longer than this is not a cursor. Bounded before any decoding so a
# multi-megabyte query string cannot buy attacker-controlled base64 and JSON work.
MAX_CURSOR_LENGTH = 512


def _b64encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def encode_cursor(scope: str, position: dict) -> str:
    payload = json.dumps({"s": scope, "p": position}, sort_keys=True, separators=(",", ":")).encode("utf-8")
    signature = hmac.new(_signing_key(), payload, hashlib.sha256).digest()[:16]
    return f"{_b64encode(payload)}.{_b64encode(signature)}"


def decode_cursor(scope: str, cursor: str, expect: dict[str, type] | None = None) -> dict:
    """Decode a cursor this server issued for `scope`, or fail with a typed error.

    Every failure mode collapses to one message on purpose. Telling a caller
    whether a cursor was malformed, unsigned, or valid but issued elsewhere
    describes server state to someone holding a token they were never given.

    `expect` names the keys the caller will read and their types. It is not
    decoration: without it, the decoded position is attacker-authored JSON handed
    straight to a query, and a missing key or a string where an int belongs
    surfaces as a 500 rather than a 400.
    """
    invalid = ApiError(
        status_code=400,
        code=VALIDATION_FAILED,
        message="The cursor is not valid for this request.",
        details=[{"field": "?cursor", "code": "invalid_cursor", "message": "Restart from the first page."}],
    )
    if len(cursor) > MAX_CURSOR_LENGTH or "." not in cursor:
        raise invalid
    encoded_payload, _, encoded_signature = cursor.partition(".")
    try:
        payload = base64.urlsafe_b64decode(encoded_payload + "=" * (-len(encoded_payload) % 4))
        signature = base64.urlsafe_b64decode(encoded_signature + "=" * (-len(encoded_signature) % 4))
    except Exception as exc:
        raise invalid from exc
    expected = hmac.new(_signing_key(), payload, hashlib.sha256).digest()[:16]
    if not hmac.compare_digest(signature, expected):
        raise invalid
    try:
        decoded = json.loads(payload)
    except Exception as exc:
        raise invalid from exc
    if not isinstance(decoded, dict) or decoded.get("s") != scope:
        raise invalid
    position = decoded.get("p")
    if not isinstance(position, dict):
        raise invalid
    for key, kind in (expect or {}).items():
        value = position.get(key)
        # bool is a subclass of int; a JSON `true` must not pass as an offset.
        if not isinstance(value, kind) or isinstance(value, bool) is not (kind is bool):
            raise invalid
    return position


def cursor_time(value: datetime) -> str:
    """Cursor form of a timestamp: ISO 8601, always carrying microseconds.

    `str(datetime)` omits the fractional part when it is zero, so a cursor built
    on a whole-second timestamp matched nothing and truncated the list with no
    error. `isoformat` round-trips through `datetime.fromisoformat`, which is
    what a store parses before comparing against the column.

    Not yet adopted by `routes/sessions.py`'s own `_cursor_time` (pre-existing,
    same logic) — issue #6 introduces this shared copy for `list_decisions_page`
    rather than touching that call site, per design-standards.md §7: converting
    an existing caller to a new shared helper is a separate, declared refactor,
    not a side effect of an unrelated feature's diff.
    """
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.isoformat()


def parse_limit(value: int | None, *, default: int = DEFAULT_LIMIT, maximum: int = MAX_LIMIT) -> int:
    if value is None:
        return default
    if value < 1:
        raise ApiError(
            status_code=400,
            code=VALIDATION_FAILED,
            message="limit must be at least 1.",
            details=[{"field": "?limit", "code": "below_minimum", "message": "limit must be at least 1."}],
        )
    # Clamping rather than rejecting: an over-large limit is a client asking for
    # too much, not a malformed request, and failing it would strand a client
    # that guessed the ceiling wrong.
    return min(value, maximum)


def page_info(*, has_more: bool, next_cursor: str | None) -> dict:
    """Build `PageInfo`, keeping its one invariant true by construction.

    The contract says `nextCursor` is null exactly when `hasMore` is false, and
    that clients must not infer the end of a list from a short page. Building the
    object anywhere else is how those two drift apart.
    """
    return {"hasMore": has_more, "nextCursor": next_cursor if has_more else None}


def paginate(items: list, *, limit: int, scope: str, position_of) -> tuple[list, dict]:
    """Trim an over-fetched list to `limit` and describe the page.

    Callers must fetch `limit + 1` rows. That extra row is what makes `hasMore`
    authoritative without a second COUNT query, and authoritative is what the
    contract promises — a client is forbidden from inferring the end of a list
    from a short page, because a page can be short when authorization filters
    rows out.
    """
    has_more = len(items) > limit
    page = items[:limit]
    cursor = encode_cursor(scope, position_of(page[-1])) if has_more and page else None
    return page, page_info(has_more=has_more, next_cursor=cursor)
