"""Recommendation engine for the «Рекомендации» feed.

A transparent, multi-signal scorer (the model's core — weights are named and
tunable, features are easy to extend) over a single candidate pool, sliced into
themed rails. Real signals only — there is no fake "popularity": the engagement
signal is live view-counts we collect ourselves (foundation for a proper model:
popularity now, collaborative/personalised later).

Pipeline: load pool once (active, in-region, geocoded, upcoming/ongoing) → score
each event → build rails by filtering/sorting the scored pool → cache briefly.
"""
import hashlib
import json
import math
from datetime import datetime, timedelta, timezone

import redis.asyncio as aioredis
from geoalchemy2 import Geometry
from sqlalchemy import cast, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from core.config.settings import get_settings
from core.db.models import Event, EventOccurrence, Venue

_MSK = timezone(timedelta(hours=3))
_POOL_CAP = 6000
_PER_RAIL = 12
_MIN_RAIL = 4  # themed rails with fewer items are dropped (avoid sparse noise)
_NEAR_KM = 8.0
_VIEWS_KEY = "rec:views"
_CACHE_PREFIX = "rec:feed:v1:"
_CACHE_TTL = 90

# Scoring weights — the "model". Tune here; features below are independent.
_W = {
    "interest": 3.0,   # event is in a category you favourite
    "prox": 2.0,       # close to you (needs your location)
    "soon": 1.5,       # happening today / very soon
    "pop": 1.5,        # other people opened it (live engagement)
    "image": 0.8,      # has a real photo (quality/eye-candy)
    "fresh": 0.7,      # recently added to the catalogue
    "free": 0.5,       # free entry
}

# Russian labels for category rails (kept in sync with the frontend taxonomy).
_CATEGORY_LABELS = {
    "concert": "Концерты", "theatre": "Театр", "exhibition": "Выставки", "cinema": "Кино",
    "standup": "Стендап", "festival": "Фестивали", "lecture": "Лекции", "tour": "Экскурсии",
    "party": "Вечеринки", "quest": "Квесты", "kids": "Детям", "other": "Другое",
}

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
        except Exception:  # pragma: no cover - best-effort
            _redis_off = True
            return None
    return _redis


def _haversine_km(a_lat: float, a_lon: float, b_lat: float, b_lon: float) -> float:
    r = 6371.0
    p1, p2 = math.radians(a_lat), math.radians(b_lat)
    dlat = math.radians(b_lat - a_lat)
    dlon = math.radians(b_lon - a_lon)
    h = math.sin(dlat / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlon / 2) ** 2
    return 2 * r * math.asin(math.sqrt(h))


class RecommendationService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def feed(
        self,
        lat: float | None,
        lon: float | None,
        interests: list[str] | None,
        per_rail: int = _PER_RAIL,
    ) -> dict:
        interests_set = {c for c in (interests or []) if c}
        now = datetime.now(timezone.utc)
        today = now.astimezone(_MSK).date()

        key = _CACHE_PREFIX + hashlib.sha256(
            json.dumps(
                [
                    round(lat, 2) if lat is not None else None,
                    round(lon, 2) if lon is not None else None,
                    sorted(interests_set),
                    today.isoformat(),
                ],
                sort_keys=True,
            ).encode()
        ).hexdigest()
        cached = await self._cache_get(key)
        if cached is not None:
            return cached

        pool = await self._load_pool(now)
        views = await self._views()
        scored = self._score_all(pool, now, today, lat, lon, interests_set, views)
        result = {"rails": self._build_rails(scored, today, lat is not None, interests_set, per_rail), "total": len(scored)}
        await self._cache_set(key, result)
        return result

    async def _load_pool(self, now: datetime) -> list[dict]:
        floor = now.replace(hour=0, minute=0, second=0, microsecond=0)
        lat_col = func.ST_Y(cast(Venue.geom, Geometry)).label("lat")
        lon_col = func.ST_X(cast(Venue.geom, Geometry)).label("lon")
        stmt = (
            select(
                Event.event_id, Event.canonical_title.label("title"), Event.category,
                Event.created_at, Event.cached_image_url, Event.primary_image_url,
                EventOccurrence.date_start, EventOccurrence.date_end, EventOccurrence.price_min,
                Venue.name.label("venue"), Venue.hours_json.label("venue_hours"), lat_col, lon_col,
            )
            .join(EventOccurrence, EventOccurrence.event_id == Event.event_id)
            .join(Venue, Venue.venue_id == EventOccurrence.venue_id)
            .where(Event.status == "active", Venue.geom.is_not(None))
            .where(text("ST_Intersects(venues.geom::geometry, ST_MakeEnvelope(30.0, 50.0, 45.0, 60.0, 4326))"))
            .where(func.coalesce(EventOccurrence.date_end, EventOccurrence.date_start) >= floor)
            .distinct(Event.event_id)
            .order_by(Event.event_id, EventOccurrence.date_start.asc())
            .limit(_POOL_CAP)
        )
        rows = (await self.db.execute(stmt)).mappings().all()
        return [dict(r) for r in rows]

    async def _views(self) -> dict[str, int]:
        client = _redis_client()
        if client is None:
            return {}
        try:
            raw = await client.hgetall(_VIEWS_KEY)
            return {k: int(v) for k, v in raw.items() if str(v).isdigit()}
        except Exception:  # pragma: no cover
            return {}

    @staticmethod
    def _is_live(c: dict, now: datetime) -> bool:
        s = c["date_start"]
        if s is None or s > now:
            return False
        e = c["date_end"] or (s + timedelta(hours=3))
        # Open-ended sentinel (>5y out) counts as ongoing.
        if e.year > now.year + 5:
            return True
        return now <= e

    def _score_all(self, pool, now, today, lat, lon, interests, views):
        max_views = max((views.get(str(c["event_id"]), 0) for c in pool), default=0)
        pop_norm = math.log1p(max_views) or 1.0
        out = []
        for c in pool:
            s = c["date_start"]
            e = c["date_end"]
            ds = s.astimezone(_MSK).date() if s else today
            de = e.astimezone(_MSK).date() if e else ds
            live = self._is_live(c, now)
            days = (ds - today).days
            ongoing = s is not None and s <= now and (e is None or e >= now)

            soon = 1.0 if (live or days <= 0) else max(0.0, 1.0 - days / 14.0)
            dist_km = None
            if lat is not None and lon is not None and c["lat"] is not None and c["lon"] is not None:
                dist_km = _haversine_km(lat, lon, c["lat"], c["lon"])
            prox = 1.0 / (1.0 + dist_km / 2.0) if dist_km is not None else 0.0
            interest = 1.0 if c["category"] in interests else 0.0
            price = c["price_min"]
            free = 1.0 if (price is not None and float(price) == 0.0) else 0.0
            has_image = bool(c["cached_image_url"] or c["primary_image_url"])
            image = 1.0 if has_image else 0.0
            v = views.get(str(c["event_id"]), 0)
            pop = math.log1p(v) / pop_norm if max_views > 0 else 0.0
            created = c["created_at"]
            age_days = (now - created).days if created else 30
            fresh = max(0.0, 1.0 - age_days / 14.0)

            score = (
                _W["interest"] * interest + _W["prox"] * prox + _W["soon"] * soon
                + _W["pop"] * pop + _W["image"] * image + _W["fresh"] * fresh + _W["free"] * free
            )
            out.append({
                "c": c, "score": score, "dist_km": dist_km, "live": live, "ongoing": ongoing,
                "ds": ds, "de": de, "days": days, "free": free > 0, "image": has_image, "views": v,
            })
        return out

    def _item(self, e: dict) -> dict:
        c = e["c"]
        return {
            "event_id": c["event_id"], "title": c["title"], "category": c["category"],
            "date_start": c["date_start"], "date_end": c["date_end"], "price_min": c["price_min"],
            "venue": c["venue"], "venue_hours": c["venue_hours"], "lat": c["lat"], "lon": c["lon"],
            "primary_image_url": c["cached_image_url"] or c["primary_image_url"] or None,
            "distance_m": round(e["dist_km"] * 1000) if e["dist_km"] is not None else None,
        }

    def _rail(self, key, title, subtitle, entries, per_rail, *, min_items=_MIN_RAIL):
        items = [self._item(e) for e in entries[:per_rail]]
        if len(items) < min_items:
            return None
        return {"key": key, "title": title, "subtitle": subtitle, "items": items}

    def _build_rails(self, scored, today, has_loc, interests, per_rail):
        by_score = sorted(scored, key=lambda e: -e["score"])
        rails = []

        # "Для тебя" — the personalised top of everything.
        foryou = self._rail("for_you", "Для тебя", "Подобрано для вас", by_score, per_rail, min_items=1)
        if foryou:
            rails.append(foryou)

        # "Идёт сейчас" — live right now.
        live = [e for e in by_score if e["live"]]
        rails.append(self._rail("live", "Идёт сейчас", "Можно пойти прямо сейчас", live, per_rail))

        # "Рядом" — closest to you.
        if has_loc:
            near = sorted([e for e in scored if e["dist_km"] is not None and e["dist_km"] <= _NEAR_KM], key=lambda e: e["dist_km"])
            rails.append(self._rail("near", "Рядом с вами", "В пешей доступности и около", near, per_rail))

        # "Сегодня" — today's events (incl. ongoing covering today).
        todays = [e for e in by_score if e["live"] or (e["ds"] <= today <= e["de"])]
        rails.append(self._rail("today", "Сегодня", None, todays, per_rail))

        # "На выходных" — the upcoming Saturday/Sunday.
        wd = today.weekday()
        weekend = {today + timedelta(days=(5 - wd) % 7), today + timedelta(days=(6 - wd) % 7)}
        wkd = [e for e in by_score if (e["ds"] in weekend) or (min(weekend) <= e["de"] and e["ds"] <= max(weekend))]
        rails.append(self._rail("weekend", "На выходных", None, wkd, per_rail))

        # "По интересам" — your favourite categories.
        if interests:
            byint = [e for e in by_score if e["c"]["category"] in interests]
            rails.append(self._rail("interests", "По вашим интересам", None, byint, per_rail))

        # "Популярное" — most opened by others (live engagement).
        if any(e["views"] > 0 for e in scored):
            popular = sorted([e for e in scored if e["views"] > 0], key=lambda e: -e["views"])
            rails.append(self._rail("popular", "Популярное", "Чаще всего открывают", popular, per_rail))

        # "Бесплатно".
        free = [e for e in by_score if e["free"]]
        rails.append(self._rail("free", "Бесплатно", None, free, per_rail))

        # A couple of category rails for browsing, busiest first (skip ones already
        # central to the feed via interests).
        counts: dict[str, int] = {}
        for e in scored:
            counts[e["c"]["category"]] = counts.get(e["c"]["category"], 0) + 1
        for cat, _ in sorted(counts.items(), key=lambda kv: -kv[1])[:3]:
            if cat in interests or cat == "other":
                continue
            cat_entries = [e for e in by_score if e["c"]["category"] == cat]
            rails.append(self._rail(f"category:{cat}", _CATEGORY_LABELS.get(cat, cat), None, cat_entries, per_rail))

        return [r for r in rails if r]

    async def log_view(self, event_id: str) -> None:
        client = _redis_client()
        if client is None:
            return
        try:
            await client.hincrby(_VIEWS_KEY, event_id, 1)
        except Exception:  # pragma: no cover
            pass

    async def _cache_get(self, key: str):
        client = _redis_client()
        if client is None:
            return None
        try:
            hit = await client.get(key)
            return json.loads(hit) if hit else None
        except Exception:  # pragma: no cover
            return None

    async def _cache_set(self, key: str, value: dict) -> None:
        client = _redis_client()
        if client is None:
            return
        try:
            await client.set(key, json.dumps(value, default=str), ex=_CACHE_TTL)
        except Exception:  # pragma: no cover
            pass
