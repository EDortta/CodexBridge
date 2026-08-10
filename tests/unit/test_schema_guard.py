"""The guard that refuses to serve a database the code has outgrown.

`create_all` issues `CREATE TABLE IF NOT EXISTS`, which never adds a column to an
existing table. So the upgrade path and the clean-install path disagree: a fresh
database gets `tasks.revision`, an existing one does not, startup succeeds either
way, and only the first read that touches the column fails — with an error that
reads like a code bug.
"""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine, text

from gateway.app.db.base import Base
from gateway.app.db.schema_guard import SchemaOutOfDate, check_schema

# `Base.metadata` is populated as a side effect of importing the models. Without
# this import these tests build an *empty* schema and pass for the wrong reason —
# they did, silently, because another test module happened to import entities
# first. Running this file alone was the only way to see it.
import gateway.app.models.entities  # noqa: F401  (registers the tables)


def test_fresh_database_passes(tmp_path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path/'fresh.db'}")
    with engine.begin() as connection:
        Base.metadata.create_all(connection)
        check_schema(connection)


def test_missing_column_is_named_with_its_migration(tmp_path) -> None:
    """The message has to be actionable: what is missing, and what adds it."""
    engine = create_engine(f"sqlite:///{tmp_path/'old.db'}")
    with engine.begin() as connection:
        Base.metadata.create_all(connection)
        connection.execute(text("alter table tasks drop column revision"))
        connection.execute(text("drop table idempotency_records"))
        with pytest.raises(SchemaOutOfDate) as raised:
            check_schema(connection)
    message = str(raised.value)
    assert "tasks.revision" in message
    assert "idempotency_records" in message
    assert "0002_api_foundation.sql" in message
    assert "scripts/apply_migrations.py" in message


def test_create_all_does_not_repair_an_existing_table(tmp_path) -> None:
    """The premise of the guard, asserted rather than assumed.

    If `create_all` ever did add the column, this guard would be dead weight and
    should be deleted. It does not, and this is the test that would tell us.
    """
    engine = create_engine(f"sqlite:///{tmp_path/'stale.db'}")
    with engine.begin() as connection:
        Base.metadata.create_all(connection)
        connection.execute(text("alter table tasks drop column revision"))
    with engine.begin() as connection:
        Base.metadata.create_all(connection)
        columns = {row[1] for row in connection.execute(text("PRAGMA table_info(tasks)"))}
    assert "revision" not in columns
