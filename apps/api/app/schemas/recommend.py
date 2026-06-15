from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel


class RailItem(BaseModel):
    event_id: UUID
    title: str
    category: str
    date_start: datetime
    date_end: datetime | None = None
    price_min: Decimal | None = None
    venue: str | None = None
    venue_hours: dict | None = None
    lat: float | None = None
    lon: float | None = None
    primary_image_url: str | None = None
    distance_m: float | None = None


class Rail(BaseModel):
    key: str
    title: str
    subtitle: str | None = None
    items: list[RailItem]


class RecommendationsResponse(BaseModel):
    rails: list[Rail]
    total: int
