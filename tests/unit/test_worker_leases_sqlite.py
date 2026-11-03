"""SQLite strips timezone information from persisted UTC lease timestamps."""
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from sqlalchemy import Column, DateTime, Integer, MetaData, Table, create_engine, insert, select
from gateway.app.services.worker_leases import lease_is_active


def test_sqlite_lease_roundtrip():
    engine = create_engine("sqlite:///:memory:")
    meta = MetaData()
    table = Table("leases", meta, Column("id", Integer, primary_key=True),
                  Column("enabled", DateTime(timezone=True)),
                  Column("expires", DateTime(timezone=True)))
    meta.create_all(engine)
    start = datetime(2026, 11, 3, 12, tzinfo=timezone.utc)
    with engine.begin() as connection:
        connection.execute(insert(table).values(id=1, enabled=start,
                              expires=start + timedelta(hours=8)))
        row = connection.execute(select(table)).one()
    assert row.enabled.tzinfo is None
    lease = SimpleNamespace(worker_id="devel3", project_id="codexbridge",
        repository="EDortta/CodexBridge", control_branch="codexbridge-control",
        authorized_by="operator:esteban", enabled_at=row.enabled,
        expires_at=row.expires, revoked_at=None)
    binding = dict(worker_id="devel3", project_id="codexbridge",
        repository="EDortta/CodexBridge", control_branch="codexbridge-control")
    assert lease_is_active(lease, now=start + timedelta(minutes=1), **binding)
    assert not lease_is_active(lease, now=start + timedelta(hours=8), **binding)
    assert not lease_is_active(lease, now=start.replace(tzinfo=None), **binding)
    assert not lease_is_active(lease, now=start + timedelta(minutes=1),
        **{**binding, "worker_id": "another"})
