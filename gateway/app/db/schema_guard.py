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
    "oauth_refresh_tokens": "0003_mobile_auth.sql",
    "epics": "0006_epics_issues.sql",
    "issues": "0006_epics_issues.sql",
    "conversations": "0007_conversations.sql",
    "conversation_messages": "0007_conversations.sql",
    "conversation_read_states": "0007_conversations.sql",
    # Issue #73's control plane. Registered as a block: the five arrived in one
    # migration and a database missing any one of them is missing all of them.
    "nodes": "0009_control_plane.sql",
    "workspace_bindings": "0009_control_plane.sql",
    "scm_associations": "0009_control_plane.sql",
    "project_authorizations": "0009_control_plane.sql",
    "discovered_resources": "0009_control_plane.sql",
    # Issue #11's artifact catalogue. Renumbered to 0010 on the way into
    # `development`: 0008 and 0009 were taken by the time this merged.
    "artifacts": "0010_artifacts.sql",
    "android_builds": "0010_artifacts.sql",
    "artifact_download_tokens": "0010_artifacts.sql",
    # Issue #13's event stream adds no table of its own — it reads `audit_events`,
    # which 0001 already created. This is the notification-preferences table, the
    # one thing that issue does persist.
    "notification_preferences": "0011_event_subscriptions.sql",
    # Issue #76 (minimal cut): enrollment invites. Missing this table means
    # `POST /api/v1/nodes/invite` and `POST /api/v1/nodes/enroll` fail on
    # their first query with a driver error instead of at startup.
    "node_invites": "0013_node_enrollment.sql",
}

# READ THIS BEFORE TRUSTING THE TABLE ABOVE.
#
# `REQUIRED_TABLES` does not currently fail a boot. `gateway/app/main.py:startup`
# runs `Base.metadata.create_all` one statement before `check_schema`, and every
# table named above is also declared on `Base` — so a gateway started against a
# database missing any of them creates them itself and the guard sees them
# present. A council round reproduced it against a database at 0007.
#
# It is still worth maintaining: it names which migration owns which object, it
# is what a reader consults, and it becomes a real gate the moment the ordering
# changes. But an entry here is **not** the "the failure appears at startup"
# guarantee that `REQUIRED_COLUMNS` and `FORBIDDEN_COLUMNS` genuinely provide —
# `CREATE TABLE IF NOT EXISTS` never adds a column, which is why those two fire
# and this one does not.
#
# What a skipped table-only migration actually costs: the `create_all` schema
# instead of the shipped one — no indexes, no column defaults from the `.sql` —
# and no `schema_migrations` row, so the next migration's bookkeeping starts
# from a wrong premise. Nothing warns.
#
# Pinned by `tests/unit/test_schema_guard.py::test_required_tables_cannot_fire_at_boot_today`,
# which fails if someone makes the gate real — at which point this comment,
# `docs/api/README.md`, `scripts/install.sh`, `deploy/README.md` and
# `scripts/apply_migrations.py` all get their promise back.

REQUIRED_COLUMNS: dict[str, dict[str, str]] = {
    "tasks": {
        "revision": "0002_api_foundation.sql",
        "policy_level": "0005_decision_policy_level.sql",
        "engine": "0008_engine_and_delivery.sql",
        "issue_ref": "0008_engine_and_delivery.sql",
        "delivery_json": "0008_engine_and_delivery.sql",
        "delivery_result_json": "0008_engine_and_delivery.sql",
    },
    # Without these two, every request authenticates against a table that
    # cannot express revocation — so a token the operator revoked keeps working
    # and nothing says why.
    "oauth_access_tokens": {
        "revoked_at": "0003_mobile_auth.sql",
        "grant_id": "0003_mobile_auth.sql",
    },
    # Without `node_id`, a gateway upgraded past 0009 without running it would
    # create `nodes` (a brand-new table `create_all` does add) while
    # `executors` silently kept no `node_id` — so every node lookup would find
    # a fleet of one project-less machines and report it as normal.
    #
    # Without `machine_token_hash` (issue #76), `/agent/ws` reads a column that
    # does not exist on its very first handshake, and every existing executor
    # is refused with a driver error that looks nothing like "run the
    # migration".
    "executors": {
        "node_id": "0009_control_plane.sql",
        "machine_token_hash": "0013_node_enrollment.sql",
    },
    # Without this, `revoke_node` (issue #76) writes a value the ORM believes
    # in but the table has no column for, and the first revoke fails at commit
    # time instead of at startup.
    "nodes": {
        "admission_state": "0013_node_enrollment.sql",
    },
    # Without these, a gateway upgraded past 0011 without running it starts
    # fine (both columns are nullable, so `create_all` on a FRESH database
    # already includes them) but every existing install fails the moment
    # `publish_epic_to_repo`/`apply_epic_materialization` tries to write a
    # column that is not there yet -- the same "fresh install fine, upgrade
    # broken" shape this whole module exists to catch early.
    "epics": {
        "materialized_path": "0012_issue_materialization.sql",
        "materialized_revision": "0012_issue_materialization.sql",
    },
    "issues": {
        "materialized_path": "0012_issue_materialization.sql",
        "materialized_revision": "0012_issue_materialization.sql",
    },
    # Without this, `record_discovery_report` and the adoption routes both
    # select a column the ORM model declares (`DiscoveredResourceModel.
    # resource_path`) that a pre-0013 database does not have -- a 500 on the
    # first discovery report or adoption call, not a startup failure that
    # names the fix.
    "discovered_resources": {
        "resource_path": "0014_discovery_resource_key_hash.sql",
    },
}


# Columns a migration *removes*, with the migration that removes each one.
#
# The mirror image of the case above, and it fails just as late without a check.
# `create_all` never drops a column either, so a database upgraded past
# `0004_drop_user_email.sql` without running it keeps three `not null` columns
# the code has stopped supplying — and the symptom is an integrity error on the
# first sign-in, which reads like a code bug. Presence, again: this says the
# migration has not run, not that the shape is subtly wrong.
FORBIDDEN_COLUMNS: dict[str, dict[str, str]] = {
    "oauth_authorization_codes": {"user_email": "0004_drop_user_email.sql"},
    "oauth_access_tokens": {"user_email": "0004_drop_user_email.sql"},
    "oauth_refresh_tokens": {"user_email": "0004_drop_user_email.sql"},
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

    for table, columns in FORBIDDEN_COLUMNS.items():
        if table not in existing_tables:
            continue
        present = {column["name"] for column in inspector.get_columns(table)}
        for column, migration in columns.items():
            if column in present:
                missing.append(f"column {table}.{column} still present (dropped by {migration})")

    if missing:
        raise SchemaOutOfDate(
            "The database does not match what this build requires: "
            + "; ".join(missing)
            + f". Run `{APPLY_COMMAND}` against this database, then start again. "
            + ADOPT_HINT
            + " Startup does not migrate on its own: applying schema changes to a "
            "live database is an operator decision, not a side effect of a deploy."
        )
