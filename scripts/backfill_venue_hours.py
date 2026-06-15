"""One-off + periodic backfill: resolve venue opening hours via Yandex Maps.

Source-agnostic: every venue (whatever event source it came from) is matched by
its name + city on Yandex Maps, and the first business's structured working hours
are stored on `venues.hours_json`. A coordinate proximity guard rejects a wrong
match (the Yandex business must sit within ~600 m of our venue point).

    python -m scripts.backfill_venue_hours
    python -m scripts.backfill_venue_hours --limit 5 --sleep 2
"""
import argparse
import asyncio
import json
import math
import time

from sqlalchemy import text

from core.db.session import SessionLocal
from pipeline.geocoding.providers.yandex_maps import YandexMapsScraper

CITY = "Москва"
MAX_MATCH_M = 600


def _dist_m(a: tuple[float, float], b: tuple[float, float]) -> float:
    R = 6371000
    dlat = math.radians(b[0] - a[0])
    dlon = math.radians(b[1] - a[1])
    h = math.sin(dlat / 2) ** 2 + math.cos(math.radians(a[0])) * math.cos(math.radians(b[0])) * math.sin(dlon / 2) ** 2
    return 2 * R * math.asin(math.sqrt(h))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--sleep", type=float, default=1.5)
    ap.add_argument("--refresh", action="store_true", help="re-resolve venues that already have hours")
    args = ap.parse_args()

    db = SessionLocal()
    scraper = YandexMapsScraper()
    cond = "" if args.refresh else "AND hours_json IS NULL"
    rows = db.execute(
        text(
            f"SELECT venue_id, name, ST_Y(geom::geometry) AS lat, ST_X(geom::geometry) AS lon "
            f"FROM events.venues WHERE geom IS NOT NULL AND name <> '' {cond} ORDER BY venue_id"
        )
    ).all()
    if args.limit:
        rows = rows[: args.limit]

    stats = {"venues": len(rows), "found": 0, "stored": 0, "far_skip": 0, "none": 0}
    for vid, name, lat, lon in rows:
        try:
            res = asyncio.run(scraper.fetch_hours(name, CITY))
        except Exception:
            res = None
        if not res or not res.get("hours"):
            stats["none"] += 1
            time.sleep(args.sleep)
            continue
        stats["found"] += 1
        coords = res.get("coords")
        if coords and lat is not None and lon is not None and _dist_m((lat, lon), coords) > MAX_MATCH_M:
            stats["far_skip"] += 1  # wrong business — don't store its hours
            time.sleep(args.sleep)
            continue
        db.execute(
            text("UPDATE events.venues SET hours_json = CAST(:h AS JSON) WHERE venue_id = :v"),
            {"h": json.dumps(res["hours"], ensure_ascii=False), "v": vid},
        )
        db.commit()
        stats["stored"] += 1
        time.sleep(args.sleep)
    print("VENUE HOURS BACKFILL DONE:", stats)


if __name__ == "__main__":
    main()
