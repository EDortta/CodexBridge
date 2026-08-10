"""Optimistic concurrency: two operators, two devices, one decision.

The scenario this exists for is concrete. A decision is shown on two phones. Both
operators tap Approve. Without a validator the second write silently overwrites
the first, and the audit trail records the second actor as the one who decided.

The validator is `TaskModel.revision`, a monotonic counter bumped by every
mutator in `gateway/app/services/store.py`. The timestamps cannot serve: none of
`started_at` / `completed_at` moves when `approval_state`, `approval_reason` or
`last_error` changes, so an ETag derived from them would be identical before and
after an approval — both concurrent writes would present a matching `If-Match`
and both would be accepted. That is why issue #2 refused to publish
`stale_write` before this column existed.
"""

from __future__ import annotations

from gateway.app.api.errors import STALE_WRITE, VALIDATION_FAILED, ApiError


ETAG_HEADER = "ETag"
IF_MATCH_HEADER = "If-Match"


def etag_for(revision: int) -> str:
    """The entity tag for a given revision, quoted as RFC 9110 requires."""
    return f'"{revision}"'


def _parse(candidate: str) -> str | None:
    """Normalize one entity tag, or None if it cannot match under `If-Match`.

    RFC 9110 §13.1.1 requires the **strong** comparison function for `If-Match`,
    and a weak validator never matches under it. Stripping the `W/` and treating
    `W/"7"` as `"7"` would be lenient in the one place leniency defeats the
    feature: a weak tag asserts semantic equivalence, and "semantically
    equivalent" is precisely what a second operator's approval is.
    """
    value = candidate.strip()
    if value.startswith("W/"):
        return None
    return value.strip('"')


def require_if_match(header: str | None, revision: int) -> None:
    """Reject a write whose `If-Match` does not name the current revision.

    A missing header is rejected rather than treated as "no opinion". A client
    that never sends `If-Match` is a client with no concurrency protection at
    all, and silently allowing it would make the protection opt-in on exactly
    the requests most likely to forget it.
    """
    if header is None or not header.strip():
        raise ApiError(
            status_code=428,
            code=VALIDATION_FAILED,
            message=(
                "This write requires an If-Match header carrying the ETag from "
                "the read that produced the value you are changing."
            ),
            details=[{"field": "If-Match", "code": "required", "message": "Send the ETag you last read."}],
        )
    tokens = [part.strip() for part in header.split(",") if part.strip()]
    # The wildcard is the bare token `*`, tested before quotes are stripped: a
    # quoted `"*"` is a legitimate entity-tag whose value happens to be an
    # asterisk, and treating it as the wildcard would let a client opt out of
    # concurrency control with a value the server itself could have issued.
    if any(token == "*" for token in tokens):
        # RFC 9110: `If-Match: *` means "as long as it exists". The entity was
        # loaded to get here, so it exists.
        return
    candidates = {parsed for token in tokens if (parsed := _parse(token)) is not None}
    if str(revision) not in candidates:
        raise ApiError(
            status_code=412,
            code=STALE_WRITE,
            message=(
                "This entity changed since you read it. Re-read it, show the "
                "current state, and let the operator decide again."
            ),
            headers={ETAG_HEADER: etag_for(revision)},
        )
