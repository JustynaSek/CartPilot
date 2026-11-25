"""Async SQLAlchemy engine and session factory."""

from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from src.core.config import get_settings


def create_engine(database_url: str | None = None, *, echo: bool | None = None) -> AsyncEngine:
    settings = get_settings()
    return create_async_engine(
        database_url or settings.database_url,
        echo=settings.db_echo if echo is None else echo,
        pool_pre_ping=True,  # transparently replaces connections dropped by the server
    )


engine: AsyncEngine = create_engine()

# expire_on_commit=False: after commit, ORM objects keep their loaded attributes.
# Otherwise touching an attribute would trigger implicit (sync) lazy IO, which
# in async code raises `MissingGreenlet`.
SessionFactory: async_sessionmaker[AsyncSession] = async_sessionmaker(
    engine,
    expire_on_commit=False,
    autoflush=False,
)


async def get_session() -> AsyncIterator[AsyncSession]:
    """Yield a session that commits on success and rolls back on error.

    Usable as a FastAPI dependency or via `contextlib.asynccontextmanager`.
    """
    async with SessionFactory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def dispose_engine() -> None:
    """Close all pooled connections (call on application shutdown)."""
    await engine.dispose()
