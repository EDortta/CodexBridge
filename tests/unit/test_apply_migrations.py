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
    """A database as `create_all` would have left it before issue #12.

    `oauth_access_tokens` is here because 0003 alters it, and
    `oauth_authorization_codes` because 0004 does; a fixture that omits a table
    the migrations touch tests the runner against a schema no deployment has.
    Each carries a row for the same reason `tasks` does: what an ALTER does to
    existing data is the part worth asserting.
    """
    db = tmp_path / "legacy.db"
    connection = sqlite3.connect(db)
    connection.executescript(
        "create table tasks (id varchar(128) primary key, state varchar(64) not null);"
        "insert into tasks (id, state) values ('t-old', 'running');"
        "create table oauth_access_tokens ("
        "  token_hash varchar(128) primary key,"
        "  client_id varchar(255) not null,"
        "  user_id varchar(255) not null,"
        "  user_email varchar(255) not null,"
        "  scopes_json text,"
        "  expires_at timestamp with time zone not null,"
        "  created_at timestamp with time zone not null"
        ");"
        "insert into oauth_access_tokens values "
        "  ('hash-old', 'chatgpt-codexbridge', 'esteban', 'e@example.com', '[]',"
        "   '2099-01-01 00:00:00', '2026-01-01 00:00:00');"
        "create table oauth_authorization_codes ("
        "  code_hash varchar(128) primary key,"
        "  client_id varchar(255) not null,"
        "  redirect_uri varchar(2048) not null,"
        "  user_id varchar(255) not null,"
        "  user_email varchar(255) not null,"
        "  scopes_json text,"
        "  code_challenge varchar(255) not null,"
        "  code_challenge_method varchar(32) not null,"
        "  expires_at timestamp with time zone not null,"
        "  consumed_at timestamp with time zone,"
        "  created_at timestamp with time zone not null"
        ");"
        "insert into oauth_authorization_codes values "
        "  ('code-old', 'chatgpt-codexbridge', 'https://chatgpt.com/cb', 'esteban',"
        "   'e@example.com', '[]', 'chal', 'S256', '2099-01-01 00:00:00', null,"
        "   '2026-01-01 00:00:00');"
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


def test_the_auth_migration_leaves_existing_tokens_usable(legacy_db: Path) -> None:
    """0003 adds revocation without revoking the installed base.

    `revoked_at` is what `store.get_oauth_access_token` refuses on. A default
    that filled it in — or a NOT NULL column with a sentinel — would sign out
    ChatGPT and the operator at the moment of the deploy, which is the one
    outcome a migration adding revocation must not have.
    """
    run(legacy_db, "--mark-applied", "0001_init.sql")
    applied = run(legacy_db)
    assert applied.returncode == 0, applied.stderr

    assert {"grant_id", "revoked_at"} <= columns(legacy_db, "oauth_access_tokens")
    assert "oauth_refresh_tokens" in tables(legacy_db)
    row = (
        sqlite3.connect(legacy_db)
        .execute("select token_hash, grant_id, revoked_at from oauth_access_tokens")
        .fetchone()
    )
    assert row == ("hash-old", None, None), "an existing token must survive the migration"


def test_the_operators_email_is_gone_from_every_credential_table(legacy_db: Path) -> None:
    """`security-standards.md` §2 names e-mail, and the default database is in `~/Sync`.

    `store.issue_auth_grant` argued §2 in its own docstring while writing
    `user_email` into `oauth_access_tokens` and into `oauth_refresh_tokens` —
    the latter a table issue #4 created — and the test behind that argument
    asserted on `audit_events` alone. The reasoning retired the risk for the
    next reader while the field was still being written twice per sign-in.

    Every row already carries `user_id`, which is the key `users.json` is
    indexed by, so nothing is lost. The migration is what makes that true of
    databases that already exist rather than only of new ones.
    """
    run(legacy_db, "--mark-applied", "0001_init.sql")
    applied = run(legacy_db)
    assert applied.returncode == 0, applied.stderr

    for table in ("oauth_access_tokens", "oauth_authorization_codes", "oauth_refresh_tokens"):
        assert "user_email" not in columns(legacy_db, table), (
            f"{table} still stores the operator's e-mail in the clear"
        )

    # The rows themselves survive: this drops a column, it does not sign anyone
    # out or invalidate a code mid-flow.
    remaining = sqlite3.connect(legacy_db).execute(
        "select token_hash, user_id from oauth_access_tokens"
    ).fetchall()
    assert remaining == [("hash-old", "esteban")]


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
    # The ledger must not record a migration that did not run.
    assert "schema_migrations" in tables(legacy_db)
    recorded = sqlite3.connect(legacy_db).execute("select filename from schema_migrations").fetchall()
    assert recorded == []


def _write_migration(tmp_path: Path, name: str, body: str) -> Path:
    """A migration in a throwaway `migrations/` the script is pointed at.

    The script resolves `migrations/` relative to its own location, so the copy
    is what lets a test give it a file the repository does not contain. Copying
    the script rather than editing the repository's one is the point.
    """
    root = tmp_path / "runner"
    (root / "migrations").mkdir(parents=True, exist_ok=True)
    (root / "scripts").mkdir(parents=True, exist_ok=True)
    (root / "scripts" / "apply_migrations.py").write_text(
        SCRIPT.read_text(encoding="utf-8"), encoding="utf-8"
    )
    (root / "migrations" / name).write_text(body, encoding="utf-8")
    return root / "scripts" / "apply_migrations.py"


def run_script(script: Path, db: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(script), "--database-url", f"sqlite:///{db}", *args],
        capture_output=True,
        text=True,
    )


def test_a_semicolon_in_a_comment_is_not_a_statement(tmp_path: Path) -> None:
    """The failure `migrations/0003_mobile_auth.sql` hit the day it was written.

    The splitter cut on `;` and stripped comment lines from each chunk
    afterwards, so prose containing a semicolon was cut in half and its tail
    handed to the database: `OperationalError: near "like": syntax error`. What
    shipped as the fix was a note in the migration asking future authors not to
    write semicolons in comments — a guard at the caller, where every future
    migration is a caller (`design-standards.md` §3, `AGENTS.md` §3).
    """
    script = _write_migration(
        tmp_path,
        "0001_prose.sql",
        "-- A migration whose prose contains a semicolon; like this one.\n"
        "create table demo (id integer primary key);\n",
    )
    db = tmp_path / "prose.db"

    result = run_script(script, db)

    assert result.returncode == 0, result.stderr
    assert "demo" in {row[0] for row in sqlite3.connect(db).execute(
        "select name from sqlite_master where type='table'"
    )}


def test_a_half_applied_migration_is_not_reported_as_untouched(tmp_path: Path) -> None:
    """The runner must not tell the operator the database is clean when it is not.

    pysqlite autocommits DDL, so "one transaction per migration" does not hold
    on the default engine: the ALTERs before the failure are committed and only
    the ledger row rolls back. The message used to say "Nothing was committed
    for this file" regardless, and offered `--mark-applied` in the same breath —
    which would record a half-applied file as complete.
    """
    script = _write_migration(
        tmp_path,
        "0001_partial.sql",
        "alter table demo add column first_col varchar(16);\n"
        "this is not sql;\n",
    )
    db = tmp_path / "partial.db"
    sqlite3.connect(db).executescript("create table demo (id integer primary key);")

    result = run_script(script, db)

    assert result.returncode == 1
    columns_now = [row[1] for row in sqlite3.connect(db).execute("pragma table_info(demo)")]
    assert "first_col" in columns_now, "precondition: the first ALTER is committed"

    assert "Nothing was committed for" not in result.stderr, (
        "the runner claimed the database was untouched while a committed ALTER "
        f"is visible on it: {result.stderr}"
    )
    assert "PARTIALLY APPLIED" in result.stderr
    assert "1 statement(s) ran before the failure" in result.stderr


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


def test_engine_and_delivery_columns_default_existing_rows_to_codex(legacy_db: Path) -> None:
    """0008: an existing row must read back as what it always was -- a plain

    `codex exec` task -- not as a null engine that `RunnerPool.for_engine`
    then has to special-case.
    """
    adopted = run(legacy_db, "--mark-applied", "0001_init.sql")
    assert adopted.returncode == 0, adopted.stderr
    applied = run(legacy_db)
    assert applied.returncode == 0, applied.stderr

    assert {"engine", "issue_ref", "delivery_json", "delivery_result_json"} <= columns(legacy_db, "tasks")
    row = sqlite3.connect(legacy_db).execute(
        "select engine, issue_ref, delivery_json, delivery_result_json from tasks where id = 't-old'"
    ).fetchone()
    assert row == ("codex", None, None, None)
