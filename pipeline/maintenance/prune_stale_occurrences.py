"""Prune phantom future occurrences — dates a source listed once but no longer does
(a cancelled/rescheduled session). The write-time upsert is add-only, so such a date
lingers and keeps the event showing a session that won't happen until it passes.

Scope = events with NO afisha source, where the source raw's ``dates`` IS the current
truth (KudaGo/Yandex/Telegram). afisha is deliberately excluded: its real dates come
from the GraphQL schedule (not the raw), so the raw can't tell us what's stale —
resolve_afisha_dates (delete+insert from GraphQL) and lifecycle expiry handle those.

Conservative by construction: only deletes a FUTURE, in-window occurrence that is
absent from the union of the event's current raw sessions, and only when at least
one occurrence still matches that truth (so a pipeline lag / empty raw can never
empty an event). Measured magnitude is tiny (~tens of rows), so it's a light daily
sweep, not a hot-path change.

Run:      docker compose -p tg-bot-afisha exec -T prefect-serve python -m pipeline.maintenance.prune_stale_occurrences
Preview:  ... python -m pipeline.maintenance.prune_stale_occurrences --dry-run
"""
import sys
from datetime import datetime, timedelta, timezone

from sqlalchemy import text

from core.db.repositories.ingestion import _OCCURRENCE_LOOKAHEAD_DAYS, _payload_session_dates
from core.db.session import SessionLocal

_EVENTS = """
select e.event_id from events.events e
where e.status = 'active'
  and not exists (
    select 1 from events.event_sources es join ref.sources s on s.source_id = es.source_id
    where es.event_id = e.event_id and s.name = 'afisha_ru'
  )
"""
_RAWS = "select r.raw_payload_json from events.event_sources es join events.raw_events r on r.raw_id = es.raw_id where es.event_id = :e"
_OCCS = "select occurrence_id, extract(epoch from date_start)::bigint from events.event_occurrences where event_id = :e"


def prune(apply: bool) -> dict:
    db = SessionLocal()
    try:
        now = datetime.now(timezone.utc)
        until = now + timedelta(days=_OCCURRENCE_LOOKAHEAD_DAYS)
        now_ts = int(now.timestamp())
        until_ts = int(until.timestamp())
        eids = [r[0] for r in db.execute(text(_EVENTS)).all()]
        ev_pruned = occ_pruned = 0
        for eid in eids:
            # Bucket every date to the MINUTE (epoch // 60). A sub-minute drift between
            # ingests (Yandex vs the stored occurrence) must NOT make the same logical
            # session count as both present-in-raw and stale — that would delete a
            # still-valid future occurrence. Match on the minute on BOTH sides.
            cur = set()
            for (payload,) in db.execute(text(_RAWS), {"e": str(eid)}).all():
                for start, _end in _payload_session_dates(payload, now, until):
                    cur.add(int(start.timestamp()) // 60)
            if not cur:
                continue  # no authoritative raw dates (LLM/ldjson source) — leave it
            occs = db.execute(text(_OCCS), {"e": str(eid)}).all()
            # Only prune when the event still has a real current date (guards against
            # a transient empty/parse-failed raw wiping every occurrence).
            if not any(int(ts) // 60 in cur for _oid, ts in occs):
                continue
            stale = [oid for oid, ts in occs if now_ts <= int(ts) <= until_ts and int(ts) // 60 not in cur]
            if not stale:
                continue
            db.execute(text("delete from events.event_occurrences where occurrence_id = any(:ids)"), {"ids": stale})
            ev_pruned += 1
            occ_pruned += len(stale)
        if apply:
            db.commit()
        else:
            db.rollback()
        return {"scanned": len(eids), "events_pruned": ev_pruned, "occurrences_pruned": occ_pruned, "applied": apply}
    finally:
        db.close()


def main(apply: bool) -> None:
    print(("APPLIED" if apply else "DRY RUN (rolled back)") + ": " + str(prune(apply)))


if __name__ == "__main__":
    main(apply="--dry-run" not in sys.argv)
