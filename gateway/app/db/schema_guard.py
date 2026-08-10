"""Refuse to start on a database that is behind the code.

`Base.metadata.create_all` issues `CREATE TABLE IF NOT EXISTS`. On a database
that already has the table, that is a no-op — it never adds a column. So a
gateway upgraded onto an existing database starts *successfully*, creates any
brand-new table, and then fails on the first read that touches a new column,
with an error that reads like a code bug rather than a schema bug.

That is exactly what happened when `tasks.revision` was introduced: fresh
installs were fine and every existing install was broken, silently, until the
first request. This module turns that into a startup failure that names the
missing object and the command that fixes it.

It checks presence, not shape. Verifying types and defaults would duplicate the
migrations in Python and drift from them; the point here is to catch "the
migration was never run", which is the failure that actually occurs.
"""

from __future__ import annotations

from sqlalchemy import inspect
from sqlalchemy.engine import Connection


APPLY_COMMAND = "python3 scripts/apply_migrations.py"

# A database created by `create_all` has never run 0001_init.sql, and that file
# does not parse on SQLite — so the bare command above fails on exactly the
# deployments this message is written for. Naming the adopt step here keeps the
# operator from arriving at a traceback.
ADOPT_HINT = (
    "If this database was created by the application rather than by that script, "
    "adopt it first: `python3 scripts/apply_migrations.py --mark-applied 0001_init.sql`."
)

# Objects introduced after 0001_init.sql, with the migration that adds each one.
# Extend this when a migration adds a table or a column the code depends on;
# without an entry here, the next upgrade fails at request time instead of at
# startup.
REQUIRED_TABLES: dict[str, str] = {
    "idempotency_records": "0002_api_foundation.sql",
}

REQUIRED_COLUMNS: dict[str, dict[str, str]] = {
    "tasks": {"revision": "0002_api_foundation.sql"},
}


class SchemaOutOfDate(RuntimeError):
    """The database is missing something a migration was supposed to add."""


def check_schema(connection: Connection) -> None:
    inspector = inspect(connection)
    existing_tables = set(inspector.get_table_names())
    missing: list[str] = []

    for table, migration in REQUIRED_TABLES.items():
        if table not in existing_tables:
            missing.append(f"table {table!r} (added by {migration})")

    for table, columns in REQUIRED_COLUMNS.items():
        if table not in existing_tables:
            # The table itself is absent, which `create_all` will have handled on
            # a fresh database. Reporting its columns too would be noise.
            continue
        present = {column["name"] for column in inspector.get_columns(table)}
        for column, migration in columns.items():
            if column not in present:
                missing.append(f"column {table}.{column} (added by {migration})")

    if missing:
        raise SchemaOutOfDate(
            "The database is missing objects this build requires: "
            + "; ".join(missing)
            + f". Run `{APPLY_COMMAND}` against this database, then start again. "
            + ADOPT_HINT
            + " Startup does not migrate on its own: applying schema changes to a "
            "live database is an operator decision, not a side effect of a deploy."
        )
