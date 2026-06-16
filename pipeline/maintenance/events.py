"""Merge duplicate *event* records — the same event ingested from two sources
(or the same source twice) that the old dedup failed to collapse, so it shows as
two pins at one venue/time ("Селеба" from Yandex + afisha.ru, "Polnalyubvi" vs
"Полналюбви", "Света" vs "Света. Большой сольный концерт").

Two events are duplicates when they share a Moscow calendar day AND either the
same venue or an identical title key on that day, AND their titles are the same
event by ``title_match.same_event`` (exact / transliterated / token-subset, with
number-and-generic guards). The canonical event is the one with the most sources
(then occurrences); the rest are repointed onto it and deleted.

Run:      docker compose -p tg-bot-afisha exec -T prefect-serve python -m pipeline.maintenance.events
Preview:  ... python -m pipeline.maintenance.events --dry-run
"""
import sys
from collections import defaultdict

from sqlalchemy import text

from core.db.session import SessionLocal
from pipeline.dedup.title_match import same_event, same_slot_title, title_nkey

_MSK_DAY = "(occ.date_start at time zone 'UTC' at time zone 'Europe/Moscow')::date"

_EVENTS = """
select e.event_id, e.canonical_title,
  (select count(*) from events.event_sources es where es.event_id = e.event_id) as n_src,
  (select count(*) from events.event_occurrences o where o.event_id = e.event_id) as n_occ
from events.events e
where e.status = 'active' and e.canonical_title <> ''
"""

_OCCS = f"""
select e.event_id, occ.venue_id, {_MSK_DAY} as d, occ.date_start
from events.events e
join events.event_occurrences occ on occ.event_id = e.event_id
where e.status = 'active' and e.canonical_title <> ''
"""


class _UF:
    def __init__(self) -> None:
        self.p: dict[str, str] = {}

    def find(self, x: str) -> str:
        self.p.setdefault(x, x)
        while self.p[x] != x:
            self.p[x] = self.p[self.p[x]]
            x = self.p[x]
        return x

    def union(self, a: str, b: str) -> None:
        self.p[self.find(a)] = self.find(b)


def find_pairs(db) -> tuple[dict, dict, list, list]:
    """Return (title, rank, safe_pairs, fuzzy_pairs). ``safe_pairs`` are key/translit
    matches (trustworthy); ``fuzzy_pairs`` are subset/ratio matches to be reviewed."""
    title: dict[str, str] = {}
    rank: dict[str, tuple] = {}
    for eid, t, n_src, n_occ in db.execute(text(_EVENTS)).all():
        title[eid] = t
        rank[eid] = (n_src, n_occ)

    # Group event ids by (venue, day) — a duplicate must share the same physical
    # place + day (matching on title across venues collapses different stagings of
    # one play at different theatres). Placeless events (no venue) can only group
    # by (title-key, day).
    by_venue_day: dict[tuple, set] = defaultdict(set)
    by_placeless_day: dict[tuple, set] = defaultdict(set)
    by_venue_time: dict[tuple, set] = defaultdict(set)
    for eid, venue_id, d, ds in db.execute(text(_OCCS)).all():
        if venue_id is not None:
            by_venue_day[(venue_id, d)].add(eid)
            by_venue_time[(venue_id, ds)].add(eid)
        else:
            by_placeless_day[(title_nkey(title.get(eid, "")), d)].add(eid)

    safe_pairs: list[tuple[str, str]] = []
    fuzzy_pairs: list[tuple[str, str]] = []
    seen_pairs: set[tuple[str, str]] = set()

    # Exact-time collision: a venue can't run two shows at the same instant, so two
    # events sharing a venue + exact start with related titles are one event — even
    # when one only adds a subtitle ("…на крыше" vs "…на крыше «Маска», «Мулен Руж»")
    # or a location suffix on an all-generic title ("Большой стендап" vs "Большой
    # стендап на Сретенке"). same_slot_title accepts the plain token-subset the slot
    # makes conclusive; same_event covers the high-ratio non-subset case. Promote
    # both (otherwise fuzzy) to the safe tier.
    for bucket in by_venue_time.values():
        ids = sorted(bucket)
        for i in range(len(ids)):
            for j in range(i + 1, len(ids)):
                a, b = ids[i], ids[j]
                if (a, b) in seen_pairs:
                    continue
                if same_slot_title(title[a], title[b]) or same_event(title[a], title[b], level="fuzzy", strict_numbers=False):
                    seen_pairs.add((a, b))
                    safe_pairs.append((a, b))

    for bucket in list(by_venue_day.values()) + list(by_placeless_day.values()):
        ids = sorted(bucket)
        for i in range(len(ids)):
            for j in range(i + 1, len(ids)):
                a, b = ids[i], ids[j]
                if (a, b) in seen_pairs:
                    continue
                seen_pairs.add((a, b))
                if same_event(title[a], title[b], level="auto"):
                    safe_pairs.append((a, b))
                elif same_event(title[a], title[b], level="fuzzy"):
                    fuzzy_pairs.append((a, b))
    return title, rank, safe_pairs, fuzzy_pairs


def merge_duplicate_events(apply: bool, fuzzy: bool = False, allowed_fuzzy=None, on_preview=None) -> dict:
    """Merge duplicate events. ``fuzzy=False`` merges only the safe key/translit
    tier (used by the periodic flow). ``fuzzy=True`` also merges subset/ratio
    pairs; pass ``allowed_fuzzy`` (a set of frozenset({a,b}) pairs) to restrict
    those to a reviewed allowlist."""
    db = SessionLocal()
    try:
        title, rank, safe_pairs, fuzzy_pairs = find_pairs(db)

        uf = _UF()
        for a, b in safe_pairs:
            uf.union(a, b)
        # allowed_fuzzy is a set of frozenset({str(id), str(id)}); ids here may be
        # UUID objects, so compare on their string form.
        allow = None if allowed_fuzzy is None else {frozenset(map(str, fs)) for fs in allowed_fuzzy}
        applied_fuzzy: list[tuple[str, str]] = []
        if fuzzy:
            for a, b in fuzzy_pairs:
                if allow is None or frozenset((str(a), str(b))) in allow:
                    uf.union(a, b)
                    applied_fuzzy.append((a, b))

        members_of = {v for pair in safe_pairs + applied_fuzzy for v in pair}
        clusters: dict[str, list[str]] = defaultdict(list)
        for eid in members_of:
            clusters[uf.find(eid)].append(eid)
        pairs: list[tuple[str, str]] = []  # (dup_id, canon_id)
        for cmembers in clusters.values():
            canon = max(cmembers, key=lambda e: (rank.get(e, (0, 0)), e))
            pairs.extend((d, canon) for d in cmembers if d != canon)

        if on_preview is not None:
            on_preview(title, safe_pairs, fuzzy_pairs, len(clusters), len(pairs))

        repointed = deduped = 0
        for dup_id, canon_id in pairs:
            deduped += db.execute(text(
                "delete from events.event_occurrences d "
                "where d.event_id = :dup and exists ("
                "  select 1 from events.event_occurrences c "
                "  where c.event_id = :canon and c.date_start = d.date_start "
                "    and c.venue_id is not distinct from d.venue_id)"
            ), {"dup": dup_id, "canon": canon_id}).rowcount
            repointed += db.execute(
                text("update events.event_occurrences set event_id = :canon where event_id = :dup"),
                {"canon": canon_id, "dup": dup_id},
            ).rowcount
            db.execute(
                text("update events.event_sources set event_id = :canon where event_id = :dup"),
                {"canon": canon_id, "dup": dup_id},
            )
        deleted = 0
        if pairs:
            deleted = db.execute(
                text("delete from events.events where event_id = any(:ids)"),
                {"ids": [d for d, _ in pairs]},
            ).rowcount
        if apply:
            db.commit()
        else:
            db.rollback()
        return {
            "clusters": len(clusters), "dup_events": len(pairs),
            "repointed_occ": repointed, "deduped_occ": deduped,
            "events_deleted": deleted, "applied": apply,
            "safe_pairs": len(safe_pairs), "fuzzy_pairs": len(fuzzy_pairs),
        }
    finally:
        db.close()


def dump_fuzzy_pairs() -> list[dict]:
    """The subset/ratio candidate pairs that need review, as JSON-able dicts."""
    db = SessionLocal()
    try:
        title, _rank, _safe, fuzzy_pairs = find_pairs(db)
        return [{"a": a, "b": b, "title_a": title[a], "title_b": title[b]} for a, b in fuzzy_pairs]
    finally:
        db.close()


def _print_preview(title: dict, safe_pairs: list, fuzzy_pairs: list, n_clusters: int, n_pairs: int) -> None:
    print("safe (key/translit) pairs: %s | fuzzy (subset/ratio) pairs: %s | clusters: %s | dup events: %s"
          % (len(safe_pairs), len(fuzzy_pairs), n_clusters, n_pairs))
    print("--- fuzzy pairs needing review ---")
    for a, b in fuzzy_pairs[:60]:
        print("  %-40.40s  ~  %-40.40s" % (title.get(a, ""), title.get(b, "")))


def main(apply: bool, fuzzy: bool) -> None:
    result = merge_duplicate_events(apply, fuzzy=fuzzy, on_preview=_print_preview)
    print(("APPLIED" if apply else "DRY RUN (rolled back)") + ": " + str(result))


if __name__ == "__main__":
    main(apply="--dry-run" not in sys.argv, fuzzy="--fuzzy" in sys.argv)
