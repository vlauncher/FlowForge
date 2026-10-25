"""Database engine, session factory, and FastAPI session dependency."""

from __future__ import annotations

from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool

from app.core.config import Settings, get_settings

_engines: dict[str, AsyncEngine] = {}


def get_engine(settings: Settings | None = None) -> AsyncEngine:
    """Create and return an AsyncEngine instance.

    In test environments, uses NullPool so connections are bound to the active
    pytest-asyncio event loop and disposed without cross-loop pollution.
    """
    cfg = settings or get_settings()
    url = cfg.database_url
    if cfg.app_env == "test":
        return create_async_engine(url, poolclass=NullPool)

    if url not in _engines:
        _engines[url] = create_async_engine(
            url,
            pool_size=cfg.db_pool_size,
            max_overflow=cfg.db_max_overflow,
            pool_pre_ping=True,
        )
    return _engines[url]


def get_session_factory(
    engine: AsyncEngine | None = None,
) -> async_sessionmaker[AsyncSession]:
    """Return an async session factory bound to the given or cached engine."""
    eng = engine or get_engine()
    return async_sessionmaker(
        bind=eng,
        class_=AsyncSession,
        expire_on_commit=False,
        autocommit=False,
        autoflush=False,
    )


async def get_session() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency yielding an AsyncSession per request.

    Rolls back transaction on unhandled exception.
    Closing is managed automatically by the context manager.
    """
    factory = get_session_factory()
    async with factory() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
