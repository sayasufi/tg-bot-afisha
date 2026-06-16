import asyncio
import json
import math
import re
import time

from sqlalchemy import func, text

from core.categorization import map_source_category
from core.cities import DEFAULT_CITY, city_by_name, city_for_source_config
from core.config.settings import get_settings
from core.db.repositories.ingestion import (
    find_cached_venue,
    get_candidate,
    get_raw,
    get_venue,
    get_or_create_venue,
    unresolved_venue_ids,
    unresolved_candidate_ids,
)
from core.db.session import SessionLocal, WorkerAsyncSessionLocal
from pipeline.geocoding.providers.yandex_maps import YandexMapsScraper
from pipeline.geocoding.service import GeocodingService
from pipeline.llm.service import LLMService


_UNKNOWN_VENUE = "Unknown venue"  # placeholder when a source gives no venue name


def _is_city_level_only(address: str, city: str, country: str) -> bool:
    """True if the address has no street-level info — just the city and/or country
    ("Москва", "Россия, Москва"). Geocoding such a string only ever returns the city
    CENTROID, which dumps every venue-less event onto one fake pin in the centre (the
    "Unknown venue on Red Square" cluster). We skip it and leave the venue
    locationless instead, so it isn't shown at a wrong place."""
    a = (address or "").strip().lower()
    if not a:
        return True
    if any(ch.isdigit() for ch in a):
        return False  # a house/street number → real street-level address
    generic = {city.strip().lower(), country.strip().lower(),
               "россия", "москва", "russia", "moscow", "рф", "г"}
    toks = [t for t in re.split(r"[\s,.;]+", a) if t]
    return bool(toks) and all(t in generic for t in toks)


def _coords_sane(lat: float, lon: float) -> tuple[float, float] | None:
    """Validate source coordinates as plausible for Russia (lat 41..82, lon 19..180).

    Some sources TRANSPOSE lat/lon for ad-hoc places — Yandex Afisha does this for
    certain excursion/quest meeting points — which lands the event in the Caspian
    (~Iran). If the values are swapped, swap them back. Garbage like (0, 0) → None,
    so enrich geocodes the text address instead.
    """

    def ok(la: float, lo: float) -> bool:
        return 41.0 <= la <= 82.0 and 19.0 <= lo <= 180.0

    if ok(lat, lon):
        return (lat, lon)
    if ok(lon, lat):
        return (lon, lat)
    return None


def _source_coords(payload: dict | None) -> tuple[float, float] | None:
    """Exact venue coordinates supplied by the source (e.g. KudaGo place.coords).

    Far more accurate than re-geocoding the text address, which often resolves only
    to the street centroid (events landing 'in the middle of the road') or, worse,
    to a wrong city entirely. Coordinates are sanity-checked (and de-transposed) so
    a source's swapped lat/lon doesn't drop the pin in the wrong country.
    """
    if not isinstance(payload, dict):
        return None
    place = payload.get("place")
    if isinstance(place, dict):
        coords = place.get("coords")
        if isinstance(coords, dict):
            lat, lon = coords.get("lat"), coords.get("lon")
            if isinstance(lat, (int, float)) and isinstance(lon, (int, float)):
                return _coords_sane(float(lat), float(lon))
    return None


async def _enrich_impl() -> dict:
    geocoder = GeocodingService()
    llm = LLMService()
    async with WorkerAsyncSessionLocal() as db:
        ids = await unresolved_candidate_ids(db)
        enriched = 0
        for candidate_id in ids:
            candidate = await get_candidate(db, candidate_id)
            if not candidate:
                continue

            venue_name = (candidate.venue or "").strip() or _UNKNOWN_VENUE
            address = (candidate.address or "").strip()
            geo = None
            venue = None
            lat = lon = None
            provider = ""
            confidence = 0.0

            raw = await get_raw(db, candidate.raw_id)
            # City comes from the event's source (multi-city), not a global default.
            city_cfg = city_for_source_config(raw.source.config_json if raw and raw.source else None)
            city = city_cfg.name
            country = city_cfg.country
            src = _source_coords(raw.raw_payload_json if raw else None)

            if src:
                # 0) Exact coordinates from the source — most accurate, no geocoding.
                lat, lon = src
                provider, confidence = "source", 0.95
            else:
                # 1) Source address: geocode it (street/house level) — but NOT a
                # city/country-only address, which only yields the city centroid.
                if address and not _is_city_level_only(address, city, country):
                    geo = await geocoder.geocode(address, city_hint=city)

                # 2) Local venue cache: venue + city -> known address/coords.
                if not geo and not address and venue_name != _UNKNOWN_VENUE:
                    cached_venue = await find_cached_venue(db, venue_name, city, country)
                    if cached_venue:
                        venue = cached_venue
                        address = cached_venue.address

                # 3) OSM-first fallback for missing address.
                if not geo and venue is None and not address and venue_name != _UNKNOWN_VENUE:
                    geo = await geocoder.geocode_venue_osm_first(venue_name, city_hint=city)
                    if geo and geo.normalized_address:
                        address = geo.normalized_address

                if geo:
                    lat, lon, provider, confidence = geo.lat, geo.lon, geo.provider, geo.confidence

            if venue is None:
                venue = await get_or_create_venue(
                    db,
                    name=venue_name,
                    address=address,
                    city=city,
                    country=country,
                    lat=lat,
                    lon=lon,
                    provider=provider,
                    confidence=confidence,
                )
            candidate.venue_id = venue.venue_id
            # Category: trust the structured source's own label first (Yandex
            # type / KudaGo category), since the LLM over-fires 'lecture' on any
            # mention of a master-class. Only ask the LLM when the source gave
            # nothing usable (untyped events, Telegram free text) — which also
            # skips the ~20s LLM round-trip for the common, well-typed case.
            source_name = raw.source.name if raw and raw.source else ""
            category = map_source_category(candidate.tags_json, source_name)
            if category is None:
                classify = await llm.classify(candidate.title, candidate.description, candidate.tags_json)
                category = classify.category
                candidate.tags_json = list(set(candidate.tags_json + classify.tags))
            # Tag the resolved category — INCLUDING "other" — so dedup treats the
            # candidate as already classified and doesn't pay for a second LLM
            # classify of the same event.
            if category:
                candidate.tags_json.append(f"category:{category}")
            db.add(candidate)
            db.add(venue)
            await db.commit()
            enriched += 1
        return {"enriched": enriched}


async def _backfill_venues_osm_impl() -> dict:
    settings = get_settings()
    geocoder = GeocodingService()
    async with WorkerAsyncSessionLocal() as db:
        ids = await unresolved_venue_ids(db, limit=200)
        updated = 0
        for venue_id in ids:
            venue = await get_venue(db, venue_id)
            if not venue:
                continue
            if venue.name == _UNKNOWN_VENUE:
                continue  # placeholder — geocoding it only lands on the city centroid
            if venue.geom is not None and (venue.address or "").strip():
                continue
            geo = await geocoder.geocode_venue_osm_first(venue.name, city_hint=venue.city or settings.default_city)
            if not geo:
                continue
            if not (venue.address or "").strip() and geo.normalized_address:
                venue.address = geo.normalized_address
            venue.geocode_provider = geo.provider
            venue.geocode_confidence = geo.confidence
            venue.city = venue.city or settings.default_city
            venue.country = venue.country or settings.default_country
            if venue.geom is None:
                venue.geom = func.ST_SetSRID(func.ST_MakePoint(geo.lon, geo.lat), 4326)
            db.add(venue)
            await db.commit()
            updated += 1
        return {"updated": updated}


def _dist_m(a: tuple[float, float], b: tuple[float, float]) -> float:
    R = 6371000
    dlat = math.radians(b[0] - a[0])
    dlon = math.radians(b[1] - a[1])
    h = math.sin(dlat / 2) ** 2 + math.cos(math.radians(a[0])) * math.cos(math.radians(b[0])) * math.sin(dlon / 2) ** 2
    return 2 * R * math.asin(math.sqrt(h))


def _is_round_clock_day(d) -> bool:
    if not (isinstance(d, list) and len(d) == 1 and isinstance(d[0], list) and len(d[0]) == 2):
        return False
    a, b = d[0]
    return a == b or (a == "00:00" and b in ("24:00", "00:00"))


def _is_territory_week(week) -> bool:
    """Every day round-the-clock → the scraper matched an always-open TERRITORY (a
    park, an embankment) or a 24/7 building that shares the venue's name, NOT the
    event's hall. A real event venue is ~never genuinely 24/7, so this is garbage."""
    return isinstance(week, list) and len(week) == 7 and all(_is_round_clock_day(d) for d in week)


def _reverse_place(lat, lon) -> dict | None:
    """Offline coords → {city, state, country_code, …} via reverse_geocode (a bundled
    GeoNames dataset, no network). Gives the city / oblast / country for ANY point —
    the seam that makes the geo logic work for every city, not just Moscow."""
    if lat is None or lon is None:
        return None
    try:
        import reverse_geocode
        return reverse_geocode.get((float(lat), float(lon)))
    except Exception:
        return None


def _match_hours(res, lat, lon, city_center, country):
    """(hours, relocate_to). ``hours`` = a real weekly schedule (not an all-week 24/7
    territory) or None. ``relocate_to`` = the matched org's coords when it's clearly
    the venue but the geocoder mis-pinned it near the FEED CITY — the real org sits
    materially farther from the city centre and reverse-geocodes to the SAME country.
    We then fix its coords. City-agnostic: anchored on the venue's OWN city centre
    (``city_center``) and validated by reverse-geocode, so it works for any city. The
    farther-from-centre + same-country guards mean a correctly placed venue is never
    dragged onto a city namesake or a foreign one (the prior re-geocode incident)."""
    if not res or not isinstance(res.get("hours"), dict):
        return None, None
    week = res["hours"].get("week")
    if not (isinstance(week, list) and len(week) == 7) or _is_territory_week(week):
        return None, None
    hours = res["hours"]
    coords = res.get("coords")
    if coords and city_center and _dist_m(coords, city_center) < 600:
        coords = None  # the scraper returned the city centre itself → a non-answer
    if not coords or lat is None or lon is None or not city_center:
        return hours, None  # nothing to compare → accept the hours, don't move
    if _dist_m((lat, lon), coords) <= 1500:
        return hours, None  # match is at the venue → accept, no move
    place = _reverse_place(coords[0], coords[1])
    if not place or (country and place.get("country_code") and place["country_code"] != country):
        return None, None  # far + foreign / unknown → wrong business, drop
    if _dist_m(city_center, coords) - _dist_m(city_center, (lat, lon)) > 20000:
        return hours, (float(coords[0]), float(coords[1]))  # real org ≥20 km farther out → fix pin
    return None, None  # far but toward the city → likely a namesake, drop


def _resolve_hours_for(scraper, name, address, lat, lon, ev_title, city_hint, city_center, country):
    """Best real weekly hours for a venue + an optional coords fix. Tries the venue
    name (+address), then — if that only yields a 24/7 territory / wrong business —
    RETRIES with the event title prepended, which pulls the specific hall/museum.
    Returns (hours_dict_or_{}, relocate_to_or_None)."""
    candidates: list[str] = []
    if address:
        candidates.append(f"{name}, {address}".strip().strip(",").strip())
    candidates.append(name)
    if ev_title and ev_title.strip():
        candidates.append(f"{ev_title.strip()} {name}".strip())
    seen: set[str] = set()
    for q in candidates:
        if not q or q in seen:
            continue
        seen.add(q)
        try:
            res = asyncio.run(scraper.fetch_hours(q, city_hint))
        except Exception:
            res = None
        hours, relocate = _match_hours(res, lat, lon, city_center, country)
        if hours:
            return hours, relocate
        time.sleep(0.8)  # polite between tries
    return {}, None  # "checked, nothing usable" → stamped so we don't re-query


# Process never-resolved venues (hours_json IS NULL) AND re-check stale EMPTY ones
# ({} older than the staleness window) — so an improved resolver, a venue that
# gained hours, or a transient Yandex failure all self-heal without manual work.
# Never-checked first, then oldest. Venues WITH real hours are left alone.
_VENUE_HOURS_QUERY = (
    "SELECT v.venue_id, v.name, v.address, ST_Y(v.geom::geometry) AS lat, ST_X(v.geom::geometry) AS lon, v.city, "
    "(SELECT e.canonical_title FROM events.event_occurrences o JOIN events.events e ON e.event_id = o.event_id "
    " WHERE o.venue_id = v.venue_id AND e.status = 'active' "
    " ORDER BY e.popularity_score DESC NULLS LAST, o.date_start LIMIT 1) AS ev_title "
    "FROM events.venues v WHERE v.geom IS NOT NULL AND v.name <> '' AND ("
    "  v.hours_json IS NULL"
    "  OR (v.hours_json::text = '{}' AND (v.hours_checked_at IS NULL OR v.hours_checked_at < now() - interval '30 days'))"
    ") ORDER BY v.hours_checked_at ASC NULLS FIRST, v.venue_id LIMIT :lim"
)


def _resolve_venue_hours_impl(limit: int = 15):
    """Resolve opening hours for venues that don't have them yet, via Yandex Maps
    (source-agnostic, by name + coords + a representative event title). Cached in
    `venues.hours_json` so we hit Yandex AT MOST ONCE per venue — venues we couldn't
    resolve are stamped {} so they aren't re-queried. All-week-24/7 is rejected as a
    territory match and retried with the event title to find the real hall."""
    db = SessionLocal()
    scraper = YandexMapsScraper()
    try:
        rows = db.execute(text(_VENUE_HOURS_QUERY), {"lim": limit}).all()
        stored = relocated = 0
        for vid, name, address, lat, lon, vcity, ev_title in rows:
            # Per-venue city (NOT a global "Москва") — works for any city: the search
            # hint, the centre the relocation guard anchors on, and the country.
            cc = city_by_name(vcity) or DEFAULT_CITY
            hours, relocate = _resolve_hours_for(
                scraper, name, address, lat, lon, ev_title, vcity or cc.name, cc.center, cc.country
            )
            if hours:
                stored += 1
            if relocate:
                # Fix an oblast venue the geocoder mis-pinned near Moscow, using the
                # matched org's real coordinates (so it lands at its true place AND
                # its hours stop being rejected by the distance guard next time).
                db.execute(
                    text("UPDATE events.venues SET geom = ST_SetSRID(ST_MakePoint(:lon, :lat), 4326)::geography, "
                         "geocode_provider = 'yandex_hours', geocode_confidence = 0.8 WHERE venue_id = :v"),
                    {"lat": relocate[0], "lon": relocate[1], "v": vid},
                )
                relocated += 1
            db.execute(
                text("UPDATE events.venues SET hours_json = CAST(:h AS JSON), hours_checked_at = now() WHERE venue_id = :v"),
                {"h": json.dumps(hours, ensure_ascii=False), "v": vid},
            )
            db.commit()
            time.sleep(1.0)
        return {"checked": len(rows), "stored": stored, "relocated": relocated}
    except Exception:
        raise
    finally:
        db.close()
