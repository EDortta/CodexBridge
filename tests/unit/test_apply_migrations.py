"""The migration runner, exercised against real throwaway databases.

The failure this guards against is not hypothetical: before this script existed,
`migrations/` had no runner at all, and `Base.metadata.create_all` — the only
schema bootstrap — issues `CREATE TABLE IF NOT EXISTS`, which never adds a
column to a table that already exists. Fresh installs got new columns; every
existing install did not, silently, until the first read.
"""

from __future__ import annotations

import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "apply_migrations.py"


def run(db: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(SCRIPT), "--database-url", f"sqlite:///{db}", *args],
        capture_output=True,
        text=True,
    )


@pytest.fixture
def legacy_db(tmp_path: Path) -> Path:
    """A database as `create_all` would have left it before issue #12."""
    db = tmp_path / "legacy.db"
    connection = sqlite3.connect(db)
    connection.executescript(
        "create table tasks (id varchar(128) primary key, state varchar(64) not null);"
        "insert into tasks (id, state) values ('t-old', 'running');"
    )
    connection.commit()
    connection.close()
    return db


def columns(db: Path, table: str) -> set[str]:
    return {row[1] for row in sqlite3.connect(db).execute(f"PRAGMA table_info({table})")}


def tables(db: Path) -> set[str]:
    return {row[0] for row in sqlite3.connect(db).execute("select name from sqlite_master where type='table'")}


def test_adopting_then_upgrading_adds_the_column_to_existing_rows(legacy_db: Path) -> None:
    assert "revision" not in columns(legacy_db, "tasks")

    adopted = run(legacy_db, "--mark-applied", "0001_init.sql")
    assert adopted.returncode == 0, adopted.stderr
    applied = run(legacy_db)
    assert applied.returncode == 0, applied.stderr

    assert "revision" in columns(legacy_db, "tasks")
    assert "idempotency_records" in tables(legacy_db)
    row = sqlite3.connect(legacy_db).execute("select id, state, revision from tasks").fetchone()
    assert row == ("t-old", "running", 1), "an existing row must get the default, not NULL"


def test_reapplying_is_a_no_op(legacy_db: Path) -> None:
    run(legacy_db, "--mark-applied", "0001_init.sql")
    run(legacy_db)
    again = run(legacy_db)
    assert again.returncode == 0
    assert "Up to date" in again.stdout


def test_failure_names_the_way_forward(legacy_db: Path) -> None:
    """The operator arrives here from a startup message naming this command.

    `0001_init.sql` is Postgres-only (`generated always as identity`), so on the
    default SQLite engine the bare command fails. A bare traceback would be a
    dead end: the message has to name the adopt step.
    """
    result = run(legacy_db)
    assert result.returncode == 1
    assert "--mark-applied 0001_init.sql" in result.stderr
    assert "Nothing was committed for" in result.stderr
    # The ledger must not record a migration that did not run.
    assert "schema_migrations" in tables(legacy_db)
    recorded = sqlite3.connect(legacy_db).execute("select filename from schema_migrations").fetchall()
    assert recorded == []


def test_dry_run_changes_nothing(legacy_db: Path) -> None:
    run(legacy_db, "--mark-applied", "0001_init.sql")
    result = run(legacy_db, "--dry-run")
    assert result.returncode == 0
    assert "pending: 0002_api_foundation.sql" in result.stdout
    assert "revision" not in columns(legacy_db, "tasks")


def test_unknown_migration_name_is_refused(legacy_db: Path) -> None:
    result = run(legacy_db, "--mark-applied", "9999_not_a_file.sql")
    assert result.returncode == 1
    assert "No such migration" in result.stderr
