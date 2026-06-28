"""Correct venue coordinates that came verbatim from a source feed and landed in the wrong spot.

ROOT CAUSE of "this venue shows in the wrong place": when an event source embeds a venue coordinate,
enrich trusts it as-is (``geocode_provider='source'``, confidence 0.95) and never geocodes the address.
Most source coords are fine, but some pin a venue ~100 m – 2 km off (e.g. НЭТ Волгоград sat past Аллея
Героев). This pass re-geocodes the ADDRESS house-precisely via Yandex and moves the pin there — BUT only
when an INDEPENDENT venue-name geocode agrees that the venue is really at that spot.

Why the agreement gate: a house-precise address geocode alone over-fires on large territories and
ambiguously-named places (a park's street entrance, one of several "Зелёный театр") where the source
coordinate may well be right. Requiring the address geocode and the venue-name geocode to land within
``_AGREE_M`` of each other — and both far from the stored source point — is what tells us the source pin
is genuinely wrong, not just that the address resolves to a different corner of a big venue.

Self-healing + cost-bounded: each ``source`` venue is reviewed ONCE, then MARKED — moved ones become
``geocode_fix``, reviewed-and-kept ones ``source_ok`` — so a re-run only pays for venues it hasn't seen.
The second (name) geocode runs ONLY for the few percent that the address flags as candidates. New
``source`` venues from later ingests are picked up on the next run. A venue the geocoder can't resolve at
all (transient miss / hard address) is LEFT as ``source`` to retry. Idempotent; safe on a schedule.

Only ``source`` venues are touched: ``yandex``/``yandex_maps``/``osm`` rows were already derived FROM the
address, so they're not the wrong-pin class. ``geocode_provider`` is informational — nothing filters on it.

Run:      docker compose -p tg-bot-afisha exec -T prefect-serve python -m pipeline.maintenance.venue_coords --limit 2500
Preview:  ... python -m pipeline.maintenance.venue_coords --dry-run --limit 120
"""
import asyncio
import math
import sys

from sqlalchemy import text

from core.db.session import WorkerAsyncSessionLocal
from pipeline.geocoding.service import GeocodingService

_MIN_SHIFT_M = 120          # stored 'source' point must be at least this far from the confirmed spot to move
_AGREE_M = 150              # address geocode & venue-name geocode within this of each other → they agree it's here
_SANITY_M = 30_000          # ...but never relocate a venue >30 km (a bad address parse landing in another city)
_HOUSE_PRECISION = {"exact", "number"}  # only act on Yandex house-level precision — minimises regressions
_COMMIT_EVERY = 50          # flush periodically so a long pass is resumable and a mid-run crash keeps progress

_MOVE_SQL = text(
    "UPDATE events.venues SET geom = ST_SetSRID(ST_MakePoint(:lon, :lat), 4326), "
    "geocode_provider = 'geocode_fix', geocode_confidence = :c, updated_at = now() WHERE venue_id = :v"
)
_KEEP_SQL = text(
    "UPDATE events.venues SET geocode_provider = 'source_ok', updated_at = now() WHERE venue_id = :v"
)
_SELECT_BASE = (
    "SELECT venue_id, name, address, city, ST_Y(geom::geometry) AS lat, ST_X(geom::geometry) AS lon "
    "FROM events.venues "
    "WHERE geocode_provider = 'source' AND coalesce(address, '') <> '' AND geom IS NOT NULL "
)
_FUTURE_CLAUSE = (
    "AND EXISTS (SELECT 1 FROM events.event_occurrences o "
    "WHERE o.venue_id = venues.venue_id AND o.date_start >= now()) "
)


def _dist_m(a: tuple[float, float], b: tuple[float, float]) -> float:
    R = 6371000.0
    dlat = math.radians(b[0] - a[0])
    dlon = math.radians(b[1] - a[1])
    s = math.sin(dlat / 2) ** 2 + math.cos(math.radians(a[0])) * math.cos(math.radians(b[0])) * math.sin(dlon / 2) ** 2
    return 2 * R * math.asin(min(1.0, math.sqrt(s)))


async def _safe_geocode(fn, query: str, city: str | None):
    if not query:
        return None
    try:
        return await fn(query, city_hint=city)
    except Exception:
        return None


async def correct_venue_coordinates(apply: bool = True, limit: int = 800, future_only: bool = True) -> dict:
    """Re-geocode 'source' venue addresses and relocate the pins that two independent geocodes agree are
    off. Returns counts + a sample of the moves and the ambiguous candidates that were conservatively kept."""
    sql = text(_SELECT_BASE + (_FUTURE_CLAUSE if future_only else "") + "ORDER BY venue_id LIMIT :lim")
    geocoder = GeocodingService()
    moved = kept = ambiguous = skipped = 0
    samples: list[str] = []
    amb: list[str] = []
    async with WorkerAsyncSessionLocal() as db:
        rows = (await db.execute(sql, {"lim": limit})).all()
        for i, (vid, name, address, city, lat, lon) in enumerate(rows, 1):
            addr = await _safe_geocode(geocoder.geocode, address, city)
            if not addr:
                skipped += 1  # geocoder gave nothing — leave 'source' so a later run can retry
                continue
            shift = _dist_m((lat, lon), (addr.lat, addr.lon))
            move_to = None
            was_ambiguous = False
            if addr.precision in _HOUSE_PRECISION and _MIN_SHIFT_M < shift < _SANITY_M:
                # The address says the source pin is off. Confirm with an INDEPENDENT venue-name geocode
                # before moving — agreement guards parks/ambiguous names where the source may be right.
                nm = await _safe_geocode(geocoder.geocode_venue_osm_first, name, city)
                if nm and _dist_m((addr.lat, addr.lon), (nm.lat, nm.lon)) < _AGREE_M:
                    move_to = addr
                else:
                    was_ambiguous = True
            if move_to is not None:
                if apply:
                    await db.execute(_MOVE_SQL, {"lon": move_to.lon, "lat": move_to.lat, "c": move_to.confidence, "v": vid})
                moved += 1
                if len(samples) < 30:
                    samples.append(f"v{vid} {(name or '')[:30]!r} {round(shift)}m -> {move_to.lat:.5f},{move_to.lon:.5f}")
            else:
                if apply:
                    await db.execute(_KEEP_SQL, {"v": vid})
                if was_ambiguous:
                    ambiguous += 1
                    if len(amb) < 15:
                        amb.append(f"v{vid} {(name or '')[:30]!r} addr says {round(shift)}m off but name disagrees — kept")
                else:
                    kept += 1
            if apply and i % _COMMIT_EVERY == 0:
                await db.commit()
        if apply:
            await db.commit()
        scanned = len(rows)
    return {"scanned": scanned, "moved": moved, "kept_ok": kept, "ambiguous_kept": ambiguous,
            "skipped_unresolved": skipped, "applied": apply, "samples": samples, "ambiguous": amb}


def main() -> None:
    apply = "--dry-run" not in sys.argv
    future_only = "--all" not in sys.argv
    limit = 800
    if "--limit" in sys.argv:
        limit = int(sys.argv[sys.argv.index("--limit") + 1])
    res = asyncio.run(correct_venue_coordinates(apply=apply, limit=limit, future_only=future_only))
    print(("APPLIED" if apply else "DRY RUN") + ": " + str({k: v for k, v in res.items() if k not in ("samples", "ambiguous")}))
    print("-- moved --")
    for s in res["samples"]:
        print("  " + s)
    print("-- ambiguous (kept) --")
    for s in res["ambiguous"]:
        print("  " + s)


if __name__ == "__main__":
    main()
