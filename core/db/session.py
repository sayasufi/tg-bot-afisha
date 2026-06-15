from collections.abc import AsyncGenerator, Generator

from sqlalchemy import create_engine
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import NullPool

from core.config.settings import get_settings

settings = get_settings()

# Modest per-process pool: this module is imported by every uvicorn worker AND every
# Celery prefork process, so pool_size must stay small to keep total connections under
# Postgres max_connections (100).
_POOL = dict(pool_pre_ping=True, pool_size=5, max_overflow=10, pool_recycle=1800)

# Sync engine — kept for scripts / any sync caller during/after the async migration.
engine = create_engine(settings.sync_database_url, **_POOL)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)


def _async_url(url: str) -> str:
    """Async DSN using psycopg3's async driver (already a dependency — no asyncpg)."""
    if "+asyncpg" in url or "+psycopg" in url:
        return url.replace("+asyncpg", "+psycopg")
    if url.startswith("postgresql://"):
        return url.replace("postgresql://", "postgresql+psycopg://", 1)
    return url


# Async engine — FastAPI (one long-lived event loop per uvicorn worker → pooled).
async_engine = create_async_engine(_async_url(settings.database_url), **_POOL)
AsyncSessionLocal = async_sessionmaker(bind=async_engine, autoflush=False, expire_on_commit=False)

# Worker async engine — Celery tasks call asyncio.run() per task, creating a fresh
# event loop each time. A pooled connection bound to a previous loop can't be reused
# ("attached to a different loop"), so workers use NullPool: a connection per session,
# discarded on close. Concurrency is bounded by prefork process count, so total
# connections stay small. Uses the same DSN as the API async engine (database_url);
# DATABASE_URL and SYNC_DATABASE_URL must point to the same database.
worker_async_engine = create_async_engine(_async_url(settings.database_url), poolclass=NullPool)
WorkerAsyncSessionLocal = async_sessionmaker(bind=worker_async_engine, autoflush=False, expire_on_commit=False)


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


async def get_async_db() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as db:
        yield db
