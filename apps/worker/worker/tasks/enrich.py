import asyncio

from sqlalchemy import func

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
from core.db.session import SessionLocal
from pipeline.geocoding.service import GeocodingService
from pipeline.llm.service import LLMService

from apps.worker.worker.celery_app import celery_app


def _source_coords(payload: dict | None) -> tuple[float, float] | None:
    """Exact venue coordinates supplied by the source (e.g. KudaGo place.coords).

    Far more accurate than re-geocoding the text address, which often resolves only
    to the street centroid (events landing 'in the middle of the road') or, worse,
    to a wrong city entirely.
    """
    if not isinstance(payload, dict):
        return None
    place = payload.get("place")
    if isinstance(place, dict):
        coords = place.get("coords")
        if isinstance(coords, dict):
            lat, lon = coords.get("lat"), coords.get("lon")
            if isinstance(lat, (int, float)) and isinstance(lon, (int, float)):
                return float(lat), float(lon)
    return None


@celery_app.task(bind=True, max_retries=3)
def enrich_candidates(self):
    db = SessionLocal()
    settings = get_settings()
    geocoder = GeocodingService()
    llm = LLMService()
    try:
        ids = unresolved_candidate_ids(db)
        enriched = 0
        for candidate_id in ids:
            candidate = get_candidate(db, candidate_id)
            if not candidate:
                continue

            venue_name = (candidate.venue or "").strip() or "Unknown venue"
            city = settings.default_city
            country = settings.default_country
            address = (candidate.address or "").strip()
            geo = None
            venue = None
            lat = lon = None
            provider = ""
            confidence = 0.0

            raw = get_raw(db, candidate.raw_id)
            src = _source_coords(raw.raw_payload_json if raw else None)

            if src:
                # 0) Exact coordinates from the source — most accurate, no geocoding.
                lat, lon = src
                provider, confidence = "source", 0.95
            else:
                # 1) Source address: geocode it (street/house level).
                if address:
                    geo = asyncio.run(geocoder.geocode(address, city_hint=city))

                # 2) Local venue cache: venue + city -> known address/coords.
                if not geo and not address and venue_name != "Unknown venue":
                    cached_venue = find_cached_venue(db, venue_name, city, country)
                    if cached_venue:
                        venue = cached_venue
                        address = cached_venue.address

                # 3) OSM-first fallback for missing address.
                if not geo and venue is None and not address and venue_name != "Unknown venue":
                    geo = asyncio.run(geocoder.geocode_venue_osm_first(venue_name, city_hint=city))
                    if geo and geo.normalized_address:
                        address = geo.normalized_address

                if geo:
                    lat, lon, provider, confidence = geo.lat, geo.lon, geo.provider, geo.confidence

            if venue is None:
                venue = get_or_create_venue(
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
            # Pass the source's own categories/tags as hints so the LLM maps them
            # into our taxonomy instead of guessing from the venue name alone.
            classify = asyncio.run(llm.classify(candidate.title, candidate.description, candidate.tags_json))
            candidate.tags_json = list(set(candidate.tags_json + classify.tags))
            if classify.category and classify.category != "other":
                candidate.tags_json.append(f"category:{classify.category}")
            db.add(candidate)
            db.add(venue)
            db.commit()
            enriched += 1
        return {"enriched": enriched}
    except Exception as exc:
        raise self.retry(exc=exc)
    finally:
        db.close()


@celery_app.task(bind=True, max_retries=3)
def backfill_venues_osm(self):
    db = SessionLocal()
    settings = get_settings()
    geocoder = GeocodingService()
    try:
        ids = unresolved_venue_ids(db, limit=200)
        updated = 0
        for venue_id in ids:
            venue = get_venue(db, venue_id)
            if not venue:
                continue
            if venue.geom is not None and (venue.address or "").strip():
                continue
            geo = asyncio.run(geocoder.geocode_venue_osm_first(venue.name, city_hint=venue.city or settings.default_city))
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
            db.commit()
            updated += 1
        return {"updated": updated}
    except Exception as exc:
        raise self.retry(exc=exc)
    finally:
        db.close()
