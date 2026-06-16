"""Re-derive occurrences in place for events whose stored dates no longer match
their raw session dates — chiefly afisha sparse shows that were saved as one
[min,max] span before the connector learned to read the detail-page sessions.

Run AFTER an afisha full-scan so the raws already carry the discrete dates. For
each event that currently has a multi-day span occurrence, the union of its
sources' in-window sessions is recomputed; if that differs from the stored
occurrence dates the occurrences are rebuilt (event_id, sources and the venue are
kept — only the dates change). Events whose raw is genuinely a run (a dense
exhibition) still resolve to one span, so they are left untouched.

Run:      docker compose -p tg-bot-afisha exec -T prefect-serve python -m pipeline.maintenance.rebuild_occurrences
Preview:  ... python -m pipeline.maintenance.rebuild_occurrences --dry-run
"""
import sys
from collections import Counter
from datetime import datetime, timedelta, timezone

from sqlalchemy import text

from core.db.repositories.ingestion import _OCCURRENCE_LOOKAHEAD_DAYS, _payload_session_dates
from core.db.session import SessionLocal

_SPAN_EVENTS = """
select distinct e.event_id
from events.events e
join events.event_occurrences o on o.event_id = e.event_id
where e.status = 'active' and o.date_end is not null
  and (o.date_end - o.date_start) > interval '2 days'
"""

_INSERT = """
insert into events.event_occurrences
  (event_id, venue_id, date_start, date_end, price_min, price_max, currency, source_best_url)
values (:e, :v, :ds, :de, :pmin, :pmax, :cur, :url)
"""


def rebuild(apply: bool, on_preview=None) -> dict:
    db = SessionLocal()
    try:
        now = datetime.now(timezone.utc)
        until = now + timedelta(days=_OCCURRENCE_LOOKAHEAD_DAYS)
        eids = [r[0] for r in db.execute(text(_SPAN_EVENTS)).all()]
        rebuilt = occ_before = occ_after = 0
        samples: list = []
        for eid in eids:
            occs = db.execute(text(
                "select venue_id, extract(epoch from date_start)::bigint, price_min, price_max, "
                "currency, source_best_url from events.event_occurrences where event_id = :e"
            ), {"e": eid}).all()
            sessions: dict = {}  # start_ts -> (start_dt, end_dt)
            for (payload,) in db.execute(text(
                "select r.raw_payload_json from events.event_sources es "
                "join events.raw_events r on r.raw_id = es.raw_id where es.event_id = :e"
            ), {"e": eid}).all():
                for sdt, edt in _payload_session_dates(payload, now, until):
                    sessions.setdefault(int(sdt.timestamp()), (sdt, edt))
            if not sessions or set(int(o[1]) for o in occs) == set(sessions):
                continue  # nothing to add, or already matches

            venue = Counter(o[0] for o in occs if o[0] is not None).most_common(1)
            venue_id = venue[0][0] if venue else (occs[0][0] if occs else None)
            tmpl = next((o for o in occs if o[0] == venue_id), occs[0] if occs else None)
            pmin, pmax, cur, url = (tmpl[2], tmpl[3], tmpl[4], tmpl[5]) if tmpl else (None, None, "RUB", "")

            occ_before += len(occs)
            db.execute(text("delete from events.event_occurrences where event_id = :e"), {"e": eid})
            for ts, (sdt, edt) in sorted(sessions.items()):
                db.execute(text(_INSERT), {"e": eid, "v": venue_id, "ds": sdt, "de": edt,
                                           "pmin": pmin, "pmax": pmax, "cur": cur or "RUB", "url": url or ""})
            occ_after += len(sessions)
            rebuilt += 1
            if len(samples) < 20:
                samples.append((len(occs), len(sessions)))

        if on_preview is not None:
            on_preview(len(eids), rebuilt, occ_before, occ_after, samples)
        if apply:
            db.commit()
        else:
            db.rollback()
        return {"span_events": len(eids), "rebuilt": rebuilt,
                "occ_before": occ_before, "occ_after": occ_after, "applied": apply}
    finally:
        db.close()


def _print_preview(scanned, rebuilt, before, after, samples) -> None:
    print("span events scanned: %s | rebuilt: %s | occ %s -> %s" % (scanned, rebuilt, before, after))
    print("sample (old_occ_count -> new_occ_count):", samples[:12])


def main(apply: bool) -> None:
    result = rebuild(apply, on_preview=_print_preview)
    print(("APPLIED" if apply else "DRY RUN (rolled back)") + ": " + str(result))


if __name__ == "__main__":
    main(apply="--dry-run" not in sys.argv)
