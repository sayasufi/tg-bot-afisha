"""Re-derive events the OLD dedup corrupted, from their (correct) raw payloads.

Two legacy defects produced wrong event rows; both are now fixed in the dedup, but
the already-stored events need rebuilding:

* wrong TITLE — the pre-rewrite fuzzy matcher merged different acts that shared a
  first name at one venue on one day ("Алексей Архиповский" into "Александр Серов");
* wrong DATE — a 30-day session window dropped every far-future session and the
  code fell back to ``now()``, so the event surfaced as happening today at a bogus
  time (and some occurrences are simply stale vs the latest raw).

For every corrupt event we detach all of its sources (freeing their candidates) and
delete the event; the normal dedup flow then rebuilds it correctly — the raws were
never wrong. Run the dedup flow after applying to reprocess the freed candidates.

Corrupt =
  * title: a source's raw title is a different event than the event title (even the
    permissive ``same_event(level="fuzzy")`` disagrees), or
  * date: the event has date-bearing sources but NO occurrence matches any of their
    raw session starts.

Run:      docker compose -p tg-bot-afisha exec -T prefect-serve python -m pipeline.maintenance.repair_corrupt_events
Preview:  ... python -m pipeline.maintenance.repair_corrupt_events --dry-run
"""
import json
import sys
from collections import defaultdict

from sqlalchemy import text

from core.db.session import SessionLocal
from pipeline.dedup.title_match import same_event

_TOL = 90  # seconds — occurrence start may round vs the raw session start


def _find_corrupt(db):
    title_bad: set = set()
    raw_starts: dict = defaultdict(set)
    has_dates: set = set()
    titles: dict = {}
    # All statuses: a date-corrupt event is often already 'expired' (its bogus
    # now()-date passed), which only hides the real future event — we still rebuild it.
    for eid, ct, payload in db.execute(text("""
        select es.event_id, e.canonical_title, r.raw_payload_json
        from events.event_sources es
        join events.events e on e.event_id = es.event_id
        join events.raw_events r on r.raw_id = es.raw_id
    """)).all():
        k = str(eid)
        titles[k] = ct
        p = payload if isinstance(payload, dict) else (json.loads(payload) if payload else {})
        rt = p.get("title") or ""
        if rt and not same_event(ct, rt, level="fuzzy"):
            title_bad.add(k)
        rows = p.get("dates")
        if isinstance(rows, list) and rows:
            has_dates.add(k)
            for row in rows:
                if isinstance(row, dict) and row.get("start"):
                    raw_starts[k].add(int(row["start"]))

    occ_by_ev: dict = defaultdict(list)
    for eid, ts in db.execute(text(
        "select o.event_id, extract(epoch from o.date_start)::bigint "
        "from events.event_occurrences o"
    )).all():
        occ_by_ev[str(eid)].append(int(ts))

    date_bad: set = set()
    for k in has_dates:
        occs = occ_by_ev.get(k, [])
        if not occs or not any(any(abs(ts - rs) <= _TOL for rs in raw_starts[k]) for ts in occs):
            date_bad.add(k)

    return title_bad, date_bad, titles


def repair(apply: bool, on_preview=None) -> dict:
    db = SessionLocal()
    try:
        title_bad, date_bad, titles = _find_corrupt(db)
        corrupt = sorted(title_bad | date_bad)
        if on_preview is not None:
            on_preview(title_bad, date_bad, titles)
        detached = deleted = 0
        if corrupt:
            detached = db.execute(
                text("delete from events.event_sources where event_id::text = any(:ids)"),
                {"ids": corrupt},
            ).rowcount
            deleted = db.execute(
                text("delete from events.events where event_id::text = any(:ids)"),
                {"ids": corrupt},
            ).rowcount
        if apply:
            db.commit()
        else:
            db.rollback()
        return {
            "corrupt_events": len(corrupt), "title_mismatch": len(title_bad),
            "date_garbage": len(date_bad), "sources_detached": detached,
            "events_deleted": deleted, "applied": apply,
        }
    finally:
        db.close()


def _print_preview(title_bad, date_bad, titles) -> None:
    print("corrupt events: %s (title-mismatch %s, date-garbage %s)"
          % (len(title_bad | date_bad), len(title_bad), len(date_bad)))
    print("--- sample title-mismatch ---")
    for k in list(title_bad)[:8]:
        print("  %s" % titles.get(k, "")[:46])
    print("--- sample date-garbage ---")
    for k in list(date_bad - title_bad)[:8]:
        print("  %s" % titles.get(k, "")[:46])


def main(apply: bool) -> None:
    result = repair(apply, on_preview=_print_preview)
    print(("APPLIED" if apply else "DRY RUN (rolled back)") + ": " + str(result))


if __name__ == "__main__":
    main(apply="--dry-run" not in sys.argv)
