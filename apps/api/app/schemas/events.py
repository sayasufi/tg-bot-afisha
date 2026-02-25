from collections.abc import Sequence
from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


class EventMapItem(BaseModel):
    event_id: UUID
    title: str
    category: str
    date_start: datetime
    price_min: Decimal | None
    venue: str | None
    lat: float | None
    lon: float | None


class EventCluster(BaseModel):
    id: str
    lat: float
    lon: float
    count: int


class EventMapResponse(BaseModel):
    clusters: list[EventCluster]
    items: list[EventMapItem]
    total: int


class EventDetailOccurrence(BaseModel):
    occurrence_id: int
    date_start: datetime
    date_end: datetime | None
    price_min: Decimal | None
    price_max: Decimal | None
    currency: str
    source_best_url: str
    venue: str | None
    address: str | None
    lat: float | None
    lon: float | None


class EventDetailResponse(BaseModel):
    event_id: UUID
    canonical_title: str
    canonical_description: str
    category: str
    subcategory: str
    age_limit: str
    primary_image_url: str
    occurrences: list[EventDetailOccurrence]


class NearbyItem(BaseModel):
    event_id: UUID
    title: str
    distance_m: float
    date_start: datetime


class NearbyResponse(BaseModel):
    items: list[NearbyItem]


class SearchRequest(BaseModel):
    q: str = Field(min_length=1)
    city: str | None = None
    limit: int = Field(default=20, ge=1, le=100)


class SearchItem(BaseModel):
    event_id: UUID
    title: str
    score: float


class SearchResponse(BaseModel):
    items: list[SearchItem]


class CategoryResponse(BaseModel):
    categories: Sequence[str]


class HealthResponse(BaseModel):
    status: str
    details: dict[str, Any] | None = None
