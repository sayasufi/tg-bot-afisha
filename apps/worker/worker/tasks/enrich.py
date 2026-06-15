import asyncio
import json
import math
import time

from sqlalchemy import func, text

from core.categorization import map_source_category
from core.cities import city_for_source_config
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

            venue_name = (candidate.venue or "").strip() or "Unknown venue"
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
                # 1) Source address: geocode it (street/house level).
                if address:
                    geo = await geocoder.geocode(address, city_hint=city)

                # 2) Local venue cache: venue + city -> known address/coords.
                if not geo and not address and venue_name != "Unknown venue":
                    cached_venue = await find_cached_venue(db, venue_name, city, country)
                    if cached_venue:
                        venue = cached_venue
                        address = cached_venue.address

                # 3) OSM-first fallback for missing address.
                if not geo and venue is None and not address and venue_name != "Unknown venue":
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
            if category and category != "other":
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


def _resolve_venue_hours_impl():
    """Resolve opening hours for venues that don't have them yet, via Yandex
    Maps (source-agnostic, by name + coords). Cached in `venues.hours_json` so we
    hit Yandex AT MOST ONCE per venue — venues we couldn't resolve are stamped
    with {} so they aren't re-queried. Small batch per run; new venues fill in
    over the next cycles."""
    db = SessionLocal()
    scraper = YandexMapsScraper()
    city = get_settings().default_city or "Москва"
    try:
        rows = db.execute(
            text(
                "SELECT venue_id, name, address, ST_Y(geom::geometry) AS lat, ST_X(geom::geometry) AS lon "
                "FROM events.venues WHERE geom IS NOT NULL AND name <> '' AND hours_json IS NULL "
                "ORDER BY venue_id LIMIT 15"
            )
        ).all()
        stored = 0
        for vid, name, address, lat, lon in rows:
            # name + address disambiguates same-named venues across the city.
            query = f"{name}, {address}".strip().strip(",").strip() if address else name
            try:
                res = asyncio.run(scraper.fetch_hours(query, city))
            except Exception:
                res = None
            hours: dict = {}  # default: "checked, nothing usable" → never re-queried
            if res and res.get("hours"):
                coords = res.get("coords")
                if not (coords and lat is not None and lon is not None and _dist_m((lat, lon), coords) > 1500):
                    hours = res["hours"]
                    stored += 1
            db.execute(
                text("UPDATE events.venues SET hours_json = CAST(:h AS JSON) WHERE venue_id = :v"),
                {"h": json.dumps(hours, ensure_ascii=False), "v": vid},
            )
            db.commit()
            time.sleep(1.2)
        return {"checked": len(rows), "stored": stored}
    except Exception:
        raise
    finally:
        db.close()
