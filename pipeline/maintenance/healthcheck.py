"""Assert the dedup invariants on live data — run it against production to prove
the pipeline is clean (and as a regression guard after changes).

Invariants (each must be 0):
  1. no two active events at the same venue + Moscow day are auto-mergeable
     duplicates (same event by title);
  2. no active event spans more than one physical place (over-merge);
  3. no active event still has duplicate venue rows to collapse into one pin;
  4. no exact near-duplicate venues within 200 m.

Fuzzy review candidates (a distinctive-subset pair like "Женитьба" / "Женитьба
Фигаро") are reported for information — they are intentionally not auto-merged.

Run:  docker compose -p tg-bot-afisha exec -T prefect-serve python -m pipeline.maintenance.healthcheck
"""
import sys

from sqlalchemy import text

from core.db.session import SessionLocal
from pipeline.maintenance.events import find_pairs
from pipeline.maintenance.resplit import resplit

_NEAR_DUP_VENUES = """
with v as (
  select venue_id, regexp_replace(translate(lower(name),'ё','е'),'[^0-9a-zа-я]','','g') nk, geom
  from events.venues where geom is not null and name <> ''
)
select count(*) from v a where exists (
  select 1 from v b where b.venue_id <> a.venue_id and b.nk = a.nk
    and ST_DWithin(a.geom::geography, b.geom::geography, 200))
"""


def main() -> None:
    db = SessionLocal()
    try:
        _title, _rank, safe_pairs, fuzzy_pairs = find_pairs(db)
        near_dup_venues = db.execute(text(_NEAR_DUP_VENUES)).scalar()
    finally:
        db.close()
    rs = resplit(apply=False)

    checks = [
        ("auto-mergeable event duplicates (same venue+day)", len(safe_pairs)),
        ("events spanning >1 physical place (over-merge)", rs["split"]),
        ("events with duplicate venue pins to collapse", rs["consolidated"]),
        ("exact near-duplicate venues (<=200m)", near_dup_venues),
    ]
    ok = True
    for name, n in checks:
        ok = ok and n == 0
        print("[%s] %s: %s" % ("PASS" if n == 0 else "FAIL", name, n))
    print("(info) fuzzy review candidates, not auto-merged:", len(fuzzy_pairs))
    print("OVERALL:", "PASS" if ok else "FAIL")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
