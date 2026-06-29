import logging

import redis
from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.schemas.events import HealthResponse
from core.config.settings import get_settings
from core.db.session import get_async_db

router = APIRouter(prefix="/v1", tags=["health"])
log = logging.getLogger(__name__)


@router.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    return HealthResponse(status="ok")


@router.get("/ready", response_model=HealthResponse)
async def ready(db: AsyncSession = Depends(get_async_db)) -> HealthResponse:
    settings = get_settings()
    details: dict[str, str] = {"db": "ok", "redis": "ok"}
    # Return only a coarse status to the client — exception text from psycopg/redis can
    # embed the DSN (hosts, ports, user). Log the detail server-side instead.
    try:
        await db.execute(text("SELECT 1"))
    except Exception:
        log.exception("readiness: db check failed")
        details["db"] = "error"
    try:
        r = redis.from_url(settings.redis_url)
        r.ping()
    except Exception:
        log.exception("readiness: redis check failed")
        details["redis"] = "error"
    status = "ok" if details["db"] == "ok" and details["redis"] == "ok" else "degraded"
    return HealthResponse(status=status, details=details)
