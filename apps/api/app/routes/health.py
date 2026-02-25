import redis
from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session

from apps.api.app.schemas.events import HealthResponse
from core.config.settings import get_settings
from core.db.session import get_db

router = APIRouter(prefix="/v1", tags=["health"])


@router.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    return HealthResponse(status="ok")


@router.get("/ready", response_model=HealthResponse)
def ready(db: Session = Depends(get_db)) -> HealthResponse:
    settings = get_settings()
    details: dict[str, str] = {"db": "ok", "redis": "ok"}
    try:
        db.execute(text("SELECT 1"))
    except Exception as exc:
        details["db"] = f"error: {exc}"
    try:
        r = redis.from_url(settings.redis_url)
        r.ping()
    except Exception as exc:
        details["redis"] = f"error: {exc}"
    status = "ok" if details["db"] == "ok" and details["redis"] == "ok" else "degraded"
    return HealthResponse(status=status, details=details)
