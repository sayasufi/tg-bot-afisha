"""Re-derive event occurrences in place from their raw payloads — used once after
widening Yandex's date window (so its raws now list every session date) to bring
existing events up to their full set of dates without re-running the whole pipeline.

For each active event we take the source raw that lists the MOST in-window sessions
(Yandex's bulk dates win over afisha's Min/Max) and rebuild the occurrences to match
— keeping event_id, sources and the venue, only the dates change. Events already in
sync are skipped. Picking a single richest source (not a union) avoids same-day
duplicates from sources that disagree on the clock time.

Run:      docker compose -p tg-bot-afisha exec -T prefect-serve python -m pipeline.maintenance.rebuild_occurrences
Preview:  ... python -m pipeline.maintenance.rebuild_occurrences --dry-run
"""
import sys
from collections import Counter
from datetime import datetime, timedelta, timezone

from sqlalchemy import text

from core.db.repositories.ingestion import _OCCURRENCE_LOOKAHEAD_DAYS, _payload_session_dates
from core.db.session import SessionLocal

_EVENTS = "select event_id from events.events where status = 'active'"
_OCCS = "select venue_id, extract(epoch from date_start)::bigint, price_min, price_max, currency, source_best_url from events.event_occurrences where event_id = :e"
_RAWS = "select r.raw_payload_json from events.event_sources es join events.raw_events r on r.raw_id = es.raw_id where es.event_id = :e"
_INSERT = ("insert into events.event_occurrences (event_id, venue_id, date_start, date_end, price_min, price_max, currency, source_best_url) "
           "values (:e, :v, :ds, :de, :pmin, :pmax, :cur, :url)")


def rebuild(apply: bool) -> dict:
    db = SessionLocal()
    try:
        now = datetime.now(timezone.utc)
        until = now + timedelta(days=_OCCURRENCE_LOOKAHEAD_DAYS)
        eids = [r[0] for r in db.execute(text(_EVENTS)).all()]
        rebuilt = occ_before = occ_after = 0
        for eid in eids:
            # richest source raw = the one listing the most in-window sessions
            best: list = []
            for (payload,) in db.execute(text(_RAWS), {"e": str(eid)}).all():
                sessions = _payload_session_dates(payload, now, until)
                if len(sessions) > len(best):
                    best = sessions
            if not best:
                continue
            occs = db.execute(text(_OCCS), {"e": str(eid)}).all()
            new_starts = {int(s.timestamp()) for s, _ in best}
            if {int(o[1]) for o in occs} == new_starts:
                continue  # already in sync
            venue = Counter(o[0] for o in occs if o[0] is not None).most_common(1)
            venue_id = venue[0][0] if venue else (occs[0][0] if occs else None)
            tmpl = next((o for o in occs if o[0] == venue_id), occs[0] if occs else None)
            pmin, pmax, cur, url = (tmpl[2], tmpl[3], tmpl[4], tmpl[5]) if tmpl else (None, None, "RUB", "")
            occ_before += len(occs)
            db.execute(text("delete from events.event_occurrences where event_id = :e"), {"e": str(eid)})
            for sdt, edt in best:
                db.execute(text(_INSERT), {"e": str(eid), "v": venue_id, "ds": sdt, "de": edt,
                                           "pmin": pmin, "pmax": pmax, "cur": cur or "RUB", "url": url or ""})
            occ_after += len(best)
            rebuilt += 1
        if apply:
            db.commit()
        else:
            db.rollback()
        return {"scanned": len(eids), "rebuilt": rebuilt, "occ_before": occ_before, "occ_after": occ_after, "applied": apply}
    finally:
        db.close()


def main(apply: bool) -> None:
    print(("APPLIED" if apply else "DRY RUN (rolled back)") + ": " + str(rebuild(apply)))


if __name__ == "__main__":
    main(apply="--dry-run" not in sys.argv)
