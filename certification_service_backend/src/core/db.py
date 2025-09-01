from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncGenerator, Optional

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from .config import get_settings

_engine: Optional[AsyncEngine] = None
_session_factory: Optional[async_sessionmaker[AsyncSession]] = None


def _create_engine() -> AsyncEngine:
    """Create a new SQLAlchemy async engine from configuration."""
    settings = get_settings()
    # echo=settings.debug enables SQL logging in development
    return create_async_engine(settings.database_url, echo=settings.debug, future=True, pool_pre_ping=True)


def _create_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    """Create an async session factory bound to the engine."""
    return async_sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


# PUBLIC_INTERFACE
def get_engine() -> AsyncEngine:
    """Return a singleton async engine, creating it if necessary."""
    global _engine
    if _engine is None:
        _engine = _create_engine()
    return _engine


# PUBLIC_INTERFACE
def get_session_factory() -> async_sessionmaker[AsyncSession]:
    """Return a singleton async session factory, creating it if necessary."""
    global _session_factory
    if _session_factory is None:
        _session_factory = _create_session_factory(get_engine())
    return _session_factory


@asynccontextmanager
# PUBLIC_INTERFACE
async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    """Yield an AsyncSession for DB operations, ensuring proper cleanup."""
    session_maker = get_session_factory()
    async with session_maker() as session:
        try:
            yield session
        finally:
            # Session context manager handles close, explicit finally for clarity
            ...


# PUBLIC_INTERFACE
async def db_healthcheck() -> bool:
    """Perform a simple health check against the database connection."""
    engine = get_engine()
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
            return True
    except Exception:
        return False


# Lazily imported to prevent circular import at module load
from sqlalchemy import text  # noqa: E402
