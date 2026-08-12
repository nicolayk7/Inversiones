"""Async SQLAlchemy engine/session. No business tables yet — those land
per-engine starting Phase 1. Phase 0 only needs to prove connectivity."""

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from packages.shared.config import settings

engine: AsyncEngine = create_async_engine(settings.database_url, pool_pre_ping=True)
SessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


async def check_connection() -> bool:
    async with engine.connect() as conn:
        await conn.execute(text("SELECT 1"))
    return True
