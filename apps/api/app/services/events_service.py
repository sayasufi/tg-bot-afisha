import hashlib
import json
import math
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID

import redis.asyncio as aioredis
from geoalchemy2 import Geography, Geometry
from sqlalchemy import Select, and_, bindparam, cast, func, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from core.codes import event_code
from core.config.settings import get_settings
from core.db.models import Event, EventOccurrence, Venue

# The map response (clusters or pins) depends only on (zoom, bbox, filters) and the
# dataset, which changes only when the pipeline ingests. So the route caches the FULLY
# SERIALIZED response bytes + an ETag in Redis briefly: a warm hit skips the DB, the
# row build AND the JSON encode entirely, and an If-None-Match match returns a bare
# 304. Best-effort — any Redis hiccup falls back to a live query + encode. Async
# client, created once on the API's single event loop.
_MAP_CACHE_PREFIX = "map:resp:v4:"  # v4: cache stores the GZIPPED body bytes
_MAP_CACHE_TTL = 60
_redis: aioredis.Redis | None = None
_redis_off = False


def _redis_client() -> aioredis.Redis | None:
    # decode_responses=False: the map cache stores GZIPPED (binary) response bytes, not
    # text. This is the ONLY user of this client (recommend.py has its own text client).
    global _redis, _redis_off
    if _redis_off:
        return None
    if _redis is None:
        try:
            _redis = aioredis.from_url(
                get_settings().redis_url, decode_responses=False, socket_timeout=0.5, socket_connect_timeout=0.5
            )
        except Exception:  # pragma: no cover - cache is best-effort
            _redis_off = True
            return None
    return _redis


def map_cache_key(zoom, bbox, date_from, date_to, categories, price_min, price_max, q, limit, offset) -> str:
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
            limit,
            offset,
        ],
        default=str,
        sort_keys=True,
    )
    return _MAP_CACHE_PREFIX + hashlib.sha256(raw.encode("utf-8")).hexdigest()


async def map_cache_get(key: str) -> tuple[bytes, str] | None:
    """(gzipped_body, etag) for a cached map response, or None. Stored as
    b'etag\\n' + gzipped_body in one key — the ETag is ASCII with no newline, so the
    FIRST newline is the separator (the gzip stream after it may contain 0x0a)."""
    client = _redis_client()
    if client is None:
        return None
    try:
        hit = await client.get(key)
    except Exception:  # pragma: no cover - never let the cache break the request
        return None
    if not hit:
        return None
    nl = hit.find(b"\n")
    if nl < 0:
        return None
    return hit[nl + 1 :], hit[:nl].decode("ascii")


async def map_cache_set(key: str, gzipped_body: bytes, etag: str) -> None:
    client = _redis_client()
    if client is None:
        return
    try:
        await client.set(key, etag.encode("ascii") + b"\n" + gzipped_body, ex=_MAP_CACHE_TTL)
    except Exception:  # pragma: no cover
        pass


# Placeholder venue name for events whose source gave no venue (see worker enrich).
# It has no real location, so it must never appear on the map / in clusters / counts.
_PLACEHOLDER_VENUE = "Unknown venue"

# All current cities are UTC+3 (Europe/Moscow, no DST since 2014). Used to compute the
# venue "open now" signal in the venues' own wall-clock time.
_MSK = timezone(timedelta(hours=3))


def _hm_to_min(s) -> int:
    try:
        h, m = str(s).split(":")
        return (int(h) if h else 0) * 60 + (int(m) if m else 0)
    except Exception:
        return 0


def _venue_open_now(hours, now_msk: datetime) -> bool | None:
    """Is the venue open at Moscow `now`? true / false / None (unknown). Server-side port
    of the frontend venueOpenNow (miniapp/src/lib/datetime.ts) so the map payload can ship
    a 1-byte tri-state per pin instead of the full weekly schedule (~18% of the gzipped
    response), AND so it's correct for non-MSK clients (the JS port read the DEVICE clock
    against Moscow hours). Keep in sync with datetime.ts venueOpenNow/isTerritoryHours."""
    if not isinstance(hours, dict):
        return None
    week = hours.get("week")
    if not isinstance(week, list) or len(week) != 7:
        return None

    def _rtc_day(day) -> bool:  # a single round-the-clock range
        if not isinstance(day, list) or len(day) != 1:
            return False
        r = day[0]
        return isinstance(r, list) and len(r) == 2 and (r[0] == r[1] or (r[0] == "00:00" and r[1] in ("24:00", "00:00")))

    if all(_rtc_day(d) for d in week):
        return None  # all-week 24/7 = matched a TERRITORY, not the hall → unknown
    day = week[now_msk.isoweekday() % 7]  # JS getDay() convention: 0=Sun .. 6=Sat
    if day is None:
        return False  # closed today
    if not isinstance(day, list) or len(day) == 0:
        return None  # unknown
    mins = now_msk.hour * 60 + now_msk.minute
    for r in day:
        if not isinstance(r, list) or len(r) != 2:
            continue
        open_m = _hm_to_min(r[0])
        close_m = _hm_to_min(r[1]) or 1440  # 00:00 close = end of day
        if open_m == close_m:
            return True  # round-the-clock (single day)
        if open_m <= mins < close_m:
            return True
    return False  # outside today's ranges


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

    # Only events within an ACTIVE city's region render — a guard against bad/foreign
    # coordinates (transposed lat/lon land in the Caspian; a touring date lands in
    # Almaty). The region is each city's own centre ± region_radius_km from core.cities,
    # so it's fully city-agnostic and grows automatically as cities are activated — no
    # hardcoded Moscow box.
    @staticmethod
    def _region_clause():
        from core.cities import active_cities

        parts = [
            f"ST_DWithin(venues.geom, ST_SetSRID(ST_MakePoint({c.center[1]}, {c.center[0]}), 4326)::geography, {c.region_radius_km * 1000})"
            for c in active_cities()
        ]
        return text("(" + " OR ".join(parts) + ")") if parts else text("true")

    @staticmethod
    def _concrete_time_clause():
        # Previously HID all-day, hours-less ongoing events (nothing but "в часы
        # работы" to show). We now keep them visible with an honest "время уточняйте"
        # (the frontend never shows the misleading "в часы работы"/24-7 "круглосуточно"
        # anymore, and the hours resolver recovers real museum/hall hours where it can),
        # so this is a no-op. Kept as a single seam in case we want to re-gate later.
        return text("true")

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
        # Below detail zoom → server-aggregated clusters (payload/marker count don't
        # grow with the catalogue); at/above it → individual pins. The WHOLE response
        # is cached as serialized bytes by the route (map_cache_*), so repeat loads
        # across the frontend's per-zoom prefetch and across users skip all of this.
        if zoom is not None and zoom < self._DETAIL_ZOOM:
            total = await self._count_pinnable(date_from, date_to, categories, price_min, price_max, q)
            clusters = await self._cluster(bbox, zoom, date_from, date_to, categories, price_min, price_max, q)
            return {"clusters": clusters, "items": [], "total": total}
        items = await self._detail(bbox, date_from, date_to, categories, price_min, price_max, q, limit, offset)
        # "Показать N" = filter-wide count of map-able events. When the whole city is
        # fetched (no bbox, no paging) it EQUALS the result size after DISTINCT ON, so
        # derive it from `items` instead of firing a second identical ~14k-row join.
        if bbox is None and not limit and not offset:
            total = len(items)
        else:
            total = await self._count_pinnable(date_from, date_to, categories, price_min, price_max, q)
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
            .where(self._concrete_time_clause())
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
            .where(self._concrete_time_clause())
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
        # Select EXACTLY the columns the dict below reads — a Core row of scalars, NOT
        # full Event/EventOccurrence ORM entities. This skips hydrating every row's
        # canonical_description (a big Text column the map never shows) and the ORM
        # identity-map overhead, which was ~the dominant cost of this whole-city query.
        stmt = (
            select(
                Event.event_id.label("event_id"),
                Event.display_no.label("display_no"),
                Event.canonical_title.label("title"),
                Event.category.label("category"),
                Event.cached_image_url.label("cached_image_url"),
                Event.primary_image_url.label("primary_image_url"),
                EventOccurrence.date_start.label("date_start"),
                EventOccurrence.date_end.label("date_end"),
                EventOccurrence.price_min.label("price_min"),
                Venue.name.label("venue_name"),
                Venue.hours_json.label("venue_hours"),
                Venue.city.label("venue_city"),
                lat_col,
                lon_col,
            )
            .join(EventOccurrence, EventOccurrence.event_id == Event.event_id)
            .outerjoin(Venue, Venue.venue_id == EventOccurrence.venue_id)
            .where(Event.status == "active")
        )
        stmt = self._apply_filters(stmt, date_from, date_to, categories, price_min, price_max, q)
        # Only Moscow-region events with coordinates (implies geom is not null).
        stmt = stmt.where(self._region_clause())
        stmt = stmt.where(Venue.name.is_distinct_from(_PLACEHOLDER_VENUE))
        stmt = stmt.where(self._concrete_time_clause())
        if bbox:
            stmt = stmt.where(self._bbox_clause(bbox))
        # One row per event — the soonest occurrence you can still ACT on — so an
        # event with several showtimes (e.g. 16 & 23 June) shows a single pin, not
        # one per date. Future-first: a venue with sessions at 14:00 & 21:00 viewed
        # at 18:00 ships the catchable 21:00, not the already-started 14:00 (this is
        # what makes the "можно пойти сейчас" highlight correct). Ongoing runs, whose
        # only occurrence began in the past, still fall through to that occurrence.
        stmt = stmt.distinct(Event.event_id).order_by(
            Event.event_id,
            (EventOccurrence.date_start < func.now()).asc(),
            EventOccurrence.date_start.asc(),
        )
        # No default cap: the map client fetches the WHOLE filtered set with no bbox
        # and clusters it client-side (and derives the "Показать N" count + radius
        # filter from it), so capping here silently drops pins. Callers that want a
        # page pass an explicit limit. (At city scale this is tens of KB gzipped; a
        # viewport-bbox fetch is the lever if the dataset ever grows past that.)
        rows = (await self.db.execute(stmt.limit(limit).offset(offset))).all()
        now_msk = datetime.now(_MSK)
        items = [
            {
                "event_id": r.event_id,
                "code": event_code(r.display_no, r.venue_city),
                "title": r.title,
                "category": r.category,
                "date_start": r.date_start,
                "date_end": r.date_end,
                # float (not Decimal) — JSON-encodable by orjson and the wire type the
                # client coerces to anyway; avoids per-row Decimal handling.
                "price_min": float(r.price_min) if r.price_min is not None else None,
                "venue": r.venue_name,
                # Compact "open now" tri-state instead of the full weekly schedule
                # (which was ~18% of the gzipped payload). Full hours stay on the
                # detail endpoint. The client uses this for the "идёт сейчас" highlight.
                "open_now": _venue_open_now(r.venue_hours, now_msk),
                "lat": float(r.lat) if r.lat is not None else None,
                "lon": float(r.lon) if r.lon is not None else None,
                "primary_image_url": r.cached_image_url or r.primary_image_url,
            }
            for r in rows
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
                Venue.city.label("venue_city"),
                func.ST_Y(cast(Venue.geom, Geometry)).label("lat"),
                func.ST_X(cast(Venue.geom, Geometry)).label("lon"),
            )
            .outerjoin(Venue, Venue.venue_id == EventOccurrence.venue_id)
            .where(EventOccurrence.event_id == event_id)
            # Same floor as the map (start of today, UTC) — NOT a tighter now()-3h. A
            # tighter floor could return ZERO occurrences for an event the map still pins
            # (single past-today session, end>floor), leaving a dateless/broken sheet.
            .where(func.coalesce(EventOccurrence.date_end, EventOccurrence.date_start) >= func.date_trunc("day", func.now()))
            # Future-first (then by time), matching the map pin: the headline session
            # is the soonest you can still go to, not an earlier one already past.
            .order_by((EventOccurrence.date_start < func.now()).asc(), EventOccurrence.date_start.asc())
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
            for occ, venue_name, venue_address, venue_hours, venue_city, lat, lon in rows
        ]
        detail_city = rows[0].venue_city if rows else None
        return {
            "event_id": event.event_id,
            "code": event_code(event.display_no, detail_city),
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
        # One row per EVENT (its nearest occurrence) — a recurring event must not eat
        # several `limit` slots. DISTINCT ON forces event_id order; sort by distance and
        # cut the limit in Python (same shape as _detail).
        stmt = (
            stmt.where(Venue.geom.is_not(None))
            .where(func.ST_DWithin(Venue.geom, point, radius_m))
            .distinct(Event.event_id)
            # DISTINCT ON keeps the FIRST row per event by this order: nearest venue,
            # then future-first (soonest still-catchable session), then earliest — so a
            # same-venue recurring event reports a deterministic, soonest occurrence,
            # matching _detail/event_detail instead of an arbitrary distance-tie winner.
            .order_by(
                Event.event_id,
                dist_col.asc(),
                (EventOccurrence.date_start < func.now()).asc(),
                EventOccurrence.date_start.asc(),
            )
        )
        rows = (await self.db.execute(stmt)).all()
        rows = sorted(rows, key=lambda r: r.distance_m if r.distance_m is not None else 0.0)[:limit]
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
