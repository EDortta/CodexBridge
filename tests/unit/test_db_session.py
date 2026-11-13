import sqlite3

from gateway.app.db.session import _configure_sqlite_connection


def test_sqlite_connection_waits_for_writers_and_uses_wal(tmp_path) -> None:
    connection = sqlite3.connect(tmp_path / "gateway.db")
    try:
        _configure_sqlite_connection(connection, None)
        assert connection.execute("PRAGMA busy_timeout").fetchone()[0] == 30000
        assert connection.execute("PRAGMA journal_mode").fetchone()[0].lower() == "wal"
        assert connection.execute("PRAGMA synchronous").fetchone()[0] == 1
    finally:
        connection.close()


def test_sqlite_memory_connection_keeps_memory_journal(tmp_path) -> None:
    connection = sqlite3.connect(":memory:")
    try:
        _configure_sqlite_connection(connection, None)
        assert connection.execute("PRAGMA busy_timeout").fetchone()[0] == 30000
        assert connection.execute("PRAGMA journal_mode").fetchone()[0].lower() == "memory"
    finally:
        connection.close()
