from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from apps.api.app.schemas.events import (
    CategoryResponse,
    EventDetailResponse,
    EventMapResponse,
    NearbyResponse,
    SearchRequest,
    SearchResponse,
)
from apps.api.app.services.events_service import EventQueryService
from core.db.session import get_db

router = APIRouter(prefix="/v1", tags=["events"])


@router.get("/events/map", response_model=EventMapResponse)
def get_map_events(
    bbox: str | None = Query(default=None, description="min_lon,min_lat,max_lon,max_lat"),
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    categories: list[str] | None = Query(default=None),
    price_min: float | None = None,
    price_max: float | None = None,
    q: str | None = None,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
):
    bbox_tuple = None
    if bbox:
        parts = [float(x) for x in bbox.split(",")]
        if len(parts) != 4:
            raise HTTPException(status_code=400, detail="bbox must have 4 comma-separated numbers")
        bbox_tuple = (parts[0], parts[1], parts[2], parts[3])

    service = EventQueryService(db)
    return service.map_events(bbox_tuple, date_from, date_to, categories, price_min, price_max, q, limit, offset)


@router.get("/events/nearby", response_model=NearbyResponse)
def get_nearby_events(
    lat: float,
    lon: float,
    radius_m: int = Query(default=3000, ge=100, le=50000),
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    categories: list[str] | None = Query(default=None),
    q: str | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db),
):
    service = EventQueryService(db)
    return service.nearby(lat, lon, radius_m, date_from, date_to, categories, q, limit)


@router.get("/events/{event_id}", response_model=EventDetailResponse)
def get_event_detail(event_id: UUID, db: Session = Depends(get_db)):
    service = EventQueryService(db)
    result = service.event_detail(event_id)
    if not result:
        raise HTTPException(status_code=404, detail="event not found")
    return result


@router.get("/categories", response_model=CategoryResponse)
def get_categories(db: Session = Depends(get_db)):
    service = EventQueryService(db)
    return service.categories()


@router.post("/search", response_model=SearchResponse)
def search(payload: SearchRequest, db: Session = Depends(get_db)):
    service = EventQueryService(db)
    return service.search(payload.q, payload.city, payload.limit)
