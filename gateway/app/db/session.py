from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from gateway.app.core.config import settings


engine = create_async_engine(settings.database_url, future=True)
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

