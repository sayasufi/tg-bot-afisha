import hashlib
import json
import math
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

import redis.asyncio as aioredis
from geoalchemy2 import Geography, Geometry
from sqlalchemy import Select, and_, bindparam, cast, func, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from core.config.settings import get_settings
from core.db.models import Event, EventOccurrence, Venue

# Cluster responses depend only on (zoom, bbox, filters) and the dataset, which
# changes only when the pipeline ingests — so cache them in Redis briefly. This
# makes the frontend's prefetch of every zoom level (and repeat loads across
# users) skip the DB entirely. Best-effort: any Redis hiccup falls back to a live
# query. Async client, created once on the API's single event loop.
_CLUSTER_CACHE_PREFIX = "map:clusters:v1:"
_CLUSTER_CACHE_TTL = 45
_redis: aioredis.Redis | None = None
_redis_off = False


def _redis_client() -> aioredis.Redis | None:
    global _redis, _redis_off
    if _redis_off:
        return None
    if _redis is None:
        try:
            _redis = aioredis.from_url(
                get_settings().redis_url, decode_responses=True, socket_timeout=0.5, socket_connect_timeout=0.5
            )
        except Exception:  # pragma: no cover - cache is best-effort
            _redis_off = True
            return None
    return _redis


def _cluster_cache_key(zoom, bbox, date_from, date_to, categories, price_min, price_max, q) -> str:
    raw = json.dumps(
        [
            zoom,
            list(bbox) if bbox else None,
            date_from.isoformat() if date_from else None,
            date_to.isoformat() if date_to else None,
            sorted(categories) if categories else None,
            price_min,
            price_max,
            q,
        ],
        default=str,
        sort_keys=True,
    )
    return _CLUSTER_CACHE_PREFIX + hashlib.sha256(raw.encode("utf-8")).hexdigest()


async def _cluster_cache_get(key: str):
    client = _redis_client()
    if client is None:
        return None
    try:
        hit = await client.get(key)
        return json.loads(hit) if hit else None
    except Exception:  # pragma: no cover - never let the cache break the request
        return None


async def _cluster_cache_set(key: str, value: dict) -> None:
    client = _redis_client()
    if client is None:
        return
    try:
        await client.set(key, json.dumps(value, default=str), ex=_CLUSTER_CACHE_TTL)
    except Exception:  # pragma: no cover
        pass


# Placeholder venue name for events whose source gave no venue (see worker enrich).
# It has no real location, so it must never appear on the map / in clusters / counts.
_PLACEHOLDER_VENUE = "Unknown venue"


class EventQueryService:
    def __init__(self, db: AsyncSession):
        self.db = db

    def _apply_filters(
        self,
        stmt: Select[Any],
        date_from: datetime | None,
        date_to: datetime | None,
        categories: list[str] | None,
        price_min: float | None,
        price_max: float | None,
        q: str | None,
    ):
        filters = []
        # Hide events that have already ENDED. An occurrence is "active" from
        # `floor` onward if it ends at/after the floor (ongoing exhibitions whose
        # start is in the past are kept; truly finished events drop out). Default
        # floor is the start of today, so the map never shows past events.
        floor = date_from or datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
        filters.append(func.coalesce(EventOccurrence.date_end, EventOccurrence.date_start) >= floor)
        if date_to:
            filters.append(EventOccurrence.date_start <= date_to)
        if categories:
            filters.append(Event.category.in_(categories))
        if price_min is not None:
            filters.append(or_(EventOccurrence.price_min.is_(None), EventOccurrence.price_min >= price_min))
        if price_max is not None:
            filters.append(or_(EventOccurrence.price_max.is_(None), EventOccurrence.price_max <= price_max))
        if q:
            filters.append(
                or_(
                    Event.canonical_title.ilike(f"%{q}%"),
                    Event.canonical_description.ilike(f"%{q}%"),
                )
            )
        if filters:
            stmt = stmt.where(and_(*filters))
        return stmt

    # At/above this zoom the map returns individual pins; below it, the server
    # returns grid-aggregated clusters so payload/marker count don't grow with the
    # total number of events.
    _DETAIL_ZOOM = 14

    @staticmethod
    def _bbox_clause(bbox: tuple[float, float, float, float]):
        min_lon, min_lat, max_lon, max_lat = bbox
        return text(
            "ST_Intersects(venues.geom::geometry, ST_MakeEnvelope(:min_lon, :min_lat, :max_lon, :max_lat, 4326))"
        ).bindparams(
            bindparam("min_lon", min_lon),
            bindparam("min_lat", min_lat),
            bindparam("max_lon", max_lon),
            bindparam("max_lat", max_lat),
        )

    # Only events in/around Moscow render — a permanent guard against bad/foreign
    # coordinates (transposed lat/lon land in the Caspian near Iran; a touring date
    # lands in Almaty). Envelope is generous (lon 30..45, lat 50..60) so legitimate
    # Moscow-region events (Tver/Kaluga day-trips) stay visible.
    @staticmethod
    def _region_clause():
        return text("ST_Intersects(venues.geom::geometry, ST_MakeEnvelope(30.0, 50.0, 45.0, 60.0, 4326))")

    async def map_events(
        self,
        bbox: tuple[float, float, float, float] | None,
        date_from: datetime | None,
        date_to: datetime | None,
        categories: list[str] | None,
        price_min: float | None,
        price_max: float | None,
        q: str | None,
        limit: int | None,
        offset: int,
        zoom: int | None = None,
    ):
        # Below detail zoom → clusters. bbox is optional: the client aggregates over
        # the WHOLE city (keyed on zoom only) so panning doesn't refetch/redraw.
        # Served from a short Redis cache when warm (the frontend prefetches every
        # zoom level), so a cache hit answers with zero DB queries.
        if zoom is not None and zoom < self._DETAIL_ZOOM:
            key = _cluster_cache_key(zoom, bbox, date_from, date_to, categories, price_min, price_max, q)
            cached = await _cluster_cache_get(key)
            if cached is not None:
                return cached
            total = await self._count_pinnable(date_from, date_to, categories, price_min, price_max, q)
            clusters = await self._cluster(bbox, zoom, date_from, date_to, categories, price_min, price_max, q)
            result = {"clusters": clusters, "items": [], "total": total}
            await _cluster_cache_set(key, result)
            return result
        # "Показать N" = filter-wide count of map-able events (stable while panning).
        total = await self._count_pinnable(date_from, date_to, categories, price_min, price_max, q)
        items = await self._detail(bbox, date_from, date_to, categories, price_min, price_max, q, limit, offset)
        return {"clusters": [], "items": items, "total": total}

    async def _count_pinnable(self, date_from, date_to, categories, price_min, price_max, q) -> int:
        stmt = (
            select(func.count(func.distinct(Event.event_id)))
            .select_from(Event)
            .join(EventOccurrence, EventOccurrence.event_id == Event.event_id)
            .join(Venue, Venue.venue_id == EventOccurrence.venue_id)
            .where(Event.status == "active", Venue.geom.is_not(None))
            .where(Venue.name.is_distinct_from(_PLACEHOLDER_VENUE))
            .where(self._region_clause())
        )
        stmt = self._apply_filters(stmt, date_from, date_to, categories, price_min, price_max, q)
        return int(await self.db.scalar(stmt) or 0)

    async def _cluster(self, bbox, zoom, date_from, date_to, categories, price_min, price_max, q):
        # One representative point per event (soonest occurrence's venue) within the
        # viewport, then snap to a zoom-sized grid and aggregate to cluster centroids.
        inner = (
            select(Event.event_id.label("eid"), cast(Venue.geom, Geometry).label("g"), EventOccurrence.date_start.label("ds"))
            .join(EventOccurrence, EventOccurrence.event_id == Event.event_id)
            .join(Venue, Venue.venue_id == EventOccurrence.venue_id)
            .where(Event.status == "active", Venue.geom.is_not(None))
            .where(Venue.name.is_distinct_from(_PLACEHOLDER_VENUE))
            .where(self._region_clause())
        )
        inner = self._apply_filters(inner, date_from, date_to, categories, price_min, price_max, q)
        if bbox is not None:
            inner = inner.where(self._bbox_clause(bbox))
        inner = (
            inner.distinct(Event.event_id)
            .order_by(Event.event_id, EventOccurrence.date_start.asc())
            .subquery()
        )
        # Aggregate to a FINE grid and place each cell's marker at the real centroid
        # of its events (so a cluster sits where its events actually are, not on a
        # lattice vertex that can drift far from the city). The fine grid keeps this
        # cheap and the centroids local; collisions are then resolved by merging.
        cell = 45.0 / (2 ** zoom)
        grid = func.ST_SnapToGrid(inner.c.g, cell, cell)
        centroid = func.ST_Centroid(func.ST_Collect(inner.c.g))
        stmt = (
            select(func.count().label("cnt"), func.ST_Y(centroid).label("lat"), func.ST_X(centroid).label("lon"))
            .select_from(inner)
            .group_by(grid)
        )
        rows = (await self.db.execute(stmt)).all()
        cells = [
            {"lat": float(la), "lon": float(lo), "count": int(cnt)}
            for cnt, la, lo in rows
            if la is not None and lo is not None
        ]
        return self._merge_clusters(cells, zoom)

    @staticmethod
    def _merge_clusters(cells: list[dict], zoom: int, sep_px: float = 84.0) -> list[dict]:
        # Greedy proximity merge (a mini-supercluster): combine cells whose centres
        # are within `sep_px` screen pixels so markers never overlap, while keeping
        # each merged cluster at the count-weighted centroid of its events. Biggest
        # clusters are placed first so dense areas anchor the merged centre.
        # Web-Mercator: 256*2**zoom px span 360° of longitude; a latitude degree
        # spans more px (÷cos φ), so we scale Δlat to longitude-equivalent units to
        # compare distances as they look ON SCREEN at Moscow's latitude.
        sep_lon = sep_px * 360.0 / (256.0 * (2 ** zoom))
        lat_scale = math.cos(math.radians(55.75)) or 1.0
        merged: list[dict] = []
        for c in sorted(cells, key=lambda x: -x["count"]):
            for m in merged:
                dlon = c["lon"] - m["lon"]
                dlat = (c["lat"] - m["lat"]) / lat_scale
                if dlon * dlon + dlat * dlat <= sep_lon * sep_lon:
                    total = m["count"] + c["count"]
                    m["lat"] = (m["lat"] * m["count"] + c["lat"] * c["count"]) / total
                    m["lon"] = (m["lon"] * m["count"] + c["lon"] * c["count"]) / total
                    m["count"] = total
                    break
            else:
                merged.append(dict(c))
        return [{"id": f"c{i}", "lat": m["lat"], "lon": m["lon"], "count": m["count"]} for i, m in enumerate(merged)]

    async def _detail(self, bbox, date_from, date_to, categories, price_min, price_max, q, limit, offset):
        # Compute venue lat/lon in the main query (was an N+1 per-row subquery).
        lat_col = func.ST_Y(cast(Venue.geom, Geometry)).label("lat")
        lon_col = func.ST_X(cast(Venue.geom, Geometry)).label("lon")
        stmt = (
            select(Event, EventOccurrence, Venue.name.label("venue_name"), Venue.hours_json.label("venue_hours"), lat_col, lon_col)
            .join(EventOccurrence, EventOccurrence.event_id == Event.event_id)
            .outerjoin(Venue, Venue.venue_id == EventOccurrence.venue_id)
            .where(Event.status == "active")
        )
        stmt = self._apply_filters(stmt, date_from, date_to, categories, price_min, price_max, q)
        # Only Moscow-region events with coordinates (implies geom is not null).
        stmt = stmt.where(self._region_clause())
        stmt = stmt.where(Venue.name.is_distinct_from(_PLACEHOLDER_VENUE))
        if bbox:
            stmt = stmt.where(self._bbox_clause(bbox))
        # One row per event — the soonest in-window occurrence — so an event with
        # several showtimes (e.g. 16 & 23 June) shows a single pin, not one per date.
        stmt = stmt.distinct(Event.event_id).order_by(Event.event_id, EventOccurrence.date_start.asc())
        rows = (await self.db.execute(stmt.limit(limit).offset(offset))).all()
        items = [
            {
                "event_id": event.event_id,
                "title": event.canonical_title,
                "category": event.category,
                "date_start": occ.date_start,
                "date_end": occ.date_end,
                "price_min": occ.price_min,
                "venue": venue_name,
                "venue_hours": venue_hours,
                "lat": float(lat) if lat is not None else None,
                "lon": float(lon) if lon is not None else None,
                "primary_image_url": event.cached_image_url or event.primary_image_url,
            }
            for event, occ, venue_name, venue_hours, lat, lon in rows
        ]
        # DISTINCT ON forces event_id ordering; present pins by soonest date instead.
        items.sort(key=lambda it: it["date_start"])
        return items

    async def event_detail(self, event_id: UUID):
        event = await self.db.get(Event, event_id)
        if not event:
            return None
        rows = (await self.db.execute(
            select(
                EventOccurrence,
                Venue.name.label("venue_name"),
                Venue.address.label("venue_address"),
                Venue.hours_json.label("venue_hours"),
                func.ST_Y(cast(Venue.geom, Geometry)).label("lat"),
                func.ST_X(cast(Venue.geom, Geometry)).label("lon"),
            )
            .outerjoin(Venue, Venue.venue_id == EventOccurrence.venue_id)
            .where(EventOccurrence.event_id == event_id)
            # Only upcoming sessions (3h grace, matching the lifecycle "live" rule) —
            # the map pin already filters, so the sheet must not surface a past date.
            .where(func.coalesce(EventOccurrence.date_end, EventOccurrence.date_start) >= text("now() - interval '3 hours'"))
            .order_by(EventOccurrence.date_start.asc())
        )).all()
        occurrences = [
            {
                "occurrence_id": occ.occurrence_id,
                "date_start": occ.date_start,
                "date_end": occ.date_end,
                "price_min": occ.price_min,
                "price_max": occ.price_max,
                "currency": occ.currency,
                "source_best_url": occ.source_best_url,
                "venue": venue_name,
                "address": venue_address,
                "venue_hours": venue_hours,
                "lat": float(lat) if lat is not None else None,
                "lon": float(lon) if lon is not None else None,
            }
            for occ, venue_name, venue_address, venue_hours, lat, lon in rows
        ]
        return {
            "event_id": event.event_id,
            "canonical_title": event.canonical_title,
            "canonical_description": event.canonical_description,
            "category": event.category,
            "subcategory": event.subcategory,
            "age_limit": event.age_limit,
            "primary_image_url": event.cached_image_url or event.primary_image_url,
            "occurrences": occurrences,
        }

    async def nearby(
        self,
        lat: float,
        lon: float,
        radius_m: int,
        date_from: datetime | None,
        date_to: datetime | None,
        categories: list[str] | None,
        q: str | None,
        limit: int,
    ):
        # Cast to geography so ST_DWithin/ST_Distance use meters, not degrees.
        point = cast(func.ST_SetSRID(func.ST_MakePoint(lon, lat), 4326), Geography(geometry_type="POINT", srid=4326))
        # Distance + coords computed in the main query (was an N+1: 2-3 extra queries/row).
        dist_col = func.ST_Distance(Venue.geom, point).label("distance_m")
        lat_col = func.ST_Y(cast(Venue.geom, Geometry)).label("lat")
        lon_col = func.ST_X(cast(Venue.geom, Geometry)).label("lon")
        stmt = (
            select(Event, EventOccurrence, Venue.name.label("venue_name"), dist_col, lat_col, lon_col)
            .join(EventOccurrence, EventOccurrence.event_id == Event.event_id)
            .join(Venue, Venue.venue_id == EventOccurrence.venue_id)
            .where(Event.status == "active")
        )
        stmt = self._apply_filters(stmt, date_from, date_to, categories, None, None, q)
        stmt = (
            stmt.where(Venue.geom.is_not(None))
            .where(func.ST_DWithin(Venue.geom, point, radius_m))
            .order_by(dist_col.asc())
            .limit(limit)
        )
        rows = (await self.db.execute(stmt)).all()
        result = [
            {
                "event_id": event.event_id,
                "title": event.canonical_title,
                "category": event.category,
                "distance_m": float(distance or 0.0),
                "date_start": occ.date_start,
                "price_min": occ.price_min,
                "venue": venue_name,
                "lat": float(lat) if lat is not None else None,
                "lon": float(lon) if lon is not None else None,
            }
            for event, occ, venue_name, distance, lat, lon in rows
        ]
        return {"items": result}

    async def categories(self):
        rows = (await self.db.execute(select(Event.category).distinct().order_by(Event.category.asc()))).scalars().all()
        return {"categories": rows}

    async def search(self, q: str, city: str | None, limit: int):
        score = func.similarity(Event.canonical_title, bindparam("q", q))
        match = or_(Event.canonical_title.ilike(f"%{q}%"), Event.canonical_description.ilike(f"%{q}%"))
        # Tie-break on event_id so equal-score rows (and the many description-only
        # matches that score ~0) come back in a stable, deterministic order rather
        # than at the DB's whim — without it, the same query can re-shuffle.
        order = (score.desc(), Event.event_id.asc())

        if city:
            stmt = (
                select(Event.event_id, Event.canonical_title, score.label("score"))
                .join(EventOccurrence, EventOccurrence.event_id == Event.event_id)
                .join(Venue, Venue.venue_id == EventOccurrence.venue_id)
                .where(Event.status == "active")
                .where(Venue.city.ilike(city))
                .where(match)
                .distinct()
                .order_by(*order)
                .limit(limit)
            )
        else:
            stmt = (
                select(Event.event_id, Event.canonical_title, score.label("score"))
                .where(Event.status == "active")
                .where(match)
                .order_by(*order)
                .limit(limit)
            )

        rows = (await self.db.execute(stmt)).all()
        return {"items": [{"event_id": row[0], "title": row[1], "score": float(row[2] or 0)} for row in rows]}
