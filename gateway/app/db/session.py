from __future__ import annotations

from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from gateway.app.core.config import settings


def _configure_sqlite_connection(dbapi_connection, _connection_record) -> None:
    """Make concurrent SQLite readers/writers wait instead of failing immediately."""
    if hasattr(dbapi_connection, "run_async"):
        async def configure_async(connection) -> None:
            await connection.execute("PRAGMA busy_timeout=30000")
            cursor = await connection.execute("PRAGMA database_list")
            database_path = (await cursor.fetchone())[2]
            await cursor.close()
            if database_path not in ("", ":memory:"):
                await connection.execute("PRAGMA journal_mode=WAL")
                await connection.execute("PRAGMA synchronous=NORMAL")

        dbapi_connection.run_async(configure_async)
        return

    cursor = dbapi_connection.cursor()
    try:
        cursor.execute("PRAGMA busy_timeout=30000")
        # WAL permits the heartbeat/read traffic to continue while another
        # connection commits a receipt. SQLite's in-memory database cannot use
        # WAL, so leave that mode untouched for the test-only database.
        database_path = dbapi_connection.execute("PRAGMA database_list").fetchone()[2]
        if database_path not in ("", ":memory:"):
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA synchronous=NORMAL")
    finally:
        cursor.close()


engine = create_async_engine(
    settings.database_url,
    future=True,
    connect_args={"timeout": 30} if settings.database_url.startswith("sqlite") else {},
)
if settings.database_url.startswith("sqlite"):
    event.listen(engine.sync_engine, "connect", _configure_sqlite_connection)
SessionLocal = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)


async def get_session() -> AsyncSession:
    async with SessionLocal() as session:
        yield session


def session_factory() -> async_sessionmaker[AsyncSession]:
    """The sessionmaker, for code that outlives a request's dependencies.

    `get_session` is a FastAPI dependency, and FastAPI closes a request's
    dependencies when the handler *returns*. For a `StreamingResponse` the body
    is produced after that, so a session injected as a dependency is already
    closed by the time the generator runs — `gateway/app/api/routes/events.py`
    opens one per poll through this instead.

    A function rather than the module attribute itself, and reading the global
    at call time on purpose: a test that swaps `SessionLocal` for an in-memory
    engine must be seen by callers that imported this module at import time.
    """
    return SessionLocal

