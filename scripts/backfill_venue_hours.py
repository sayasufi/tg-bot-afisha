"""One-off + periodic backfill: resolve venue opening hours via Yandex Maps.

Source-agnostic: every venue (whatever event source it came from) is matched by
its name + address + city on Yandex Maps, and the first business's structured
working hours are stored on `venues.hours_json`. Including the address fixes
same-named venues elsewhere in the city; a coordinate proximity guard then
rejects a wrong match.

    python -m scripts.backfill_venue_hours                 # only venues with no hours yet
    python -m scripts.backfill_venue_hours --refresh-empty  # also retry ones with empty {}/no week
    python -m scripts.backfill_venue_hours --refresh        # everything
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
MAX_MATCH_M = 1500  # the address disambiguates, so allow a looser match (big parks/estates)


def _dist_m(a: tuple[float, float], b: tuple[float, float]) -> float:
    R = 6371000
    dlat = math.radians(b[0] - a[0])
    dlon = math.radians(b[1] - a[1])
    h = math.sin(dlat / 2) ** 2 + math.cos(math.radians(a[0])) * math.cos(math.radians(b[0])) * math.sin(dlon / 2) ** 2
    return 2 * R * math.asin(math.sqrt(h))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--sleep", type=float, default=1.4)
    ap.add_argument("--refresh-empty", action="store_true", help="also retry venues stamped {} / without a week")
    ap.add_argument("--refresh", action="store_true", help="re-resolve every venue")
    args = ap.parse_args()

    if args.refresh:
        cond = ""
    elif args.refresh_empty:
        cond = "AND (hours_json IS NULL OR hours_json::text NOT LIKE '%week%')"
    else:
        cond = "AND hours_json IS NULL"

    db = SessionLocal()
    scraper = YandexMapsScraper()
    rows = db.execute(
        text(
            f"SELECT venue_id, name, address, ST_Y(geom::geometry) AS lat, ST_X(geom::geometry) AS lon "
            f"FROM events.venues WHERE geom IS NOT NULL AND name <> '' {cond} ORDER BY venue_id"
        )
    ).all()
    if args.limit:
        rows = rows[: args.limit]

    stats = {"venues": len(rows), "found": 0, "stored": 0, "far_skip": 0, "none": 0}
    for vid, name, address, lat, lon in rows:
        query = f"{name}, {address}".strip().strip(",").strip() if address else name
        try:
            res = asyncio.run(scraper.fetch_hours(query, CITY))
        except Exception:
            res = None
        hours: dict = {}  # default: checked, nothing usable → stamp {} so we don't re-query
        if isinstance(res, dict) and res.get("blocked"):
            stats.setdefault("blocked", 0)
            stats["blocked"] += 1
            time.sleep(args.sleep)
            continue  # captcha/network — don't cache {} as "no hours"; leave for retry
        if res and res.get("hours"):
            stats["found"] += 1
            coords = res.get("coords")
            if coords and lat is not None and lon is not None and _dist_m((lat, lon), coords) > MAX_MATCH_M:
                stats["far_skip"] += 1
            else:
                hours = res["hours"]
                stats["stored"] += 1
        else:
            stats["none"] += 1
        db.execute(
            text("UPDATE events.venues SET hours_json = CAST(:h AS JSON) WHERE venue_id = :v"),
            {"h": json.dumps(hours, ensure_ascii=False), "v": vid},
        )
        db.commit()
        time.sleep(args.sleep)
    print("VENUE HOURS BACKFILL DONE:", stats)


if __name__ == "__main__":
    main()
