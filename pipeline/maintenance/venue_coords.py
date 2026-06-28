"""Correct venue coordinates that came verbatim from a source feed and landed in the wrong spot.

ROOT CAUSE of "this venue shows in the wrong place": when an event source embeds a venue coordinate,
enrich trusts it as-is (``geocode_provider='source'``, confidence 0.95) and never geocodes the address.
Most source coords are fine, but some pin a venue ~100-200 m off (e.g. НЭТ Волгоград sat past Аллея
Героев). This pass re-geocodes the ADDRESS house-precisely via Yandex and, when the precise point
disagrees with the stored ``source`` point by more than ``_MIN_SHIFT_M`` (and isn't absurdly far), moves
the venue there — the street address is what the user expects the pin to match.

Self-healing + cost-bounded: each ``source`` venue is geocoded ONCE, then MARKED — moved ones become
``geocode_fix``, reviewed-and-kept ones ``source_ok`` — so a re-run only pays for venues it hasn't seen.
New ``source`` venues from later ingests are picked up on the next run. Idempotent; safe on a schedule.
A venue the geocoder can't resolve at all (transient miss / hard address) is LEFT as ``source`` to retry.

Only ``source`` venues are touched: ``yandex``/``yandex_maps``/``osm`` rows were already derived FROM the
address, so they're not the wrong-pin class. ``geocode_provider`` is informational — nothing filters on it.

Run:      docker compose -p tg-bot-afisha exec -T prefect-serve python -m pipeline.maintenance.venue_coords --limit 2500
Preview:  ... python -m pipeline.maintenance.venue_coords --dry-run --limit 60
"""
import asyncio
import math
import sys

from sqlalchemy import text

from core.db.session import WorkerAsyncSessionLocal
from pipeline.geocoding.service import GeocodingService

_MIN_SHIFT_M = 110          # stored 'source' point this far from the house-precise geocode → trust the geocode
_SANITY_M = 30_000          # ...but never relocate a venue >30 km (a bad address parse landing in another city)
_HOUSE_PRECISION = {"exact", "number"}  # only override on Yandex house-level precision — minimises regressions
_COMMIT_EVERY = 50          # flush periodically so a long pass is resumable and a mid-run crash keeps progress


def _dist_m(a: tuple[float, float], b: tuple[float, float]) -> float:
    R = 6371000.0
    dlat = math.radians(b[0] - a[0])
    dlon = math.radians(b[1] - a[1])
    s = math.sin(dlat / 2) ** 2 + math.cos(math.radians(a[0])) * math.cos(math.radians(b[0])) * math.sin(dlon / 2) ** 2
    return 2 * R * math.asin(min(1.0, math.sqrt(s)))


_SELECT_BASE = (
    "SELECT venue_id, name, address, city, ST_Y(geom::geometry) AS lat, ST_X(geom::geometry) AS lon "
    "FROM events.venues "
    "WHERE geocode_provider = 'source' AND coalesce(address, '') <> '' AND geom IS NOT NULL "
)
_FUTURE_CLAUSE = (
    "AND EXISTS (SELECT 1 FROM events.event_occurrences o "
    "WHERE o.venue_id = venues.venue_id AND o.date_start >= now()) "
)


async def correct_venue_coordinates(apply: bool = True, limit: int = 800, future_only: bool = True) -> dict:
    """Re-geocode 'source' venue addresses and relocate the pins that are materially off. Returns counts."""
    sql = text(_SELECT_BASE + (_FUTURE_CLAUSE if future_only else "") + "ORDER BY venue_id LIMIT :lim")
    geocoder = GeocodingService()
    moved = checked = skipped = 0
    samples: list[str] = []
    async with WorkerAsyncSessionLocal() as db:
        rows = (await db.execute(sql, {"lim": limit})).all()
        for i, (vid, name, address, city, lat, lon) in enumerate(rows, 1):
            try:
                geo = await geocoder.geocode(address, city_hint=city)
            except Exception:
                geo = None
            if not geo:
                skipped += 1  # geocoder gave nothing (transient miss / hard address) — leave 'source', retry later
                continue
            dist = _dist_m((lat, lon), (geo.lat, geo.lon))
            if geo.precision in _HOUSE_PRECISION and _MIN_SHIFT_M < dist < _SANITY_M:
                if apply:
                    await db.execute(text(
                        "UPDATE events.venues SET geom = ST_SetSRID(ST_MakePoint(:lon, :lat), 4326), "
                        "geocode_provider = 'geocode_fix', geocode_confidence = :c, updated_at = now() "
                        "WHERE venue_id = :v"
                    ), {"lon": geo.lon, "lat": geo.lat, "c": geo.confidence, "v": vid})
                moved += 1
                if len(samples) < 30:
                    samples.append(f"v{vid} {(name or '')[:32]!r} {round(dist)}m -> {geo.lat:.5f},{geo.lon:.5f}")
            else:
                # House-precise and close enough, OR no house-precision to verify against — keep the source
                # point but mark it reviewed so the next run skips it (cost-bounded).
                if apply:
                    await db.execute(text(
                        "UPDATE events.venues SET geocode_provider = 'source_ok', updated_at = now() WHERE venue_id = :v"
                    ), {"v": vid})
                checked += 1
            if apply and i % _COMMIT_EVERY == 0:
                await db.commit()
        if apply:
            await db.commit()
        scanned = len(rows)
    return {"scanned": scanned, "moved": moved, "checked_ok": checked,
            "skipped_unresolved": skipped, "applied": apply, "samples": samples}


def main() -> None:
    apply = "--dry-run" not in sys.argv
    future_only = "--all" not in sys.argv
    limit = 800
    if "--limit" in sys.argv:
        limit = int(sys.argv[sys.argv.index("--limit") + 1])
    res = asyncio.run(correct_venue_coordinates(apply=apply, limit=limit, future_only=future_only))
    print(("APPLIED" if apply else "DRY RUN") + ": " + str({k: v for k, v in res.items() if k != "samples"}))
    for s in res["samples"]:
        print("  " + s)


if __name__ == "__main__":
    main()
