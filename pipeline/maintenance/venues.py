"""Merge duplicate venue records whose names are *similar* (not just identical)
and that sit close together — the long tail the exact-name pass in
``merge_duplicate_venues`` leaves behind.

Cross-source naming drift spawns rows like "Современник" / "Современник. Основная
сцена", "Театр.doc Industrial" / "Doc Industrial", "Зелёный театр" / "Зелёный
театр в Парке Горького" for one physical place. Those share no exact normalised
key, so the strict pass can't see them, yet they split one (correctly
cross-source-merged) event into a pin per venue.

This pass pulls every venue pair within 150 m and merges the pair when either
(a) the names are a strong match (token_set_ratio >= 85) — clearly one place, or
(b) the names are a moderate match (>= 55) AND the two venues co-host the same
event on the same date — the exact symptom of a duplicate pin. The proximity
gate keeps genuinely different but co-located venues ("В тишине" / "Большая
страна", 10 m apart) separate; the co-host gate on the moderate band keeps
different places that merely share a fallback geocode apart ("Управа Басманного
района" / "Театр на Басманной", both pinned to the district centroid).
Canonical venue = the one with the most occurrences. Idempotent.

Run:      docker compose -p tg-bot-afisha exec -T prefect-serve python -m pipeline.maintenance.venues
Preview:  ... python -m pipeline.maintenance.venues --dry-run
"""
import sys

from sqlalchemy import text

from core.db.session import SessionLocal
from core.matching.title_match import same_event
from core.matching.venue_match import contrasts, is_subset, name_match_score

# Every venue pair within this radius is a *candidate*; name + co-host decide.
_RADIUS_M = 150
# Tighter radius for the name-blind "same-show" merge below: two venues this close that list the SAME
# show on the SAME day are one place even when their names share nothing. Kept small so genuinely
# distinct neighbours / adjacent festival stages aren't swept in on a coincidental title.
_SHOW_RADIUS_M = 30

_CANDIDATES = """
with v as (
  select venue_id, name, address, geom,
    (select count(*) from events.event_occurrences o where o.venue_id = venues.venue_id) as noc
  from events.venues where geom is not null and name <> ''
)
select a.venue_id, a.name, a.address, a.noc, b.venue_id, b.name, b.address, b.noc,
       ST_Distance(a.geom::geography, b.geom::geography) as dist,
       exists (
         select 1 from events.event_occurrences oa
         join events.event_occurrences ob
           on ob.event_id = oa.event_id and ob.date_start = oa.date_start
         where oa.venue_id = a.venue_id and ob.venue_id = b.venue_id
       ) as co_host
from v a join v b
  on b.venue_id > a.venue_id
 and ST_DWithin(a.geom::geography, b.geom::geography, :r)
"""


class _UF:
    def __init__(self) -> None:
        self.p: dict[int, int] = {}

    def find(self, x: int) -> int:
        self.p.setdefault(x, x)
        while self.p[x] != x:
            self.p[x] = self.p[self.p[x]]
            x = self.p[x]
        return x

    def union(self, a: int, b: int) -> None:
        self.p[self.find(a)] = self.find(b)


def _share_same_show(db, a_id: int, b_id: int) -> bool:
    """True if the two venues each carry an event with the SAME title on the same Moscow day, as
    DISTINCT event rows. That's the un-merged twin of co_host (which needs the events already merged
    onto one event_id): here the duplicate split a venue in two so hard the name matcher gave up, yet
    both list the same show at the same spot — proof it's one place ("Dex" / «легендарный завод на
    Дубровке», "ДК Альфа Кристалл" / "Alfa Only кинотеатр"). Bounded scan; Moscow-day to match dedup."""
    rows = db.execute(text(
        "select ea.canonical_title, eb.canonical_title "
        "from events.event_occurrences oa "
        "join events.events ea on ea.event_id = oa.event_id "
        "join events.event_occurrences ob on ob.venue_id = :b "
        "  and (ob.date_start at time zone 'Europe/Moscow')::date "
        "      = (oa.date_start at time zone 'Europe/Moscow')::date "
        "join events.events eb on eb.event_id = ob.event_id and eb.event_id <> ea.event_id "
        "where oa.venue_id = :a limit 200"
    ), {"a": a_id, "b": b_id}).all()
    # Fuzzy title match: the co-location (<=30m) + same-day context is the strong signal, so we let a
    # looser title (subtitle/suffix drift like "Applique 9–Y" vs "APPLIQUE 9—Y FESTIVAL") still count.
    return any(same_event(ta, tb, level="fuzzy") for ta, tb in rows)


def merge_fuzzy_venues(apply: bool, on_preview=None) -> dict:
    """Find and (if ``apply``) merge near-duplicate venues. Returns a counts dict.
    Idempotent — once there are no duplicates left it's a no-op, so it's safe to
    run on a schedule. ``on_preview(merges, name_by_id)`` is an optional hook the
    CLI uses to print the candidate list before committing."""
    db = SessionLocal()
    try:
        rows = db.execute(text(_CANDIDATES), {"r": _RADIUS_M}).all()
        uf = _UF()
        occ: dict[int, int] = {}
        name: dict[int, str] = {}
        comp: dict[int, set[int]] = {}  # uf-root -> member ids, for the contrast guard
        merges: list[tuple] = []  # (a_id, b_id, dist, ratio, co_host)

        def _guarded_union(a: int, b: int) -> bool:
            """Union a,b UNLESS it would put a contrasting pair (Большой vs Малый зал)
            in one cluster — the pairwise contrasts() guard doesn't survive transitive
            closure, so a generic bridge name ("Зал Консерватории") could otherwise
            merge the two halls it sits between. Refuse if any cross-pair contrasts."""
            ra, rb = uf.find(a), uf.find(b)
            ma, mb = comp.setdefault(ra, {a}), comp.setdefault(rb, {b})
            if ra == rb:
                return True
            if any(contrasts(name[x], name[y]) for x in ma for y in mb):
                return False
            uf.union(a, b)
            r = uf.find(a)
            comp[r] = ma | mb
            for old in (ra, rb):
                if old != r:
                    comp.pop(old, None)
            return True

        for a_id, a_name, a_addr, a_noc, b_id, b_name, b_addr, b_noc, dist, co_host in rows:
            occ[a_id], occ[b_id] = a_noc, b_noc
            name[a_id], name[b_id] = a_name, b_name
            ratio = name_match_score(a_name, b_name, co_host, addr_a=a_addr or "", addr_b=b_addr or "")
            if ratio is not None and _guarded_union(a_id, b_id):
                merges.append((a_id, b_id, round(dist), round(ratio), co_host))
            # Names too divergent for the matcher, but the pair sits on top of each other AND lists the
            # same show on the same day — one place under two unrelated names. Tight radius + antonym
            # guard keep distinct-but-close spaces (Большой/Малый зал, adjacent stages) apart.
            elif ratio is None and dist <= _SHOW_RADIUS_M and not contrasts(a_name, b_name) and _share_same_show(db, a_id, b_id):
                if _guarded_union(a_id, b_id):
                    merges.append((a_id, b_id, round(dist), 0, "same-show"))

        # Per cluster, the canonical venue keeps the most occurrences.
        clusters: dict[int, list[int]] = {}
        for vid in {v for pair in merges for v in pair[:2]}:
            clusters.setdefault(uf.find(vid), []).append(vid)
        pairs: list[tuple[int, int]] = []  # (dup_id, canon_id)
        for members in clusters.values():
            canon = max(members, key=lambda v: (occ.get(v, 0), -v))
            pairs.extend((d, canon) for d in members if d != canon)

        if on_preview is not None:
            on_preview(merges, name)

        repointed = deduped = 0
        for dup_id, canon_id in pairs:
            # The (event_id, date_start, venue_id) unique constraint means a dup
            # occurrence can't move onto the canonical venue if one is already
            # there — drop those colliding rows first, then repoint the rest.
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
        else:
            db.rollback()
        return {
            "clusters": len(clusters), "dup_venues": len(pairs),
            "repointed_occ": repointed, "deduped_occ": deduped,
            "venues_deleted": deleted, "applied": apply,
        }
    finally:
        db.close()


def _print_preview(merges: list, name: dict) -> None:
    show = [m for m in merges if not is_subset(name.get(m[0], ""), name.get(m[1], ""))]
    print("merge pairs: %s | non-subset (ratio-driven): %s" % (len(merges), len(show)))
    for a_id, b_id, dist, ratio, co_host in sorted(show, key=lambda m: m[3]):
        print("  v%-5s %-32.32s  ~  v%-5s %-32.32s  %4sm r%-3s %s"
              % (a_id, name.get(a_id, ""), b_id, name.get(b_id, ""), dist, ratio,
                 "co-host" if co_host else ""))


def main(apply: bool) -> None:
    result = merge_fuzzy_venues(apply, on_preview=_print_preview)
    print(("APPLIED" if apply else "DRY RUN (rolled back)") + ": " + str(result))


if __name__ == "__main__":
    main(apply="--dry-run" not in sys.argv)
