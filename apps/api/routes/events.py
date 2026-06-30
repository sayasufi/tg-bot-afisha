import gzip
import hashlib
import logging
import time
from datetime import datetime
from decimal import Decimal
from uuid import UUID

import orjson
from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.schemas.events import (
    CategoryResponse,
)
from apps.api.services.events_service import (
    EventQueryService,
    _redis_client,
    map_cache_get,
    map_cache_key,
    map_cache_set,
)
from core.domain.cities import active_cities, city_by_name
from core.db.session import get_async_db

router = APIRouter(prefix="/v1", tags=["events"])
logger = logging.getLogger(__name__)

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
    fields: str = Query(default="full", pattern="^(full|index)$", description="'index' = slim per-event payload"),
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
    key = map_cache_key(zoom, bbox_tuple, date_from, date_to, categories, price_min, price_max, q, limit, offset, city_slug, fields)
    cached = await map_cache_get(key)
    if cached is not None:
        gz_body, etag = cached
    else:
        service = EventQueryService(db)
        result = await service.map_events(
            bbox_tuple, date_from, date_to, categories, price_min, price_max, q, limit, offset, zoom, city_cfg, fields
        )
        # Return the pooled connection BEFORE the CPU-bound encode/compress (~MB) — `result` is already plain
        # dicts, so nothing below needs the DB. Frees a pool slot during the slowest part of a cache-miss.
        await db.close()
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


@router.get("/events/list")
async def list_events(
    bbox: str | None = Query(default=None, description="min_lon,min_lat,max_lon,max_lat"),
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    categories: list[str] | None = Query(default=None),
    price_max: float | None = None,
    q: str | None = Query(default=None, max_length=200),
    sort: str = Query(default="date", pattern="^(date|distance|popularity|price)$"),
    lat: float | None = Query(default=None, ge=-90, le=90),
    lon: float | None = Query(default=None, ge=-180, le=180),
    radius_km: float | None = Query(default=None, ge=0, le=200),
    limit: int = Query(default=20, ge=1, le=50),
    offset: int = Query(default=0, ge=0),
    city: str | None = Query(default=None, max_length=120, description="city slug or name to scope to"),
    db: AsyncSession = Depends(get_async_db),
):
    """Flat, paginated, sortable list of the events in the current map bbox — the list
    view that mirrors the pins (same filters)."""
    bbox_tuple = None
    if bbox:
        try:
            parts = [float(x) for x in bbox.split(",")]
        except ValueError:
            raise HTTPException(status_code=400, detail="bbox must be 4 comma-separated numbers")
        if len(parts) != 4:
            raise HTTPException(status_code=400, detail="bbox must have 4 comma-separated numbers")
        bbox_tuple = (parts[0], parts[1], parts[2], parts[3])
    service = EventQueryService(db)
    return await service.list_events(
        bbox_tuple, date_from, date_to, categories, price_max, q, sort, lat, lon, radius_km, limit, offset, city_by_name(city)
    )


# Per-city event counts power the far-zoom "созвездие" picker (a number on each city chip). It's a
# 16-region spatial COUNT over slow-moving data (changes only on ingest), so cache it in-process for
# a few minutes instead of recomputing per call. Per-worker staleness of a few minutes is harmless.
_CITY_COUNTS: dict[str, object] = {"at": 0.0, "data": {}}
_CITY_COUNTS_TTL = 600.0  # seconds


async def _city_event_counts(db: AsyncSession) -> dict[str, int]:
    """{slug: active-event count in that city's region}. Cached; degrades to stale/empty on error so
    the (load-critical) city list never breaks over a count."""
    now = time.monotonic()
    cached: dict = _CITY_COUNTS["data"]  # type: ignore[assignment]
    if cached and now - float(_CITY_COUNTS["at"]) < _CITY_COUNTS_TTL:
        return cached
    cities = active_cities()
    # Coords come from the trusted core.domain.cities registry (not user input), so interpolating the VALUES
    # list is not an injection vector — same rationale as core.domain.cities.region_predicate_sql.
    values = ", ".join(
        f"('{c.slug}', {c.center[0]}, {c.center[1]}, {c.region_radius_km * 1000.0})" for c in cities
    )
    sql = text(
        f"""
        WITH city(slug, lat, lon, r) AS (VALUES {values})
        SELECT c.slug, COUNT(DISTINCT e.event_id) AS n
        FROM city c
        JOIN events.venues v
          ON ST_DWithin(v.geom, ST_SetSRID(ST_MakePoint(c.lon, c.lat), 4326)::geography, c.r)
        JOIN events.event_occurrences o ON o.venue_id = v.venue_id
        JOIN events.events e ON e.event_id = o.event_id AND e.status = 'active'
        GROUP BY c.slug
        """
    )
    try:
        rows = (await db.execute(sql)).all()
        data = {row[0]: int(row[1]) for row in rows}
        _CITY_COUNTS["at"] = now
        _CITY_COUNTS["data"] = data
        return data
    except Exception:
        logger.warning("city_event_counts failed", exc_info=True)
        return cached or {}


@router.get("/cities")
async def get_cities(db: AsyncSession = Depends(get_async_db)):
    """Active cities the app serves — for the frontend's city picker / auto-detect and per-city map
    centring. From the core.domain.cities registry (the multi-city source of truth). `count` = active events
    in the city's region; the far-zoom constellation picker shows it on each city chip."""
    counts = await _city_event_counts(db)
    return {
        "cities": [
            {
                "slug": c.slug,
                "name": c.name,
                "lat": c.center[0],
                "lon": c.center[1],
                "radius_km": c.region_radius_km,
                "utc_offset": c.utc_offset_hours,
                "count": counts.get(c.slug, 0),
            }
            for c in active_cities()
        ]
    }


@router.get("/events/nearby")
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
    result = await service.nearby(lat, lon, radius_m, date_from, date_to, categories, q, limit)
    # Bypass response_model (mirrors the map route): the service builds plain dicts, so
    # orjson encodes them once instead of Pydantic re-validating up to 200 rows per call —
    # the serialization that pegged the API CPU at the measured ~25 rps knee.
    return Response(orjson.dumps(result), media_type="application/json")


class ByIdsRequest(BaseModel):
    ids: list[str]
    lat: float | None = None
    lon: float | None = None


@router.post("/events/by-ids")
async def events_by_ids(payload: ByIdsRequest, db: AsyncSession = Depends(get_async_db)):
    """Hydrate specific events by id into the rich list-item shape — used by the
    favourites/profile views so saved events render independent of the map's loaded set
    (the count and the list can't diverge). Caps at 500 ids; drops non-UUIDs."""
    ids = []
    for s in payload.ids[:500]:
        try:
            ids.append(UUID(str(s)))
        except (ValueError, TypeError):
            continue
    service = EventQueryService(db)
    return await service.list_by_ids(ids, payload.lat, payload.lon)


_DETAIL_TTL = 90  # event detail changes only on ingest — short Redis cache absorbs the thundering herd
# when the FIRST mass digest/broadcast sends everyone to the same few hot events at once.


@router.get("/events/{event_id}")
async def get_event_detail(event_id: UUID, db: AsyncSession = Depends(get_async_db)):
    rc = _redis_client()
    key = f"evdetail:{event_id}"
    if rc is not None:
        try:
            cached = await rc.get(key)
            if cached:
                return Response(cached, media_type="application/json")
        except Exception:
            pass
    service = EventQueryService(db)
    result = await service.event_detail(event_id)
    if not result:
        raise HTTPException(status_code=404, detail="event not found")
    # orjson нативно умеет datetime/UUID, но НЕ Decimal (цены) — раньше сериализовала Pydantic-схема.
    # Decimal→float (остаётся числом, контракт цены не ломается), прочее непредвиденное → строка (безопасно).
    body = orjson.dumps(result, default=lambda o: float(o) if isinstance(o, Decimal) else str(o))
    if rc is not None:
        try:
            await rc.set(key, body, ex=_DETAIL_TTL)
        except Exception:
            pass
    return Response(body, media_type="application/json")


@router.get("/venues/{venue_id}")
async def get_venue(venue_id: int, since: datetime | None = None, db: AsyncSession = Depends(get_async_db)):
    """A venue + its upcoming events — the venue page (tap the place in an event sheet). `since` (the
    «Площадки» list's last-visit timestamp) drives «+N новых» = events listed here since you last looked."""
    service = EventQueryService(db)
    result = await service.venue_detail(venue_id, since)
    if not result:
        raise HTTPException(status_code=404, detail="venue not found")
    return Response(orjson.dumps(result), media_type="application/json")


@router.get("/categories", response_model=CategoryResponse)
async def get_categories(db: AsyncSession = Depends(get_async_db)):
    service = EventQueryService(db)
    return await service.categories()


@router.get("/search")
async def search(
    q: str = Query(min_length=1, max_length=200),
    city: str | None = Query(default=None, max_length=120, description="city slug or name to scope to"),
    limit: int = Query(default=8, ge=1, le=20),
    db: AsyncSession = Depends(get_async_db),
):
    # GET so the typeahead can use AbortController + browser/edge caching. Returns ranked
    # event rows (matched by code / title / venue) ready to render and open with no extra
    # fetch. No response_model — the rows are built as plain dicts (datetime/UUID handled
    # by FastAPI's encoder).
    service = EventQueryService(db)
    return await service.search(q, city_by_name(city), limit)
