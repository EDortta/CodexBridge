"""RFC 3339 in UTC, spelled one way.

The contract's `Timestamp` schema is stricter than `format: date-time` can
express: always UTC, always the literal `Z`, never a `+00:00` offset. Three
route modules were formatting timestamps by hand before this existed, and a
fourth spelling is one endpoint away — so the rule lives in one function that
every one of them calls.

Naive values are read as UTC rather than as local time. SQLite hands back a
column without a timezone while Postgres hands back an aware one, so a formatter
that trusted `tzinfo` produced a correct instant on one database and an instant
shifted by the server's offset on the other.
"""

from __future__ import annotations

from datetime import datetime, timezone


def utc_z(value: datetime | None) -> str | None:
    """`value` as an RFC 3339 UTC instant ending in `Z`, or None."""
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def now_z() -> str:
    """The current instant, in the same form."""
    return utc_z(datetime.now(timezone.utc))


def cursor_z(value: datetime) -> str:
    """Cursor form of a timestamp: ISO 8601, always carrying microseconds.

    `str(datetime)` omits the fractional part when it is zero, so a cursor
    built on a whole-second timestamp matches nothing and silently truncates
    the list it paginates. This round-trips through `datetime.fromisoformat`,
    which is what a keyset-pagination query compares against — `utc_z`'s
    trailing `Z` does not parse back with that function.
    """
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.isoformat()
