from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from app.core.config import get_settings

settings = get_settings()

# Pool sizing: Railway Postgres hobby = 25 max connections.
# Leave headroom for admin connections and migrations.
engine = create_async_engine(
    settings.database_url,
    pool_size=10,
    max_overflow=5,
    pool_pre_ping=True,       # Drop stale connections before use
    pool_recycle=1800,        # Recycle connections every 30 min
    echo=settings.app_env != "production",
)

AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
    autocommit=False,
)


class Base(DeclarativeBase):
    pass


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency — yields a DB session, always closes it."""
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


async def check_db() -> bool:
    """Health check — returns True if DB is reachable."""
    try:
        async with AsyncSessionLocal() as session:
            await session.execute(__import__("sqlalchemy").text("SELECT 1"))
        return True
    except Exception:
        return False
