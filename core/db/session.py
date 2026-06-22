from collections.abc import AsyncGenerator, Generator

from sqlalchemy import create_engine
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import NullPool

from core.config.settings import get_settings

settings = get_settings()

# Per-process pools, imported by every uvicorn worker (Prefect uses the NullPool engine below). The
# CEILING MUST stay under Postgres max_connections (100) across all 6 workers + the bot + prefect-serve +
# healthchecks. The SYNC engine is barely used now (only the sync /location endpoint + scripts), so keep it
# tiny. The ASYNC engine is the hot path: 6 × (5+5) = 60, plus sync 6 × (2+3) = 30 → ≤90 worst case, with
# headroom. NOTE: the proper scale fix is to route through the deployed Odyssey transaction pooler
# (odyssey:6432) and/or raise Postgres max_connections — see the perf plan; this just removes the squeeze.
_SYNC_POOL = dict(pool_pre_ping=True, pool_size=2, max_overflow=3, pool_recycle=1800)

# The async API engine adds an explicit pool_timeout: when every connection is checked out, a request waits
# at most this long for one, then fails fast — instead of SQLAlchemy's 30s default that turned pool pressure
# under load into 30s hangs and a wall of 500s. Read handlers release the connection before any CPU-heavy
# work, so the pool should rarely be contended; this just bounds the worst case.
_ASYNC_POOL = dict(pool_pre_ping=True, pool_size=5, max_overflow=5, pool_recycle=1800, pool_timeout=10)

# Pin every session to UTC explicitly. Code relies on a UTC session (e.g. the map and
# event-detail date floor compare a Python UTC-midnight against SQL date_trunc('day',
# now()), which are equal ONLY under a UTC session; dedup day-bucketing likewise). The
# Postgres default is already UTC, but a future container `TZ=`/`PGTZ=` env would
# silently change date_trunc semantics — this makes the invariant explicit and safe.
#
# prepare_threshold=None disables psycopg3 auto-prepared-statements. REQUIRED when the
# DB URL points at the transaction-pooling Odyssey (odyssey:6432): a prepared statement
# created on one pooled server connection won't exist on the next one a transaction
# lands on. Harmless on a direct Postgres connection, so it's always on.
_CONNECT = {"options": "-c timezone=UTC", "prepare_threshold": None}

# Sync engine — kept for scripts / any sync caller during/after the async migration.
engine = create_engine(settings.sync_database_url, connect_args=_CONNECT, **_SYNC_POOL)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)


def _async_url(url: str) -> str:
    """Async DSN using psycopg3's async driver (already a dependency — no asyncpg)."""
    if "+asyncpg" in url or "+psycopg" in url:
        return url.replace("+asyncpg", "+psycopg")
    if url.startswith("postgresql://"):
        return url.replace("postgresql://", "postgresql+psycopg://", 1)
    return url


# Async engine — FastAPI (one long-lived event loop per uvicorn worker → pooled).
async_engine = create_async_engine(_async_url(settings.database_url), connect_args=_CONNECT, **_ASYNC_POOL)
AsyncSessionLocal = async_sessionmaker(bind=async_engine, autoflush=False, expire_on_commit=False)

# Worker async engine — Celery tasks call asyncio.run() per task, creating a fresh
# event loop each time. A pooled connection bound to a previous loop can't be reused
# ("attached to a different loop"), so workers use NullPool: a connection per session,
# discarded on close. Concurrency is bounded by prefork process count, so total
# connections stay small. Uses the same DSN as the API async engine (database_url);
# DATABASE_URL and SYNC_DATABASE_URL must point to the same database.
worker_async_engine = create_async_engine(_async_url(settings.database_url), connect_args=_CONNECT, poolclass=NullPool)
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
