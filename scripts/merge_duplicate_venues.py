"""One-off: merge duplicate venue records (same normalised name within 200 m).

Cross-source geocoding drift + ё/е + address-format differences spawned several
venue rows for one physical place, which splits a (correctly cross-source-merged)
event into a pin per venue. This repoints occurrences/candidates onto the
canonical venue (the one with the most occurrences) and removes the duplicates.
Idempotent — no duplicates left -> no-op. The fuzzy match in
``get_or_create_venue`` prevents new duplicates; this cleans up the existing ones.

Run:  docker compose -p tg-bot-afisha exec -T prefect-serve python -m scripts.merge_duplicate_venues
Preview without writing:  ... python -m scripts.merge_duplicate_venues --dry-run
"""
import sys

from sqlalchemy import text

from core.db.session import SessionLocal

# dup_id -> canon_id for venues that share a normalised name and sit within 200 m.
_PAIRS = """
with v as (
  select venue_id, geom,
    regexp_replace(translate(lower(name), 'ё', 'е'), '[^0-9a-zа-я]', '', 'g') as nkey,
    (select count(*) from events.event_occurrences o where o.venue_id = venues.venue_id) as noc
  from events.venues where geom is not null and name <> ''
),
grp as (select nkey from v group by nkey having count(*) > 1),
canon as (
  select distinct on (nkey) nkey, venue_id as canon_id, geom as canon_geom
  from v join grp using (nkey)
  order by nkey, noc desc, venue_id asc
)
select v.venue_id as dup_id, c.canon_id
from v join canon c using (nkey)
where v.venue_id <> c.canon_id
  and ST_DWithin(v.geom::geography, c.canon_geom::geography, 200)
"""


def main(apply: bool) -> None:
    db = SessionLocal()
    try:
        pairs = db.execute(text(_PAIRS)).all()
        print("duplicate venues to merge:", len(pairs))
        repointed = 0
        deduped = 0
        for dup_id, canon_id in pairs:
            # The (event_id, date_start, venue_id) unique constraint means a dup
            # occurrence can't just move onto the canonical venue if one is already
            # there — drop those colliding dup rows first, then repoint the rest.
            deduped += db.execute(text(
                "delete from events.event_occurrences d "
                "where d.venue_id = :dup and exists ("
                "  select 1 from events.event_occurrences c "
                "  where c.venue_id = :canon and c.event_id = d.event_id and c.date_start = d.date_start)"
            ), {"dup": dup_id, "canon": canon_id}).rowcount
            repointed += db.execute(
                text("update events.event_occurrences set venue_id = :canon where venue_id = :dup"),
                {"canon": canon_id, "dup": dup_id},
            ).rowcount
            db.execute(
                text("update events.event_candidates set venue_id = :canon where venue_id = :dup"),
                {"canon": canon_id, "dup": dup_id},
            )
        deleted = 0
        if pairs:
            deleted = db.execute(
                text("delete from events.venues where venue_id = any(:ids)"),
                {"ids": [d for d, _ in pairs]},
            ).rowcount
        if apply:
            db.commit()
            print("APPLIED: repointed_occ=%s deduped_occ=%s venues_deleted=%s" % (repointed, deduped, deleted))
        else:
            db.rollback()
            print("DRY RUN (rolled back): repoint_occ=%s dedup_occ=%s delete_venues=%s" % (repointed, deduped, deleted))
    finally:
        db.close()


if __name__ == "__main__":
    main(apply="--dry-run" not in sys.argv)
