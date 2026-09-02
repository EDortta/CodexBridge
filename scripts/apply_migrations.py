#!/usr/bin/env python3
"""Apply the SQL files in `migrations/`, once each, in filename order.

Run explicitly, by an operator:

    python3 scripts/apply_migrations.py                  # uses CODEX_BRIDGE_DATABASE_URL
    python3 scripts/apply_migrations.py --database-url sqlite:///./codex_bridge.db
    python3 scripts/apply_migrations.py --dry-run        # list what would run

**Startup does not call this.** Applying schema changes to a live database is an
operator decision, not a side effect of restarting a service. What startup does
do is refuse to serve when a *column* this build needs is missing
(`gateway/app/db/schema_guard.py`), so that failure is loud and names this
command instead of surfacing later on the first request.

**A missing *table* is not caught**, because `startup` runs
`Base.metadata.create_all` before `check_schema` and creates it. The gateway
then serves on a schema that has the tables but none of the `.sql`'s indexes or
column defaults, and with no `schema_migrations` row — silently. Every
table-only migration (0006, 0007, 0008) has that shape. Run this command;
do not infer from a clean start that you already did.

Why this exists: `migrations/` had no runner at all. The only schema bootstrap
was `Base.metadata.create_all`, which issues `CREATE TABLE IF NOT EXISTS` and
therefore never adds a column to a table that already exists. Fresh installs got
new columns and every existing install did not — silently, until the first read.

Adopting a database that predates this script:

    python3 scripts/apply_migrations.py --mark-applied 0001_init.sql

`0001_init.sql` is Postgres-only: `id integer primary key generated always as
identity` (lines 44 and 53) is a syntax error on SQLite, so the file cannot run
against the default engine at all. Databases here were bootstrapped by
`Base.metadata.create_all` rather than by that file — verified for the SQLite
dev database; a Postgres deployment *could* have been created from it by hand,
and `--mark-applied` is correct either way.

Marking it applied records that reality instead of pretending the file ran. It
is deliberately a separate, explicit flag: silently skipping a migration that
fails is how a schema and its ledger start lying to each other.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from sqlalchemy import create_engine, text
from sqlalchemy.exc import SQLAlchemyError


REPO_ROOT = Path(__file__).resolve().parents[1]
MIGRATIONS_DIR = REPO_ROOT / "migrations"

LEDGER_DDL = """
create table if not exists schema_migrations (
  filename varchar(255) primary key,
  applied_at timestamp not null
)
"""


def _sync_url(url: str) -> str:
    """Strip async drivers: this script runs synchronously on purpose."""
    return url.replace("+aiosqlite", "").replace("+asyncpg", "").replace("+aiomysql", "")


def _statements(sql: str) -> list[str]:
    """Split a migration into statements.

    **Comments are stripped before the split, not after.** The previous cut
    split on `;` first and dropped comment lines from each chunk afterwards, so
    a semicolon inside a comment — ordinary prose, `like this; and this` — cut
    the file mid-sentence and handed the tail to the database as a statement.
    That is not hypothetical: `migrations/0003_mobile_auth.sql` hit it on the day
    it was written, and the mitigation shipped was a note asking every future
    author to avoid semicolons in prose. A guard every caller must remember is a
    guard one caller will not remember (`design-standards.md` §3), and here every
    future migration is the caller.

    Still naive about semicolons inside **string literals** and procedural
    bodies. The migrations in this repository are plain DDL; if one ever needs a
    function body, this splitter must be replaced rather than worked around, and
    this comment is the warning.
    """
    without_comments = "\n".join(
        line for line in sql.splitlines() if not line.strip().startswith("--")
    )
    return [chunk.strip() for chunk in without_comments.split(";") if chunk.strip()]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--database-url",
        default=os.environ.get("CODEX_BRIDGE_DATABASE_URL", "sqlite:///./codex_bridge.db"),
        help="SQLAlchemy URL. Defaults to $CODEX_BRIDGE_DATABASE_URL, then the SQLite dev database.",
    )
    parser.add_argument("--dry-run", action="store_true", help="Report pending migrations without applying them.")
    parser.add_argument(
        "--mark-applied",
        action="append",
        default=[],
        metavar="FILENAME",
        help=(
            "Record a migration as applied WITHOUT running it, for a database that "
            "already has its objects. Repeatable. Use only when you have verified "
            "the schema matches."
        ),
    )
    args = parser.parse_args()

    files = sorted(MIGRATIONS_DIR.glob("*.sql"))
    if not files:
        print(f"No migrations found in {MIGRATIONS_DIR}", file=sys.stderr)
        return 1

    engine = create_engine(_sync_url(args.database_url), future=True)
    with engine.begin() as connection:
        connection.execute(text(LEDGER_DDL))
        applied = {row[0] for row in connection.execute(text("select filename from schema_migrations"))}

    known = {path.name for path in files}
    for name in args.mark_applied:
        if name not in known:
            print(f"No such migration: {name}. Known: {', '.join(sorted(known))}", file=sys.stderr)
            return 1
        if name in applied:
            print(f"already recorded: {name}")
            continue
        with engine.begin() as connection:
            connection.execute(
                text("insert into schema_migrations (filename, applied_at) values (:f, CURRENT_TIMESTAMP)"),
                {"f": name},
            )
        applied.add(name)
        print(f"marked applied without running: {name}")

    if args.mark_applied:
        # Marking only marks. A flag whose name says "record this as done"
        # must not also change the schema in the same breath: an operator
        # adopting a database is not necessarily ready to migrate it, and a
        # surprise DDL on a production database is the wrong kind of surprise.
        remaining = [path.name for path in files if path.name not in applied]
        if remaining:
            print(f"Still pending: {', '.join(remaining)}. Run again without --mark-applied to apply.")
        else:
            print("Nothing pending.")
        return 0

    pending = [path for path in files if path.name not in applied]
    if not pending:
        print(f"Up to date: {len(applied)} migration(s) already applied.")
        return 0

    if args.dry_run:
        for path in pending:
            print(f"pending: {path.name}")
        return 0

    for path in pending:
        print(f"applying {path.name} ...", end=" ", flush=True)
        # How many statements the database accepted before the failure. Needed
        # because "one transaction per migration" is a promise the engine keeps
        # only where DDL is transactional: SQLite's pysqlite driver autocommits
        # every ALTER and CREATE, so a file whose third statement fails leaves
        # the first two committed and the ledger row rolled back.
        executed = 0
        try:
            with engine.begin() as connection:
                for statement in _statements(path.read_text(encoding="utf-8")):
                    connection.execute(text(statement))
                    executed += 1
                connection.execute(
                    text("insert into schema_migrations (filename, applied_at) values (:f, CURRENT_TIMESTAMP)"),
                    {"f": path.name},
                )
        except SQLAlchemyError as exc:
            # A bare traceback here is a dead end for the operator, who arrived
            # from a startup message naming this exact command. Say what failed
            # and what the ways forward are.
            print("FAILED")
            print(f"\n{path.name} did not apply:\n  {exc.__class__.__name__}: {exc}\n", file=sys.stderr)
            if executed:
                # The message that used to print here said "Nothing was
                # committed for this file", unconditionally. That is false
                # whenever a statement succeeded first, and it is false in the
                # case that needs the operator most: they are told the database
                # is untouched while it may be half migrated, and the remedy
                # offered in the same breath would record a half-applied file as
                # complete. What this script can honestly say is how many
                # statements the database accepted — whether any of them changed
                # anything is a question about the file, so it is asked, not
                # answered.
                print(
                    f"WARNING: {executed} statement(s) ran before the failure, and this\n"
                    "engine may not roll back DDL — SQLite does not. The ledger row WAS\n"
                    "rolled back, so if any of those statements changed the schema, this\n"
                    "file is now PARTIALLY APPLIED and re-running it will fail on the part\n"
                    "that already succeeded.\n\n"
                    f"Read the first {executed} statement(s) of {path.name} before doing\n"
                    "anything else, and check the schema against them.",
                    file=sys.stderr,
                )
            else:
                print("The first statement failed, so nothing was committed for this file.", file=sys.stderr)
            print(
                "\nIf this database already has the objects that migration creates — the\n"
                "usual case for a database bootstrapped by the application rather than by\n"
                "this script, where every statement above was a no-op — record it as\n"
                "applied without running it:\n\n"
                f"    python3 scripts/apply_migrations.py --mark-applied {path.name}\n\n"
                "Do NOT do that if the statements above actually changed the schema: it\n"
                "would record a half-applied migration as complete and the next reader\n"
                "would have no way to tell. Otherwise the migration itself needs fixing.\n"
                "Later migrations were not attempted.",
                file=sys.stderr,
            )
            return 1
        print("ok")

    print(f"Applied {len(pending)} migration(s).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
