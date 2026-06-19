"""Recommendation engine for the «Рекомендации» feed.

A hybrid recommender over one candidate pool, sliced into themed rails:
  • PERSONALISATION — a graded category affinity learned from BOTH explicit
    favourites and the events you actually open (implicit behavioural feedback the
    client sends back). The more you open concerts, the more concerts you get.
  • CONTENT — proximity, time-to-event / live-now, freshness, listing quality.
  • CONTEXT — time of day (evening gigs vs daytime shows).
  • ENGAGEMENT — a live view-count we collect ourselves (no fake popularity).
  • DIVERSITY — «Для тебя» is capped per category AND per venue so it reads as a
    hand-picked cross-section; an «Откройте новое» rail fights the filter bubble.

The weights below are the tunable "model"; every feature is independent and easy
to extend (learned weights / collaborative signal later).
"""
import asyncio
import math
import time
from collections import Counter
from datetime import datetime, timedelta, timezone

from geoalchemy2 import Geometry
from sqlalchemy import cast, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.app.services.events_service import _venue_open_now
from core.codes import event_code
from core.db.models import Event, EventOccurrence, Venue
from core.redis import get_redis

_MSK = timezone(timedelta(hours=3))
_POOL_CAP = 2000  # soonest-upcoming events scored into the base pool (was 6000). The rails are
# soon-biased, so the soonest ~2000 cover the visible feed while keeping the per-request
# re-rank cheap; the base is cached, so this also bounds the once-per-window recompute.
_PER_RAIL = 12
_MIN_RAIL = 4  # themed rails with fewer items are dropped (avoid sparse noise)
_MAX_RAILS = 7  # hard cap so the feed is a few strong rails, not a wall of relabelled lists
_NEAR_KM = 8.0
_RECENT_CAP = 60  # max recent opens the client may send (behavioural profile)
_VIEWS_KEY = "rec:views"
_INTENT_KEY = "intent:event"  # higher-value actions (route/click/share)
_INTENT_W = 4  # one intent hit ≈ this many opens when blended into popularity

# The expensive part of a feed — loading the city pool and scoring every event's
# NON-PERSONAL features (time-window/soon, live-now, popularity, quality, freshness,
# open-now) — is identical for every user in a short window. So it's computed once per
# (city, ~6h context) and cached IN-PROCESS per worker for _BASE_TTL seconds; each request
# then only applies the cheap per-user delta (category affinity + proximity) and builds the
# rails. This turns a full re-score-on-every-request (the ~10 rps CPU wall measured under
# load) into a light re-rank, and — because a base HIT touches no DB at all — removes the
# 'idle in transaction' connection-hold that exhausted the pool. Per-worker duplication
# (each worker recomputes its own base) is negligible: one ~scoring pass per worker per
# _BASE_TTL, vs one per request before.
_BASE_TTL = 120.0
_base_cache: dict[str, tuple] = {}  # city_slug -> (monotonic_expiry, today, hour//6, base_entries)
_base_lock = asyncio.Lock()  # collapse a concurrent base recompute into one (per worker)

# Scoring weights — the "model". Tune here; features are independent.
_W = {
    "interest": 3.0,  # graded affinity: favourites + what you actually open
    "prox": 2.0,      # close to you (needs your location)
    "soon": 1.5,      # happening today / very soon
    "pop": 1.3,       # other people open it (live engagement)
    "context": 0.8,   # fits the time of day
    "quality": 0.7,   # has photo / price / venue — a complete listing
    "fresh": 0.6,     # recently added to the catalogue
    "free": 0.4,      # free entry
}

# Categories that play better in the evening vs the daytime (time-of-day context).
_EVENING = {"party", "concert", "standup", "cinema", "theatre"}
_DAYTIME = {"exhibition", "tour", "kids", "lecture", "quest"}

# Russian labels for category rails (kept in sync with the frontend taxonomy).
_CATEGORY_LABELS = {
    "concert": "Концерты", "theatre": "Театр", "exhibition": "Выставки", "cinema": "Кино",
    "standup": "Стендап", "festival": "Фестивали", "lecture": "Лекции", "tour": "Экскурсии",
    "party": "Вечеринки", "quest": "Квесты", "kids": "Детям", "other": "Другое",
}

# Editorial "Подборки" — slug-named, rule-based lenses over the same scored pool: a curated
# "guide to the city" shelf shown above the auto rails (kind=rule; pinned/editorial later).
_COLLECTIONS = [
    ("date", "Свидание", "вечер вдвоём"),
    ("free", "Бесплатно", "вход свободный"),
    ("last-chance", "Последний шанс", "скоро закроется"),
    ("fresh", "Новинки недели", "только что добавили"),
    ("kids", "С детьми", "куда сходить с ребёнком"),
]
_DATE_CATS = {"concert", "theatre", "cinema", "party", "standup"}

def _redis_client():
    # decode_responses=True: recommend stores/reads text counters (rec:views, rec:seen).
    return get_redis(decode=True)


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

    async def feed(self, lat, lon, interests, recent, per_rail: int = _PER_RAIL, city=None) -> dict:
        favs = {c for c in (interests or []) if c in _CATEGORY_LABELS}
        recent = [c for c in (recent or []) if c in _CATEGORY_LABELS][:_RECENT_CAP]
        affinity = self._affinity(favs, recent)
        now = datetime.now(timezone.utc)
        msk = now.astimezone(_MSK)
        today, hour = msk.date(), msk.hour

        # 1) Non-personal base score for the city, computed once per window and cached.
        base = await self._base_scored(now, today, hour, city)
        # 2) Cheap per-user re-rank (category affinity + proximity) — no DB, no re-scoring.
        scored = self._personalize(base, lat, lon, affinity)
        return {
            "collections": self._collections(scored, today, now, per_rail),
            "rails": self._build_rails(scored, today, lat is not None, affinity, per_rail),
            "total": len(scored),
        }

    async def collection(self, slug, lat, lon, interests, recent, city, limit, offset) -> dict:
        """Full, paginated list of ONE «Подборка» — the detail screen behind a grid tile. Uses
        the SAME cached scored pool as the feed, so the detail agrees with the shelf preview;
        returns the collection's true total (for «N событий») plus the requested page of items.
        Unknown slug → an empty collection (404-ish without leaking which slugs exist)."""
        meta = next((c for c in _COLLECTIONS if c[0] == slug), None)
        if meta is None:
            return {"key": f"collection:{slug}", "title": slug, "subtitle": None, "count": 0, "items": []}
        _, title, sub = meta
        favs = {c for c in (interests or []) if c in _CATEGORY_LABELS}
        recent = [c for c in (recent or []) if c in _CATEGORY_LABELS][:_RECENT_CAP]
        affinity = self._affinity(favs, recent)
        now = datetime.now(timezone.utc)
        msk = now.astimezone(_MSK)
        today, hour = msk.date(), msk.hour
        base = await self._base_scored(now, today, hour, city)
        scored = self._personalize(base, lat, lon, affinity)
        by_score = sorted(scored, key=lambda e: -e["score"])
        pred, _diverse = self._collection_rules(today, now)[slug]
        # The detail shows the FULL collection (no per-category diversity cap — that's only a
        # teaser device for the shelf preview), so the count and the list always agree.
        matching = [e for e in by_score if pred(e)]
        page = matching[offset : offset + limit]
        return {
            "key": f"collection:{slug}", "title": title, "subtitle": sub,
            "count": len(matching), "items": [self._item(e) for e in page],
        }

    @staticmethod
    def _collection_rules(today, now):
        """The «Подборки» predicate set — shared by the shelf (`_collections`) and the
        full-collection endpoint (`collection`) so they can never drift. slug -> (predicate
        over a scored entry, diverse-cap-the-preview?)."""
        week_ago = now - timedelta(days=7)
        soon = today + timedelta(days=3)

        def is_fresh(e) -> bool:
            cr = e["c"].get("created_at")
            if cr is None:
                return False
            if cr.tzinfo is None:
                cr = cr.replace(tzinfo=timezone.utc)
            return cr >= week_ago

        return {
            # "Свидание" — a varied evening-out cross-section (the score already favours evening).
            "date": (lambda e: e["c"]["category"] in _DATE_CATS, True),
            "free": (lambda e: e["free"], True),  # all free upcoming (the only free rail now)
            # "Последний шанс" — a MULTI-day run (ds<de) whose end is within 3 days, not every
            # single-session event happening today.
            "last-chance": (lambda e: e["ds"] < e["de"] and today <= e["de"] <= soon, False),
            "fresh": (is_fresh, False),
            "kids": (lambda e: e["c"]["category"] == "kids", True),
        }

    def _collections(self, scored, today, now, per_rail):
        """The «Подборки» shelf — rule-based editorial lenses over the scored pool. Each is a
        plain rail (reusing _diverse/_rail) carrying a `count` (the TRUE number of matching
        events, for the grid tile) plus a capped preview; independent of the auto-rail dedup/cap,
        so a collection can share an item with «Для тебя» (a different entry point, like «Рядом»).
        Sparse collections (< _MIN_RAIL) are dropped."""
        by_score = sorted(scored, key=lambda e: -e["score"])
        rules = self._collection_rules(today, now)
        out = []
        for slug, title, sub in _COLLECTIONS:
            pred, diverse = rules[slug]
            matching = [e for e in by_score if pred(e)]
            pool = self._diverse(matching, per_rail) if diverse else matching
            rail = self._rail(f"collection:{slug}", title, sub, pool, per_rail)
            if rail:
                rail["count"] = len(matching)  # true total for "N событий", not the capped preview
                out.append(rail)
        return out

    async def _base_scored(self, now: datetime, today, hour: int, city=None) -> list[dict]:
        """The shareable, non-personal scored pool for a city — every event's score
        WITHOUT the per-user interest/proximity terms (those are added per request in
        `_personalize`). Cached in-process per worker for `_BASE_TTL`s, keyed by city +
        date + 6h context bucket; recomputed under a lock so a concurrent miss does the
        pool query + scoring exactly once. A cache hit performs NO DB access."""
        slug = city.slug if city else "all"
        hour6 = hour // 6
        ent = _base_cache.get(slug)
        if ent and ent[0] > time.monotonic() and ent[1] == today and ent[2] == hour6:
            return ent[3]
        async with _base_lock:
            ent = _base_cache.get(slug)  # re-check: another coroutine may have refreshed it
            if ent and ent[0] > time.monotonic() and ent[1] == today and ent[2] == hour6:
                return ent[3]
            pool = await self._load_pool(now, city)
            views = await self._views()
            # Release the DB connection BEFORE the CPU-heavy scoring so it is not held
            # 'idle in transaction' across the O(n) Python pass (the pool-exhaustion 500s).
            await self.db.close()
            base = self._score_all(pool, now, today, hour, None, None, {}, views)
            _base_cache[slug] = (time.monotonic() + _BASE_TTL, today, hour6, base)
            return base

    @staticmethod
    def _personalize(base: list[dict], lat, lon, affinity: dict[str, float]) -> list[dict]:
        """Apply the per-user terms to a cached base: category affinity (interest) and
        proximity. Returns NEW entry dicts (the base is shared across requests/workers and
        must not be mutated). For an anonymous request (no affinity, no location) the base
        is returned as-is — `_build_rails` never mutates it."""
        located = lat is not None and lon is not None
        if not affinity and not located:
            return base
        wi, wp = _W["interest"], _W["prox"]
        out = []
        for e in base:
            c = e["c"]
            score = e["score"]
            if affinity:
                a = affinity.get(c["category"])
                if a:
                    score += wi * a
            dist_km = None
            if located and c["lat"] is not None and c["lon"] is not None:
                dist_km = _haversine_km(lat, lon, c["lat"], c["lon"])
                score += wp / (1.0 + dist_km / 2.0)
            out.append({**e, "score": score, "dist_km": dist_km})
        return out

    @staticmethod
    def _affinity(favs: set[str], recent: list[str]) -> dict[str, float]:
        """Graded category affinity: explicit favourites are strong (1.0); opened
        events add a behavioural boost proportional to how often you open them."""
        aff: dict[str, float] = {c: 1.0 for c in favs}
        if recent:
            counts = Counter(recent)
            top = max(counts.values())
            for c, n in counts.items():
                aff[c] = aff.get(c, 0.0) + 0.7 * (n / top)
        return aff

    @staticmethod
    def _context(category: str, hour: int) -> float:
        if hour >= 17 or hour <= 4:  # evening / night
            return 1.0 if category in _EVENING else 0.35
        return 1.0 if category in _DAYTIME else 0.5  # daytime

    async def _load_pool(self, now: datetime, city=None) -> list[dict]:
        from core.cities import region_predicate_sql

        floor = now.replace(hour=0, minute=0, second=0, microsecond=0)
        lat_col = func.ST_Y(cast(Venue.geom, Geometry)).label("lat")
        lon_col = func.ST_X(cast(Venue.geom, Geometry)).label("lon")
        # Scope to the city's region (centre ± region_radius), or OR over all active cities
        # when none given — the single shared region predicate the map/list/search use too.
        region = region_predicate_sql(city)
        # One row per event = its soonest upcoming occurrence (DISTINCT ON requires
        # the event_id lead in ORDER BY).
        inner = (
            select(
                Event.event_id, Event.display_no, Event.canonical_title.label("title"), Event.category,
                Event.created_at, Event.cached_image_url, Event.primary_image_url,
                EventOccurrence.date_start, EventOccurrence.date_end, EventOccurrence.price_min,
                Venue.name.label("venue"), Venue.city.label("city"), Venue.hours_json.label("venue_hours"), lat_col, lon_col,
            )
            .join(EventOccurrence, EventOccurrence.event_id == Event.event_id)
            .join(Venue, Venue.venue_id == EventOccurrence.venue_id)
            .where(Event.status == "active", Venue.geom.is_not(None))
            .where(text(region))
            .where(func.coalesce(EventOccurrence.date_end, EventOccurrence.date_start) >= floor)
            .distinct(Event.event_id)
            .order_by(Event.event_id, EventOccurrence.date_start.asc())
            .subquery()
        )
        # Then keep the SOONEST-happening events across the whole city — not a slice
        # ordered by event_id (UUID), which silently dropped half the calendar from
        # every rail. Clamp past starts to today so ongoing/permanent runs (old
        # date_start, far-future end) sort as "now", not ahead of upcoming events.
        stmt = select(inner).order_by(func.greatest(inner.c.date_start, floor).asc()).limit(_POOL_CAP)
        rows = (await self.db.execute(stmt)).mappings().all()
        return [dict(r) for r in rows]

    async def _views(self) -> dict[str, int]:
        """Effective popularity per event: rec:views (an open) BLENDED with intent:event
        (route/click/share — higher-value actions, see routes/intent.py), each intent hit
        weighted _INTENT_W opens. Best-effort — either hash may be absent."""
        client = _redis_client()
        if client is None:
            return {}
        try:
            pipe = client.pipeline()
            pipe.hgetall(_VIEWS_KEY)
            pipe.hgetall(_INTENT_KEY)
            views_raw, intent_raw = await pipe.execute()
            out: dict[str, int] = {k: int(v) for k, v in (views_raw or {}).items() if str(v).isdigit()}
            for k, v in (intent_raw or {}).items():
                if str(v).isdigit():
                    out[k] = out.get(k, 0) + _INTENT_W * int(v)
            return out
        except Exception:  # pragma: no cover
            return {}

    @staticmethod
    def _is_live(c: dict, now: datetime) -> bool:
        """"Можно успеть прямо сейчас" — mirrors the map's goNowState so the rail can't
        disagree with the pins. A TIMED event (real clock time, run ≤24h) is catchable
        only if it HASN'T started yet and starts within 3h (you can't catch a film that
        began). An ONGOING / all-day run is live only while within its run AND the venue
        is open RIGHT NOW (unknown hours → not live). The old check was date-range only,
        so it flagged closed museums and long-past sessions as 'live'."""
        s = c["date_start"]
        if s is None:
            return False
        e = c["date_end"]
        end = e if e is not None else s + timedelta(hours=3)
        s_msk = s.astimezone(_MSK)
        timed = (s_msk.hour != 0 or s_msk.minute != 0) and (end - s) <= timedelta(hours=24)
        if timed:
            secs = (s - now).total_seconds()
            return 0 < secs <= 3 * 3600  # not started yet, starts within 3 hours
        if s > now:
            return False  # ongoing run hasn't begun
        far_future = e is not None and e.year > now.year + 5  # open-ended sentinel
        if e is not None and not far_future and now > e:
            return False  # run already over
        return _venue_open_now(c["venue_hours"], now.astimezone(_MSK)) is True

    def _score_all(self, pool, now, today, hour, lat, lon, affinity, views):
        max_views = max((views.get(str(c["event_id"]), 0) for c in pool), default=0)
        pop_norm = math.log1p(max_views) or 1.0
        now_msk = now.astimezone(_MSK)
        out = []
        for c in pool:
            s, e = c["date_start"], c["date_end"]
            ds = s.astimezone(_MSK).date() if s else today
            de = e.astimezone(_MSK).date() if e else ds
            live = self._is_live(c, now)
            days = (ds - today).days

            soon = 1.0 if (live or days <= 0) else max(0.0, 1.0 - days / 14.0)
            dist_km = None
            if lat is not None and lon is not None and c["lat"] is not None and c["lon"] is not None:
                dist_km = _haversine_km(lat, lon, c["lat"], c["lon"])
            prox = 1.0 / (1.0 + dist_km / 2.0) if dist_km is not None else 0.0
            interest = affinity.get(c["category"], 0.0)
            context = self._context(c["category"], hour)
            price = c["price_min"]
            free = price is not None and float(price) == 0.0
            has_image = bool(c["cached_image_url"] or c["primary_image_url"])
            quality = 0.6 * has_image + 0.2 * (price is not None) + 0.2 * bool(c["venue"])
            v = views.get(str(c["event_id"]), 0)
            pop = math.log1p(v) / pop_norm if max_views > 0 else 0.0
            created = c["created_at"]
            if created is not None and created.tzinfo is None:
                created = created.replace(tzinfo=timezone.utc)
            age_days = (now - created).days if created else 30
            fresh = max(0.0, 1.0 - age_days / 14.0)

            score = (
                _W["interest"] * interest + _W["prox"] * prox + _W["soon"] * soon
                + _W["pop"] * pop + _W["context"] * context + _W["quality"] * quality
                + _W["fresh"] * fresh + _W["free"] * (1.0 if free else 0.0)
            )
            out.append({
                "c": c, "score": score, "dist_km": dist_km, "live": live,
                "ds": ds, "de": de, "free": free, "views": v,
                # Compact open-now (Moscow time) — the rails ship this, not the full
                # weekly schedule, matching the map payload (see events_service).
                "open_now": _venue_open_now(c["venue_hours"], now_msk),
            })
        return out

    def _item(self, e: dict) -> dict:
        c = e["c"]
        return {
            "event_id": c["event_id"], "code": event_code(c.get("display_no"), c.get("city")),
            "title": c["title"], "category": c["category"],
            "date_start": c["date_start"], "date_end": c["date_end"],
            "price_min": float(c["price_min"]) if c["price_min"] is not None else None,
            "venue": c["venue"], "open_now": e.get("open_now"), "lat": c["lat"], "lon": c["lon"],
            "primary_image_url": c["cached_image_url"] or c["primary_image_url"] or None,
            "distance_m": round(e["dist_km"] * 1000) if e["dist_km"] is not None else None,
        }

    def _rail(self, key, title, subtitle, entries, per_rail, *, min_items=_MIN_RAIL):
        items = [self._item(e) for e in entries[:per_rail]]
        if len(items) < min_items:
            return None
        return {"key": key, "title": title, "subtitle": subtitle, "items": items}

    @staticmethod
    def _diverse(entries, per_rail, cap_per_cat=3, cap_per_venue=2):
        """Varied pick: cap items per category AND per venue so a rail is a real
        cross-section, not 12 of the same thing at the same place. The single
        highest-scored event still leads. In a normal feed the caps leave plenty
        to fill the rail; an unusually homogeneous pool yields a shorter — but
        honestly diverse — rail instead of a wall of duplicates."""
        out, ccat, cven = [], {}, {}
        for e in entries:  # pre-sorted by score
            cat, ven = e["c"]["category"], e["c"]["venue"] or ""
            if ccat.get(cat, 0) >= cap_per_cat:
                continue
            if ven and cven.get(ven, 0) >= cap_per_venue:
                continue
            out.append(e)
            ccat[cat] = ccat.get(cat, 0) + 1
            if ven:
                cven[ven] = cven.get(ven, 0) + 1
            if len(out) >= per_rail:
                break
        return out

    def _build_rails(self, scored, today, has_loc, affinity, per_rail):
        by_score = sorted(scored, key=lambda e: -e["score"])
        rails = []
        seen: set = set()  # cross-rail dedup: an event shows in ONE rail, so each rail is
        # genuinely new content, not the same ~12 events relabelled. Rails are tried in
        # priority order; one renders only if it still adds ≥_MIN_RAIL UNSEEN events.

        def add(key, title, subtitle, entries, *, diverse=False, min_items=_MIN_RAIL, filter_seen=True):
            if len(rails) >= _MAX_RAILS:
                return
            # filter_seen=False lets a distinct-axis rail (e.g. "Рядом") show its TRUE best
            # even if an item also leads "Для тебя" — but it still marks them seen so the
            # big overlapping rails below don't repeat it.
            pool = [e for e in entries if e["c"]["event_id"] not in seen] if filter_seen else list(entries)
            if diverse:
                pool = self._diverse(pool, per_rail)
            rail = self._rail(key, title, subtitle, pool, per_rail, min_items=min_items)
            if rail:
                seen.update(it["event_id"] for it in rail["items"])
                rails.append(rail)

        # "Для тебя" — a VARIED personalised top (capped per category + venue). Claims
        # first; min 1 so it always leads. When the account is COLD (no affinity at all:
        # no picked interests, no favourites, no opens) the order is popularity-driven, so
        # label it honestly rather than pretending it's personal — the interest picker at
        # onboarding is what flips a new user out of this cold state.
        if affinity:
            add("for_you", "Для тебя", "Собрано лично для вас", by_score, diverse=True, min_items=1)
        else:
            add("for_you", "Популярное сейчас", "Начните отсюда — дальше подстроюсь под вас", by_score, diverse=True, min_items=1)

        # "Рядом" — closest to you. A spatial lens must show the actual nearest, so it is
        # NOT filtered by the seen-set (a 1-2 event overlap with "Для тебя" is fine); it
        # still marks its items seen so the rails below stay fresh.
        if has_loc:
            near = sorted([e for e in scored if e["dist_km"] is not None and e["dist_km"] <= _NEAR_KM], key=lambda e: e["dist_km"])
            add("near", "Рядом с вами", "В пешей доступности и около", near, filter_seen=False)

        # "Сегодня" — today's events (incl. ongoing covering today). The old standalone
        # "Идёт сейчас" rail was a strict subset of this AND every card already shows a
        # live badge, so it's dropped — it only padded the feed with repeats.
        add("today", "Сегодня", None, [e for e in by_score if e["live"] or (e["ds"] <= today <= e["de"])])

        # "На выходных" — the current-or-upcoming weekend as a contiguous Sat+Sun.
        wd = today.weekday()
        sat = today if wd == 5 else today - timedelta(days=1) if wd == 6 else today + timedelta(days=5 - wd)
        weekend = {sat, sat + timedelta(days=1)}
        add("weekend", "На выходных", None, [e for e in by_score if (e["ds"] in weekend) or (min(weekend) <= e["de"] and e["ds"] <= max(weekend))])

        # "Популярное" — most opened by others (live engagement).
        if any(e["views"] > 0 for e in scored):
            add("popular", "Популярное", "Чаще всего открывают", sorted([e for e in scored if e["views"] > 0], key=lambda e: -e["views"]))

        # ("Бесплатно" lives in the «Подборки» shelf now — no duplicate auto rail here.)

        # "Откройте новое" — strong events OUTSIDE any category you've engaged with.
        usual = set(affinity)
        if usual:
            add("explore", "Откройте новое", "Не из ваших привычных тем", [e for e in by_score if e["c"]["category"] not in usual], diverse=True)

        # Category rails — strongest-affinity categories first, then busiest; each only
        # if it still brings ≥_MIN_RAIL unseen events (and within the rail cap).
        counts = Counter(e["c"]["category"] for e in scored)
        busiest = [c for c in counts if c != "other"]
        ordered = sorted(busiest, key=lambda c: (-affinity.get(c, 0.0), -counts[c]))
        for cat in ordered:
            add(f"category:{cat}", _CATEGORY_LABELS.get(cat, cat), None, [e for e in by_score if e["c"]["category"] == cat])

        return rails

    async def log_view(self, event_id, user_id=None) -> None:
        client = _redis_client()
        if client is None:
            return
        exists = await self.db.scalar(
            select(Event.event_id).where(Event.event_id == event_id, Event.status == "active").limit(1)
        )
        if not exists:
            return
        try:
            if user_id is not None:
                # Count each user at most once per event per day, so a single
                # user can't inflate the popularity signal by reopening.
                seen_key = f"rec:seen:{event_id}"
                added = await client.sadd(seen_key, str(user_id))
                await client.expire(seen_key, 86400)
                if not added:
                    return
            await client.hincrby(_VIEWS_KEY, str(event_id), 1)
        except Exception:  # pragma: no cover
            pass
