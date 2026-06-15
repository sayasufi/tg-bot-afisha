from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.app.schemas.recommend import RecommendationsResponse
from apps.api.app.services.recommend import RecommendationService
from core.db.session import get_async_db

router = APIRouter(prefix="/v1", tags=["recommend"])


@router.get("/recommendations", response_model=RecommendationsResponse)
async def get_recommendations(
    lat: float | None = Query(default=None, ge=-90, le=90),
    lon: float | None = Query(default=None, ge=-180, le=180),
    interests: list[str] | None = Query(default=None),
    per_rail: int = Query(default=12, ge=4, le=30),
    db: AsyncSession = Depends(get_async_db),
):
    service = RecommendationService(db)
    return await service.feed(lat, lon, interests, per_rail)


@router.post("/recommendations/seen/{event_id}", status_code=204)
async def log_event_seen(event_id: UUID, db: AsyncSession = Depends(get_async_db)):
    # Fire-and-forget engagement signal: increments the event's open-count, which
    # feeds the "Популярное" rail and the popularity term in the score.
    await RecommendationService(db).log_view(str(event_id))
    return None
