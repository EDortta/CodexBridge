"""Fail-closed validation of a Gateway-issued Worker activation lease."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

MAX_WINDOW = timedelta(hours=8)


def lease_is_active(lease: object, *, worker_id: str, project_id: str,
                    repository: str, control_branch: str, now: datetime) -> bool:
    """A lease is evidence of authorization only when all bindings match."""
    if now.tzinfo is None or now.utcoffset() is None:
        return False
    if not isinstance(worker_id, str) or not worker_id or not project_id:
        return False
    if not isinstance(repository, str) or not repository or not control_branch:
        return False
    try:
        enabled = lease.enabled_at
        expires = lease.expires_at
        revoked = lease.revoked_at
        if not isinstance(enabled, datetime) or not isinstance(expires, datetime):
            return False
        if enabled.tzinfo is None or expires.tzinfo is None:
            return False
        if enabled.utcoffset() is None or expires.utcoffset() is None:
            return False
        if revoked is not None:
            return False
        if expires - enabled != MAX_WINDOW:
            return False
        instant = now.astimezone(timezone.utc)
        if not (enabled.astimezone(timezone.utc) <= instant < expires.astimezone(timezone.utc)):
            return False
        return (
            lease.worker_id == worker_id and lease.project_id == project_id
            and lease.repository == repository and lease.control_branch == control_branch
            and bool(lease.authorized_by)
        )
    except (AttributeError, TypeError, ValueError, OverflowError):
        return False
