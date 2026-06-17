import hashlib
import json
import math
import re
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID

import redis.asyncio as aioredis
from geoalchemy2 import Geography, Geometry
from sqlalchemy import Select, and_, bindparam, case, cast, func, nullslast, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from core.codes import event_code, parse_event_code
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


def map_cache_key(zoom, bbox, date_from, date_to, categories, price_min, price_max, q, limit, offset, city=None) -> str:
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
            city,
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

# Search-as-you-type helpers --------------------------------------------------
# A query that looks like a public event code ("MSK-04PN", "msk04pn", "04PN"): 2-4
# letters + optional sep + 2-8 base32 chars. We try an exact code lookup for these.
_CODE_RE = re.compile(r"^[A-Za-z]{2,4}[-·\s]?[0-9A-Za-z]{2,8}$")


def _looks_like_code(q: str) -> bool:
    # Require a dash or a digit so plain Latin words ("standup", "techno") don't waste a
    # display_no probe — real codes always have one (e.g. "MSK-04PN").
    s = q.strip()
    return bool(_CODE_RE.match(s)) and ("-" in s or any(c.isdigit() for c in s))


# Phonetic transliteration so a query typed in ONE script also finds titles in the OTHER
# ("bolshoi" → "Большой", "стендап" → "standup"). Approximate by design — it only feeds
# ILIKE/trigram, which tolerate the imperfections. Digraphs MUST come before single chars.
_LAT2CYR = [
    ("shch", "щ"), ("sch", "щ"), ("yo", "ё"), ("yu", "ю"), ("ya", "я"), ("ye", "е"),
    ("zh", "ж"), ("kh", "х"), ("ts", "ц"), ("ch", "ч"), ("sh", "ш"), ("eh", "э"),
    ("a", "а"), ("b", "б"), ("v", "в"), ("g", "г"), ("d", "д"), ("e", "е"), ("z", "з"),
    ("i", "и"), ("j", "ж"), ("k", "к"), ("l", "л"), ("m", "м"), ("n", "н"), ("o", "о"),
    ("p", "п"), ("q", "к"), ("r", "р"), ("s", "с"), ("t", "т"), ("u", "у"), ("f", "ф"),
    ("h", "х"), ("c", "ц"), ("w", "в"), ("x", "кс"), ("y", "ы"),
]
_CYR2LAT = [
    ("щ", "shch"), ("ш", "sh"), ("ч", "ch"), ("ж", "zh"), ("х", "kh"), ("ц", "ts"),
    ("ю", "yu"), ("я", "ya"), ("ё", "yo"), ("э", "e"), ("а", "a"), ("б", "b"), ("в", "v"),
    ("г", "g"), ("д", "d"), ("е", "e"), ("з", "z"), ("и", "i"), ("й", "y"), ("к", "k"),
    ("л", "l"), ("м", "m"), ("н", "n"), ("о", "o"), ("п", "p"), ("р", "r"), ("с", "s"),
    ("т", "t"), ("у", "u"), ("ф", "f"), ("ы", "y"), ("ъ", ""), ("ь", ""),
]
_CYR_SET = frozenset("абвгдежзийклмнопрстуфхцчшщъыьэюяё")


def _translit_variant(qn: str) -> str | None:
    """The opposite-script form of the query, or None when it's mixed / scriptless."""
    low = qn.lower()
    has_lat = any("a" <= c <= "z" for c in low)
    has_cyr = any(c in _CYR_SET for c in low)
    table = _LAT2CYR if (has_lat and not has_cyr) else _CYR2LAT if (has_cyr and not has_lat) else None
    if table is None:
        return None
    out = low
    for a, b in table:
        out = out.replace(a, b)
    return out or None


def _region_sql(city) -> str:
    """Raw-SQL region predicate (venues.geom within a city's radius) for the search CTE —
    same city-agnostic guard as _region_clause, as a string we can embed in text()."""
    from core.cities import active_cities

    cities = [city] if city is not None else active_cities()
    parts = [
        f"ST_DWithin(venues.geom, ST_SetSRID(ST_MakePoint({c.center[1]}, {c.center[0]}), 4326)::geography, {c.region_radius_km * 1000})"
        for c in cities
    ]
    return "(" + " OR ".join(parts) + ")" if parts else "true"


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

    # Only events within a city's region render — a guard against bad/foreign coordinates
    # (transposed lat/lon land in the Caspian; a touring date lands in Almaty). The region
    # is the city's own centre ± region_radius_km from core.cities. With `city` given the
    # map is SCOPED to that one city (multi-city: a Moscow user never sees SPb pins); with
    # no city it ORs over all active cities (back-compat / "everything" fallback).
    @staticmethod
    def _region_clause(city=None):
        from core.cities import active_cities

        cities = [city] if city is not None else active_cities()
        parts = [
            f"ST_DWithin(venues.geom, ST_SetSRID(ST_MakePoint({c.center[1]}, {c.center[0]}), 4326)::geography, {c.region_radius_km * 1000})"
            for c in cities
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
        city=None,
    ):
        # Below detail zoom → server-aggregated clusters (payload/marker count don't
        # grow with the catalogue); at/above it → individual pins. The WHOLE response
        # is cached as serialized bytes by the route (map_cache_*), so repeat loads
        # across the frontend's per-zoom prefetch and across users skip all of this.
        # `city` (a CityConfig) scopes everything to one city when given.
        if zoom is not None and zoom < self._DETAIL_ZOOM:
            total = await self._count_pinnable(date_from, date_to, categories, price_min, price_max, q, city)
            clusters = await self._cluster(bbox, zoom, date_from, date_to, categories, price_min, price_max, q, city)
            return {"clusters": clusters, "items": [], "total": total}
        items = await self._detail(bbox, date_from, date_to, categories, price_min, price_max, q, limit, offset, city)
        # "Показать N" = filter-wide count of map-able events. When the whole city is
        # fetched (no bbox, no paging) it EQUALS the result size after DISTINCT ON, so
        # derive it from `items` instead of firing a second identical ~14k-row join.
        if bbox is None and not limit and not offset:
            total = len(items)
        else:
            total = await self._count_pinnable(date_from, date_to, categories, price_min, price_max, q, city)
        return {"clusters": [], "items": items, "total": total}

    async def _count_pinnable(self, date_from, date_to, categories, price_min, price_max, q, city=None) -> int:
        stmt = (
            select(func.count(func.distinct(Event.event_id)))
            .select_from(Event)
            .join(EventOccurrence, EventOccurrence.event_id == Event.event_id)
            .join(Venue, Venue.venue_id == EventOccurrence.venue_id)
            .where(Event.status == "active", Venue.geom.is_not(None))
            .where(Venue.name.is_distinct_from(_PLACEHOLDER_VENUE))
            .where(self._region_clause(city))
            .where(self._concrete_time_clause())
        )
        stmt = self._apply_filters(stmt, date_from, date_to, categories, price_min, price_max, q)
        return int(await self.db.scalar(stmt) or 0)

    async def _cluster(self, bbox, zoom, date_from, date_to, categories, price_min, price_max, q, city=None):
        # One representative point per event (soonest occurrence's venue) within the
        # viewport, then snap to a zoom-sized grid and aggregate to cluster centroids.
        inner = (
            select(Event.event_id.label("eid"), cast(Venue.geom, Geometry).label("g"), EventOccurrence.date_start.label("ds"))
            .join(EventOccurrence, EventOccurrence.event_id == Event.event_id)
            .join(Venue, Venue.venue_id == EventOccurrence.venue_id)
            .where(Event.status == "active", Venue.geom.is_not(None))
            .where(Venue.name.is_distinct_from(_PLACEHOLDER_VENUE))
            .where(self._region_clause(city))
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

    async def _detail(self, bbox, date_from, date_to, categories, price_min, price_max, q, limit, offset, city=None):
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
        # Only in-region events with coordinates (implies geom is not null) — scoped to
        # the requested city when given (multi-city), else all active cities.
        stmt = stmt.where(self._region_clause(city))
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

    async def list_events(
        self, bbox, date_from, date_to, categories, price_max, q, sort, lat, lon, radius_km, limit, offset, city=None
    ):
        """Paginated, sortable flat list of events in the bbox — the 'list view' of the
        map. Reuses the SAME filters as map_events, so the list matches the pins; adds a
        chosen sort + LIMIT/OFFSET + a total count."""
        lat_col = func.ST_Y(cast(Venue.geom, Geometry)).label("lat")
        lon_col = func.ST_X(cast(Venue.geom, Geometry)).label("lon")
        has_pt = lat is not None and lon is not None
        pt = func.ST_SetSRID(func.ST_MakePoint(lon, lat), 4326) if has_pt else None
        cols = [
            Event.event_id.label("event_id"),
            Event.display_no.label("display_no"),
            Event.canonical_title.label("title"),
            Event.category.label("category"),
            Event.cached_image_url.label("cached_image_url"),
            Event.primary_image_url.label("primary_image_url"),
            Event.popularity_score.label("popularity_score"),
            EventOccurrence.date_start.label("date_start"),
            EventOccurrence.date_end.label("date_end"),
            EventOccurrence.price_min.label("price_min"),
            Venue.name.label("venue_name"),
            Venue.hours_json.label("venue_hours"),
            Venue.city.label("venue_city"),
            lat_col,
            lon_col,
        ]
        if has_pt:
            cols.append(func.ST_DistanceSphere(cast(Venue.geom, Geometry), pt).label("dist_m"))
        base = (
            select(*cols)
            .join(EventOccurrence, EventOccurrence.event_id == Event.event_id)
            .outerjoin(Venue, Venue.venue_id == EventOccurrence.venue_id)
            .where(Event.status == "active")
        )
        base = self._apply_filters(base, date_from, date_to, categories, None, price_max, q)
        base = base.where(self._region_clause(city)).where(Venue.name.is_distinct_from(_PLACEHOLDER_VENUE)).where(self._concrete_time_clause())
        if bbox:
            base = base.where(self._bbox_clause(bbox))
        if radius_km and has_pt:
            base = base.where(func.ST_DistanceSphere(cast(Venue.geom, Geometry), pt) <= radius_km * 1000.0)
        # One row per event — the soonest actionable occurrence — exactly like the map pin.
        inner = (
            base.distinct(Event.event_id)
            .order_by(Event.event_id, (EventOccurrence.date_start < func.now()).asc(), EventOccurrence.date_start.asc())
            .subquery()
        )
        total = await self.db.scalar(select(func.count()).select_from(inner)) or 0
        rows_q = select(inner)
        if sort == "distance" and has_pt:
            rows_q = rows_q.order_by(nullslast(inner.c.dist_m.asc()))
        elif sort == "popularity":
            # popularity_score is unpopulated; the real signal is the rec:views counter
            # we collect ourselves. Rank the viewed events by their count, rest by date.
            rank = await self._views_rank(inner.c.event_id)
            rows_q = rows_q.order_by(rank.desc(), inner.c.date_start.asc()) if rank is not None else rows_q.order_by(inner.c.date_start.asc())
        elif sort == "price":
            rows_q = rows_q.order_by(nullslast(inner.c.price_min.asc()), inner.c.date_start.asc())
        else:  # "date" (default) — soonest first
            rows_q = rows_q.order_by(inner.c.date_start.asc())
        rows = (await self.db.execute(rows_q.limit(limit).offset(offset))).all()
        now_msk = datetime.now(_MSK)
        items = [
            {
                "event_id": r.event_id,
                "code": event_code(r.display_no, r.venue_city),
                "title": r.title,
                "category": r.category,
                "date_start": r.date_start,
                "date_end": r.date_end,
                "price_min": float(r.price_min) if r.price_min is not None else None,
                "venue": r.venue_name,
                "open_now": _venue_open_now(r.venue_hours, now_msk),
                "lat": float(r.lat) if r.lat is not None else None,
                "lon": float(r.lon) if r.lon is not None else None,
                "primary_image_url": r.cached_image_url or r.primary_image_url,
            }
            for r in rows
        ]
        return {"items": items, "total": int(total)}

    async def _views_rank(self, id_col):
        """A CASE expr ranking events by their rec:views count (unviewed → 0), or None
        when there's no view data — backs the 'по популярности' sort."""
        client = _redis_client()
        if client is None:
            return None
        try:
            raw = await client.hgetall("rec:views")
        except Exception:  # pragma: no cover
            return None
        whens = []
        for k, v in raw.items():
            key = k.decode() if isinstance(k, bytes) else k
            val = v.decode() if isinstance(v, bytes) else v
            try:
                whens.append((id_col == UUID(str(key)), int(val)))
            except (ValueError, AttributeError):
                continue
        return case(*whens, else_=0) if whens else None

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

    # Lean projection shared by the code fast-path and the text CTE — exactly the fields
    # a search row needs to render AND to open the sheet with no extra round-trip.
    _SEARCH_COLS = (
        "e.event_id, e.display_no, e.canonical_title AS title, e.category, "
        "e.cached_image_url, e.primary_image_url, o.date_start, o.date_end, "
        "venues.name AS venue_name, venues.city AS venue_city, "
        "ST_Y(venues.geom::geometry) AS lat, ST_X(venues.geom::geometry) AS lon"
    )

    def _search_item(self, r, score: float) -> dict:
        return {
            "type": "event",
            "event_id": r["event_id"],
            "code": event_code(r["display_no"], r["venue_city"]),
            "title": r["title"],
            "category": r["category"],
            "date_start": r["date_start"],
            "date_end": r["date_end"],
            "price_min": None,
            "venue": r["venue_name"],
            "open_now": None,
            "lat": float(r["lat"]) if r["lat"] is not None else None,
            "lon": float(r["lon"]) if r["lon"] is not None else None,
            "primary_image_url": r["cached_image_url"] or r["primary_image_url"],
            "score": float(score),
        }

    async def search(self, q: str, city, limit: int) -> dict:
        """Typeahead search across event CODE, title and venue name, ranked. Fast at this
        scale (GIN trigram + a display_no probe); NEVER touches canonical_description
        (the old 130ms seq-scan). `city` is a CityConfig|None (resolved in the route)."""
        q = (q or "").strip()
        if not q:
            return {"items": []}
        # Keep ё as typed: folding it to е broke the prefix/contains ILIKE against the ё
        # in the data ("зеленый" stopped matching "Зелёный"). Trigram %> already tolerates
        # the one-char ё/е difference, so both spellings still match fuzzily.
        qn = q

        # Tier 0 — exact event code ("MSK-04PN"): a unique display_no probe. EXCLUSIVE —
        # a code is unambiguous, so don't pollute it with fuzzy text matches.
        if _looks_like_code(q):
            try:
                _city_code, no = parse_event_code(q)
            except Exception:
                no = None
            if no is not None:
                row = (await self.db.execute(
                    text(
                        f"SELECT {self._SEARCH_COLS} FROM events.events e "
                        "JOIN events.event_occurrences o ON o.event_id = e.event_id "
                        "JOIN events.venues ON venues.venue_id = o.venue_id "
                        "WHERE e.status = 'active' AND e.display_no = :no "
                        "ORDER BY (o.date_start < now()) ASC, o.date_start ASC LIMIT 1"
                    ),
                    {"no": no},
                )).mappings().first()
                if row:
                    return {"items": [self._search_item(row, 1000.0)]}

        if len(qn) < 2:
            return {"items": []}

        # Also search the OPPOSITE-script transliteration (latin↔cyrillic) so "bolshoi"
        # finds "Большой" and "стендап" finds "STANDUP". Gated by :has_qt when there's a
        # distinct variant.
        qt = _translit_variant(qn)
        has_qt = bool(qt) and qt != qn
        if not has_qt:
            qt = qn  # bound but switched off by :has_qt

        # Lower word_similarity threshold for short-prefix recall (default 0.6 is too
        # strict). SET LOCAL is transaction-scoped → safe behind the Odyssey pooler.
        await self.db.execute(text("SET LOCAL pg_trgm.word_similarity_threshold = 0.3"))
        # Match ё-INSENSITIVELY: both the column and the query are folded via
        # translate(lower(x), 'ё', 'е'), so "зеленый" finds "Зелёный" and vice-versa.
        # The functional GIN indexes (migration 0012) are on the SAME expression, so
        # prefix (LIKE) + fuzzy (%>) stay index-driven. LIKE metacharacters escaped.
        esc = str.maketrans({"%": r"\%", "_": r"\_", "\\": "\\\\"})
        qf, qtf = qn.lower().replace("ё", "е"), qt.lower().replace("ё", "е")
        qflike, qtflike = qf.translate(esc), qtf.translate(esc)
        region = _region_sql(city)
        ft = "translate(lower(e.canonical_title), 'ё', 'е')"  # folded title (matches the index)
        fv = "translate(lower(venues.name), 'ё', 'е')"  # folded venue name
        # GIN-DRIVEN candidate gathering FIRST (folded title + venue trgm), THEN join for
        # the soonest in-region occurrence — keeps the candidate set small vs a naive
        # single join. Each field is matched against BOTH the query and its translit.
        sql = text(
            "WITH cand AS ("
            "  SELECT e.event_id, GREATEST("
            f"      CASE WHEN {ft} LIKE :qflike || '%' ESCAPE '\\' THEN 200 "
            f"           WHEN {ft} LIKE '%' || :qflike || '%' ESCAPE '\\' THEN 100 ELSE 0 END, "
            f"      CASE WHEN char_length(:qf) >= 3 THEN (word_similarity(:qf, {ft}) * 100)::int ELSE 0 END, "
            f"      CASE WHEN :has_qt AND {ft} LIKE :qtflike || '%' ESCAPE '\\' THEN 190 "
            f"           WHEN :has_qt AND {ft} LIKE '%' || :qtflike || '%' ESCAPE '\\' THEN 95 ELSE 0 END, "
            f"      CASE WHEN :has_qt AND char_length(:qtf) >= 3 THEN (word_similarity(:qtf, {ft}) * 100)::int ELSE 0 END"
            "    ) AS score "
            "  FROM events.events e "
            "  WHERE e.status = 'active' AND ("
            f"      {ft} LIKE :qflike || '%' ESCAPE '\\' "
            f"      OR {ft} LIKE '%' || :qflike || '%' ESCAPE '\\' "
            f"      OR (char_length(:qf) >= 3 AND {ft} %> :qf) "
            f"      OR (:has_qt AND ({ft} LIKE :qtflike || '%' ESCAPE '\\' "
            f"                       OR {ft} LIKE '%' || :qtflike || '%' ESCAPE '\\' "
            f"                       OR (char_length(:qtf) >= 3 AND {ft} %> :qtf))) ) "
            "  UNION ALL "
            "  SELECT o.event_id, GREATEST("
            f"      CASE WHEN {fv} LIKE :qflike || '%' ESCAPE '\\' THEN 120 ELSE 0 END, "
            f"      CASE WHEN char_length(:qf) >= 3 AND {fv} %> :qf THEN (word_similarity(:qf, {fv}) * 130)::int ELSE 0 END, "
            f"      CASE WHEN :has_qt AND {fv} LIKE :qtflike || '%' ESCAPE '\\' THEN 118 ELSE 0 END, "
            f"      CASE WHEN :has_qt AND char_length(:qtf) >= 3 AND {fv} %> :qtf THEN (word_similarity(:qtf, {fv}) * 128)::int ELSE 0 END"
            "    ) AS score "
            "  FROM events.venues "
            "  JOIN events.event_occurrences o ON o.venue_id = venues.venue_id "
            f"  WHERE {fv} LIKE :qflike || '%' ESCAPE '\\' "
            f"        OR (char_length(:qf) >= 3 AND {fv} %> :qf) "
            f"        OR (:has_qt AND ({fv} LIKE :qtflike || '%' ESCAPE '\\' "
            f"                         OR (char_length(:qtf) >= 3 AND {fv} %> :qtf))) "
            "), best AS (SELECT event_id, max(score) AS score FROM cand GROUP BY event_id HAVING max(score) > 0), "
            "rows AS ("
            f"  SELECT DISTINCT ON (e.event_id) {self._SEARCH_COLS}, e.popularity_score, b.score "
            "  FROM best b "
            "  JOIN events.events e ON e.event_id = b.event_id "
            "  JOIN events.event_occurrences o ON o.event_id = e.event_id "
            "  JOIN events.venues ON venues.venue_id = o.venue_id "
            "  WHERE venues.name IS DISTINCT FROM :placeholder "
            "    AND coalesce(o.date_end, o.date_start) >= date_trunc('day', now()) "
            f"   AND {region} "
            "  ORDER BY e.event_id, (o.date_start < now()) ASC, o.date_start ASC"
            ") SELECT * FROM rows "
            "ORDER BY score DESC, popularity_score DESC NULLS LAST, date_start ASC LIMIT :lim"
        )
        rows = (await self.db.execute(
            sql,
            {"qf": qf, "qflike": qflike, "qtf": qtf, "qtflike": qtflike, "has_qt": has_qt,
             "lim": limit, "placeholder": _PLACEHOLDER_VENUE},
        )).mappings().all()
        return {"items": [self._search_item(r, float(r["score"])) for r in rows]}
