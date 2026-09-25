"""Async SQLAlchemy 2.0 engine + session management (Phase 0).

The engine is created lazily-safe: no connection is attempted at import time, so
the V1 in-memory pipeline (and the pytest suite) keeps working without Postgres.
"""
from __future__ import annotations

from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import settings


# Async engine with connection pooling. pool_pre_ping validates stale connections
# (long-lived containers behind Render/NAT proxies recycle them silently).
# Pool sizing only applies to server-backed dialects — SQLite (aiosqlite) rejects
# pool_size/max_overflow, which keeps the pytest suite and local fallback usable.
def _engine_kwargs() -> dict:
    kwargs: dict = {"echo": settings.db_echo, "pool_pre_ping": True}
    if settings.db_null_pool:
        # See Settings.db_null_pool: no pooling across event loops. Must be
        # set before pool_size/max_overflow (NullPool rejects them).
        from sqlalchemy.pool import NullPool

        kwargs["poolclass"] = NullPool
        return kwargs
    if settings.database_url.startswith("postgresql"):
        kwargs.update(
            pool_size=settings.db_pool_size,
            max_overflow=settings.db_max_overflow,
            pool_recycle=3600,  # recycle connections after 1 hour
        )
    return kwargs


def _normalize_db_url(url: str) -> str:
    """Providers (Supabase, Neon, Render) hand out postgresql:// URIs.
    This stack is async — rewrite to the asyncpg driver transparently."""
    if url.startswith("postgresql://"):
        return url.replace("postgresql://", "postgresql+asyncpg://", 1)
    return url


engine = create_async_engine(_normalize_db_url(settings.database_url), **_engine_kwargs())

# Session factory — expire_on_commit=False so returned ORM objects stay usable
# after the commit inside get_session (needed by response serialization).
async_session_factory = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency that yields a database session.

    Commits on success, rolls back on exception. v2 endpoints depend on this.
    """
    async with async_session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def check_database() -> bool:
    """Cheap connectivity probe used by lifespan + /health/ready."""
    from sqlalchemy import text

    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        return True
    except Exception:
        return False
