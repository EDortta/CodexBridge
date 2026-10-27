from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from gateway.app.services.worker_leases import lease_is_active


def lease():
    now = datetime(2026, 10, 27, tzinfo=timezone.utc)
    return SimpleNamespace(worker_id="w1", project_id="codexbridge",
                           repository="EDortta/CodexBridge",
                           control_branch="codexbridge-control",
                           authorized_by="operator1", enabled_at=now,
                           expires_at=now + timedelta(hours=8), revoked_at=None)


def active(l, now=None, **kwargs):
    args = {"worker_id": "w1", "project_id": "codexbridge",
            "repository": "EDortta/CodexBridge", "control_branch": "codexbridge-control",
            "now": now or datetime(2026, 10, 27, 1, tzinfo=timezone.utc)}
    args.update(kwargs)
    return lease_is_active(l, **args)


def test_valid_eight_hour_lease():
    assert active(lease())


def test_expiry_is_exclusive():
    assert not active(lease(), datetime(2026, 10, 27, 8, tzinfo=timezone.utc))


def test_bad_binding_and_revocation():
    l = lease()
    assert not active(l, worker_id="another")
    assert not active(l, repository="other/repo")
    l.revoked_at = l.enabled_at
    assert not active(l)


def test_window_cannot_be_extended():
    l = lease()
    l.expires_at += timedelta(seconds=1)
    assert not active(l)


def test_naive_clock_fails_closed():
    assert not active(lease(), datetime(2026, 10, 27, 1))
