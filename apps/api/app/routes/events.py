import gzip
import hashlib
from datetime import datetime
from uuid import UUID

import orjson
from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.app.schemas.events import (
    CategoryResponse,
    EventDetailResponse,
    NearbyResponse,
    SearchRequest,
    SearchResponse,
)
from apps.api.app.services.events_service import (
    EventQueryService,
    map_cache_get,
    map_cache_key,
    map_cache_set,
)
from core.cities import active_cities, city_by_name
from core.db.session import get_async_db

router = APIRouter(prefix="/v1", tags=["events"])

# Map data changes only on ingest; let the browser cache it and revalidate cheaply
# (ETag → 304) after the window. Same value the cache_control middleware would set.
_MAP_CACHE_CONTROL = "public, max-age=30, stale-while-revalidate=120"


@router.get("/events/map")
async def get_map_events(
    request: Request,
    bbox: str | None = Query(default=None, description="min_lon,min_lat,max_lon,max_lat"),
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    categories: list[str] | None = Query(default=None),
    price_min: float | None = None,
    price_max: float | None = None,
    q: str | None = Query(default=None, max_length=200),
    zoom: int | None = Query(default=None, ge=0, le=22),
    limit: int | None = Query(default=None, ge=1, le=20000),
    offset: int = Query(default=0, ge=0),
    city: str | None = Query(default=None, max_length=120, description="city slug or name to scope to"),
    db: AsyncSession = Depends(get_async_db),
):
    # Resolve the city to scope the map to one city (multi-city). Unknown/absent → None
    # → all active cities (back-compat). city_by_name accepts slug or display name.
    city_cfg = city_by_name(city)
    bbox_tuple = None
    if bbox:
        # Parse defensively — a malformed bbox must be a clean 400, not a 500
        # that leaks a stack trace and never reaches PostGIS.
        try:
            parts = [float(x) for x in bbox.split(",")]
        except ValueError:
            raise HTTPException(status_code=400, detail="bbox must be 4 comma-separated numbers")
        if len(parts) != 4:
            raise HTTPException(status_code=400, detail="bbox must have 4 comma-separated numbers")
        bbox_tuple = (parts[0], parts[1], parts[2], parts[3])

    # Serve the whole response from Redis when warm (skips DB + row-build + encode +
    # compress), and emit an ETag so a post-window revalidation returns a bare 304
    # instead of re-shipping the body. We bypass response_model on purpose: the payload
    # is built as plain dicts and encoded once with orjson — Pydantic re-validating ~7k
    # rows was a large, pointless slice of the latency. The cached body is GZIPPED ONCE
    # per window: served as-is to gzip clients (≈all), so neither uvicorn nor the nginx
    # edge re-compresses the multi-MB payload per request, and the nginx proxy_cache in
    # front stores it already-compressed.
    accepts_gzip = "gzip" in request.headers.get("accept-encoding", "").lower()
    city_slug = city_cfg.slug if city_cfg else None
    key = map_cache_key(zoom, bbox_tuple, date_from, date_to, categories, price_min, price_max, q, limit, offset, city_slug)
    cached = await map_cache_get(key)
    if cached is not None:
        gz_body, etag = cached
    else:
        service = EventQueryService(db)
        result = await service.map_events(
            bbox_tuple, date_from, date_to, categories, price_min, price_max, q, limit, offset, zoom, city_cfg
        )
        raw = orjson.dumps(result)  # orjson encodes datetime/UUID natively; price is float
        etag = 'W/"' + hashlib.sha256(raw).hexdigest()[:32] + '"'
        gz_body = gzip.compress(raw, 5)
        await map_cache_set(key, gz_body, etag)

    headers = {"ETag": etag, "Cache-Control": _MAP_CACHE_CONTROL, "Vary": "Accept-Encoding"}
    if request.headers.get("if-none-match") == etag:
        return Response(status_code=304, headers=headers)
    if accepts_gzip:
        headers["Content-Encoding"] = "gzip"
        return Response(content=gz_body, media_type="application/json", headers=headers)
    return Response(content=gzip.decompress(gz_body), media_type="application/json", headers=headers)


@router.get("/cities")
async def get_cities():
    """Active cities the app serves — for the frontend's city picker / auto-detect and
    per-city map centring. From the core.cities registry (the multi-city source of truth)."""
    return {
        "cities": [
            {"slug": c.slug, "name": c.name, "lat": c.center[0], "lon": c.center[1], "radius_km": c.region_radius_km}
            for c in active_cities()
        ]
    }


@router.get("/events/nearby", response_model=NearbyResponse)
async def get_nearby_events(
    lat: float = Query(ge=-90, le=90),
    lon: float = Query(ge=-180, le=180),
    radius_m: int = Query(default=3000, ge=100, le=50000),
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    categories: list[str] | None = Query(default=None),
    q: str | None = Query(default=None, max_length=200),
    limit: int = Query(default=50, ge=1, le=200),
    db: AsyncSession = Depends(get_async_db),
):
    service = EventQueryService(db)
    return await service.nearby(lat, lon, radius_m, date_from, date_to, categories, q, limit)


@router.get("/events/{event_id}", response_model=EventDetailResponse)
async def get_event_detail(event_id: UUID, db: AsyncSession = Depends(get_async_db)):
    service = EventQueryService(db)
    result = await service.event_detail(event_id)
    if not result:
        raise HTTPException(status_code=404, detail="event not found")
    return result


@router.get("/categories", response_model=CategoryResponse)
async def get_categories(db: AsyncSession = Depends(get_async_db)):
    service = EventQueryService(db)
    return await service.categories()


@router.post("/search", response_model=SearchResponse)
async def search(payload: SearchRequest, db: AsyncSession = Depends(get_async_db)):
    service = EventQueryService(db)
    return await service.search(payload.q, payload.city, payload.limit)
