"""Reindex active events into Meilisearch.

A denormalised mirror — one doc per active event at its soonest (future-first) occurrence, carrying
everything the typeahead must render + open the sheet (no DB round-trip on a hit). Full reindex each
run (cheap at this scale) via an atomic tmp-index swap, so the live index never goes empty. No-op when
search is disabled.
"""
import logging

from sqlalchemy import text

from core.codes import event_code
from core.config.settings import get_settings
from core.db.session import WorkerAsyncSessionLocal
from core.search.meili import MeiliClient
from core.matching.title_match import translit_tokens

logger = logging.getLogger(__name__)

# DISTINCT ON (event_id) + future-first ordering → the soonest upcoming (else soonest past) occurrence.
_SQL = text(
    "SELECT DISTINCT ON (e.event_id) "
    "  e.event_id, e.display_no, e.canonical_title AS title, e.category, "
    "  e.cached_image_url, e.primary_image_url, o.date_start, o.date_end, "
    "  venues.name AS venue_name, venues.city AS venue_city, "
    "  ST_Y(venues.geom::geometry) AS lat, ST_X(venues.geom::geometry) AS lon "
    "FROM events.events e "
    "JOIN events.event_occurrences o ON o.event_id = e.event_id "
    "JOIN events.venues ON venues.venue_id = o.venue_id "
    "WHERE e.status = 'active' "
    "ORDER BY e.event_id, (o.date_start < now()) ASC, o.date_start ASC"
)


def _doc(r) -> dict:
    title = r["title"] or ""
    lat, lon = r["lat"], r["lon"]
    ds, de = r["date_start"], r["date_end"]
    eid = str(r["event_id"])  # event_id is a UUID — Meili needs a string/int primary key
    doc = {
        "id": eid,
        "event_id": eid,
        "title": title,
        "title_translit": " ".join(translit_tokens(title)),  # latin query → cyrillic title
        "venue": r["venue_name"] or "",
        "code": event_code(r["display_no"], r["venue_city"]) if r["display_no"] is not None else "",
        "category": r["category"],
        "date_start": ds.isoformat() if ds else None,
        "date_end": de.isoformat() if de else None,
        "date_start_ts": int(ds.timestamp()) if ds else 0,
        "image": r["cached_image_url"] or r["primary_image_url"] or "",
        "lat": float(lat) if lat is not None else None,
        "lon": float(lon) if lon is not None else None,
        "status": "active",
    }
    if lat is not None and lon is not None:
        doc["_geo"] = {"lat": float(lat), "lng": float(lon)}  # Meili reserved field (note: "lng")
    return doc


async def _reindex_search_impl() -> dict:
    if not get_settings().meili_search_enabled:
        return {"skipped": "disabled"}
    async with WorkerAsyncSessionLocal() as db:
        rows = (await db.execute(_SQL)).mappings().all()
    docs = [_doc(r) for r in rows]
    n = await MeiliClient().reindex(docs)
    logger.info("search_reindex", extra={"indexed": n})
    return {"indexed": n}
