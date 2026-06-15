from collections.abc import AsyncGenerator, Generator

from sqlalchemy import create_engine
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import Session, sessionmaker

from core.config.settings import get_settings

settings = get_settings()

# Modest per-process pool: this module is imported by every uvicorn worker AND every
# Celery prefork process, so pool_size must stay small to keep total connections under
# Postgres max_connections (100).
_POOL = dict(pool_pre_ping=True, pool_size=5, max_overflow=10, pool_recycle=1800)

# Sync engine — Celery worker tasks (run async bodies via asyncio.run) and scripts.
engine = create_engine(settings.sync_database_url, **_POOL)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)


def _async_url(url: str) -> str:
    """Async DSN using psycopg3's async driver (already a dependency — no asyncpg)."""
    if "+asyncpg" in url or "+psycopg" in url:
        return url.replace("+asyncpg", "+psycopg")
    if url.startswith("postgresql://"):
        return url.replace("postgresql://", "postgresql+psycopg://", 1)
    return url


# Async engine — FastAPI request handlers.
async_engine = create_async_engine(_async_url(settings.database_url), **_POOL)
AsyncSessionLocal = async_sessionmaker(bind=async_engine, autoflush=False, expire_on_commit=False)


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


async def get_async_db() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as db:
        yield db
