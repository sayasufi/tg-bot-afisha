"""Repair events whose occurrences span more than one venue — split the ones that
span genuinely different *places* and consolidate the ones that are really one
place reached through duplicate venue rows.

Both the old dedup and an over-eager first cleanup matched events by title across
venues, so "Безымянная звезда" (a play staged at four theatres the same night)
collapsed into one event with four venue pins, while true cross-source duplicates
that resolved to two venue rows ~50 m apart became one event with two near-dup
pins. This pass clusters each multi-venue event's venues by proximity (<=200 m =
one place):
  * >1 cluster  -> split: keep the largest cluster on the event, move each other
    cluster's occurrences to a fresh copy of the event (so the four stagings
    become four events).
  * within every cluster -> repoint all occurrences to one canonical venue and
    drop the rows that then collide on (date, venue) — collapsing the near-dup
    pins to one.
Sources are re-pointed to the split they came from (matched by URL); the map
renders from occurrences, so a source that can't be matched simply stays put.

Run:      docker compose -p tg-bot-afisha exec -T prefect-serve python -m scripts.resplit_multivenue_events
Preview:  ... python -m scripts.resplit_multivenue_events --dry-run
"""
import math
import sys
from collections import Counter, defaultdict

from sqlalchemy import text

from core.db.session import SessionLocal
from pipeline.dedup.venue_match import name_match_score

THRESH_M = 200  # venues this close are treated as one physical place

_COPY = """
insert into events.events
  (event_id, canonical_title, canonical_description, category, subcategory,
   age_limit, popularity_score, rating_score, primary_image_url, cached_image_url, status)
select gen_random_uuid(), canonical_title, canonical_description, category, subcategory,
   age_limit, popularity_score, rating_score, primary_image_url, cached_image_url, status
from events.events where event_id = :e
returning event_id
"""

def _haversine(a: tuple, b: tuple) -> float:
    (lat1, lon1), (lat2, lon2) = a, b
    r = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = math.radians(lat2 - lat1), math.radians(lon2 - lon1)
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(h))


def _cluster(vgeom: dict, vname: dict) -> list[list[int]]:
    """Group an event's venues into physical places: union two venues when they
    sit within THRESH_M OR their names match. The name rule catches one place
    that drifted to two rows >200 m apart ("Театр.doc на Лесной" twice) — within a
    single event, a shared name means a shared place."""
    ids = list(vgeom)
    parent = {i: i for i in ids}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for i in range(len(ids)):
        for j in range(i + 1, len(ids)):
            ga, gb = vgeom[ids[i]], vgeom[ids[j]]
            close = bool(ga and gb and _haversine(ga, gb) <= THRESH_M)
            named = name_match_score(vname.get(ids[i], ""), vname.get(ids[j], "")) is not None
            if close or named:
                parent[find(ids[i])] = find(ids[j])
    out = defaultdict(list)
    for i in ids:
        out[find(i)].append(i)
    return list(out.values())


def resplit(apply: bool, on_preview=None) -> dict:
    db = SessionLocal()
    try:
        multi = [r[0] for r in db.execute(text(
            "select event_id from events.event_occurrences where venue_id is not null "
            "group by event_id having count(distinct venue_id) > 1"
        )).all()]
        st = {"scanned": len(multi), "split": 0, "new_events": 0, "consolidated": 0,
              "occ_repointed": 0, "occ_deduped": 0, "sources_moved": 0}
        samples = []
        for eid in multi:
            occs = db.execute(text(
                "select o.occurrence_id, o.venue_id, coalesce(o.source_best_url,''), o.date_start, "
                "ST_Y(v.geom::geometry), ST_X(v.geom::geometry), coalesce(v.name,'') "
                "from events.event_occurrences o left join events.venues v on v.venue_id = o.venue_id "
                "where o.event_id = :e"
            ), {"e": eid}).all()
            vgeom: dict = {}
            vname: dict = {}
            vcount: Counter = Counter()
            for _oid, vid, _url, _ds, lat, lon, nm in occs:
                if vid is None:
                    continue
                vcount[vid] += 1
                if vid not in vgeom:
                    vgeom[vid] = (float(lat), float(lon)) if lat is not None else None
                    vname[vid] = nm
            if len(vgeom) < 2:
                continue
            clusters = _cluster(vgeom, vname)
            cl_canon = [max(cl, key=lambda v: (vcount[v], -v)) for cl in clusters]
            cl_occ = [sum(vcount[v] for v in cl) for cl in clusters]
            primary = max(range(len(clusters)), key=lambda k: (cl_occ[k], -min(clusters[k])))
            v2cl = {v: k for k, cl in enumerate(clusters) for v in cl}

            cluster_eid = {primary: eid}
            if len(clusters) > 1:
                st["split"] += 1
                if len(samples) < 25:
                    title = db.execute(text("select canonical_title from events.events where event_id=:e"), {"e": eid}).scalar()
                    vnames = db.execute(text("select venue_id, name from events.venues where venue_id = any(:ids)"),
                                        {"ids": [cl_canon[k] for k in range(len(clusters))]}).all()
                    nm = {vid: n for vid, n in vnames}
                    samples.append((title, [nm.get(cl_canon[k], "?") for k in range(len(clusters))]))
                for k in range(len(clusters)):
                    if k == primary:
                        continue
                    cluster_eid[k] = db.execute(text(_COPY), {"e": eid}).scalar()
                    st["new_events"] += 1
            else:
                st["consolidated"] += 1

            # Group occurrences by their TARGET (event, date, canonical venue): keep
            # one survivor per group, delete the rest first (so repointing the
            # survivor can't collide on the (event, date, venue) unique key).
            url2cl: dict = {}
            groups: dict = defaultdict(list)
            for oid, vid, url, ds, lat, lon, nm in occs:
                if vid is None:
                    continue
                k = v2cl[vid]
                if url:
                    url2cl.setdefault(url, k)
                groups[(k, ds, cl_canon[k])].append(oid)
            for (k, ds, cv), oids in groups.items():
                survivor = min(oids)
                losers = [o for o in oids if o != survivor]
                if losers:
                    db.execute(text("delete from events.event_occurrences where occurrence_id = any(:ids)"),
                               {"ids": losers})
                    st["occ_deduped"] += len(losers)
                db.execute(text(
                    "update events.event_occurrences set event_id = :te, venue_id = :cv where occurrence_id = :oid"
                ), {"te": str(cluster_eid[k]), "cv": cv, "oid": survivor})
                st["occ_repointed"] += 1

            if len(clusters) > 1:
                for sid, surl in db.execute(text(
                    "select id, coalesce(source_event_url,'') from events.event_sources where event_id = :e"
                ), {"e": eid}).all():
                    k = url2cl.get(surl)
                    if k is not None and k != primary:
                        db.execute(text("update events.event_sources set event_id = :te where id = :sid"),
                                   {"te": str(cluster_eid[k]), "sid": sid})
                        st["sources_moved"] += 1

        if on_preview is not None:
            on_preview(samples)
        if apply:
            db.commit()
        else:
            db.rollback()
        st["applied"] = apply
        return st
    finally:
        db.close()


def _print_preview(samples: list) -> None:
    print("--- sample splits (event -> the distinct places it was wrongly merged across) ---")
    for title, places in samples:
        print("  %-44.44s -> %s" % (title, " | ".join(p[:22] for p in places)))


def main(apply: bool) -> None:
    result = resplit(apply, on_preview=_print_preview)
    print(("APPLIED" if apply else "DRY RUN (rolled back)") + ": " + str(result))


if __name__ == "__main__":
    main(apply="--dry-run" not in sys.argv)
