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


def test_a_database_that_cannot_express_revocation_refuses_to_serve(tmp_path) -> None:
    """`revoked_at` is what makes a revoked token stop working.

    Without it the gateway starts, authenticates happily, and honours tokens the
    operator revoked — the one failure `POST /api/v1/auth/revoke` exists to
    prevent, presenting as nothing at all.
    """
    engine = create_engine(f"sqlite:///{tmp_path/'no-revocation.db'}")
    with engine.begin() as connection:
        Base.metadata.create_all(connection)
        connection.execute(text("alter table oauth_access_tokens drop column revoked_at"))
        connection.execute(text("drop table oauth_refresh_tokens"))
        with pytest.raises(SchemaOutOfDate) as raised:
            check_schema(connection)
    message = str(raised.value)
    assert "oauth_access_tokens.revoked_at" in message
    assert "oauth_refresh_tokens" in message
    assert "0003_mobile_auth.sql" in message


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


def test_engine_and_delivery_columns_are_required(tmp_path) -> None:
    """Migration 0008: engine/issue_ref/delivery_json/delivery_result_json.

    Without this entry, a database that predates 0008 starts successfully
    and only fails the first time `start_development_task` (or any code
    reading `task.engine`/`task.delivery_json`) touches one of these columns
    — the exact "reads like a code bug" failure this module exists to turn
    into a named startup refusal.
    """
    engine = create_engine(f"sqlite:///{tmp_path/'pre-0008.db'}")
    with engine.begin() as connection:
        Base.metadata.create_all(connection)
        connection.execute(text("alter table tasks drop column engine"))
        connection.execute(text("alter table tasks drop column issue_ref"))
        connection.execute(text("alter table tasks drop column delivery_json"))
        connection.execute(text("alter table tasks drop column delivery_result_json"))
        with pytest.raises(SchemaOutOfDate) as raised:
            check_schema(connection)
    message = str(raised.value)
    assert "tasks.engine" in message
    assert "tasks.issue_ref" in message
    assert "tasks.delivery_json" in message
    assert "tasks.delivery_result_json" in message
    assert "0008_engine_and_delivery.sql" in message

def test_required_tables_cannot_fire_at_boot_today() -> None:
    """`REQUIRED_TABLES` is documentation, not a boot gate — pinned, not fixed.

    `gateway/app/main.py:startup` runs `Base.metadata.create_all` one statement
    before `check_schema`, and every table `REQUIRED_TABLES` demands is also
    declared on `Base`. So a gateway started against a database missing any of
    them creates them itself and the guard sees them present: the missing-table
    half of this module can never fire on the real boot path. Only the
    `REQUIRED_COLUMNS` half can, because `CREATE TABLE IF NOT EXISTS` does not
    add a column to an existing table — which is the defect this module was
    written for.

    A council round found `docs/api/README.md` promising the opposite for
    migration 0010 ("fails at boot naming the file"). The prose is corrected;
    this test is what keeps it corrected. **It is not an endorsement.** The cost
    is real — a deployment that skips a migration silently runs the `create_all`
    schema, without the indexes and defaults the `.sql` carries and without a
    `schema_migrations` row. Moving `check_schema` ahead of `create_all` (or
    narrowing `create_all`) changes how every migration in this project is
    gated, so it is an operator's decision, not a side effect of one issue.

    **If someone makes the gate real, this test must fail.** Delete it then, and
    put the promise back in the prose it was taken out of.
    """
    import inspect

    from gateway.app.db.schema_guard import REQUIRED_TABLES
    import gateway.app.main as main

    declared_on_base = set(Base.metadata.tables)
    assert not set(REQUIRED_TABLES) - declared_on_base, (
        "some REQUIRED_TABLES entries are no longer created by `create_all`, so the "
        f"guard can now fire for them: {sorted(set(REQUIRED_TABLES) - declared_on_base)}. "
        "That is an improvement — update docs/api/README.md and delete this test."
    )

    # The other half, and the one the first cut of this test left unpinned: it
    # is the *order* in `startup` that disarms the guard, and a version that
    # only compared the two table sets would keep passing after someone made
    # the gate real — which is the drift in the opposite direction. A second
    # council round caught that. Read off the source because there is no other
    # observable: both calls are `run_sync` on the same connection.
    startup = inspect.getsource(main.startup)
    # The `run_sync(...)` calls, not any mention of the names: the comment above
    # them names `check_schema` first, and matching that made this assertion
    # fire on correct code.
    create_all_at = startup.index("run_sync(Base.metadata.create_all)")
    check_schema_at = startup.index("run_sync(check_schema)")
    assert create_all_at < check_schema_at, (
        "`check_schema` now runs before `create_all`, so REQUIRED_TABLES is a real "
        "boot gate. Put the promise back in docs/api/README.md §\"Deploy needs "
        "migration 0010\", in scripts/install.sh, in deploy/README.md and in "
        "scripts/apply_migrations.py, and delete this test."
    )
