from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.app.schemas.recommend import RecommendationsResponse
from apps.api.app.services.recommend import RecommendationService
from apps.api.app.services.telegram_auth import validate_init_data
from core.db.session import get_async_db

router = APIRouter(prefix="/v1", tags=["recommend"])

# Cap the behavioural profile so a hostile client can't ship an unbounded list.
_MAX_PROFILE = 30


@router.get("/recommendations", response_model=RecommendationsResponse)
async def get_recommendations(
    lat: float | None = Query(default=None, ge=-90, le=90),
    lon: float | None = Query(default=None, ge=-180, le=180),
    interests: list[str] | None = Query(default=None),
    recent: list[str] | None = Query(default=None, description="categories of recently opened events (behavioural profile)"),
    per_rail: int = Query(default=12, ge=4, le=30),
    db: AsyncSession = Depends(get_async_db),
):
    service = RecommendationService(db)
    return await service.feed(
        lat, lon,
        interests[:_MAX_PROFILE] if interests else interests,
        recent[:_MAX_PROFILE] if recent else recent,
        per_rail,
    )


class SeenRequest(BaseModel):
    init_data: str | None = None


@router.post("/recommendations/seen/{event_id}", status_code=204)
async def log_event_seen(
    event_id: UUID,
    payload: SeenRequest | None = None,
    db: AsyncSession = Depends(get_async_db),
):
    # Engagement signal that feeds the "Популярное" rail and the popularity term
    # in scoring — so it must be authenticated, else anyone could inflate any
    # event's open-count. Require a valid Telegram initData and count each user
    # at most once per event per day (dedupe lives in log_view).
    if not payload or not payload.init_data:
        return None  # unauthenticated → silently ignored (fire-and-forget)
    try:
        user = validate_init_data(payload.init_data)
    except HTTPException:
        return None
    user_id = user.get("id")
    if user_id is None:
        return None
    await RecommendationService(db).log_view(event_id, user_id)
    return None
