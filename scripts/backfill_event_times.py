"""One-off backfill: recover real start times for events stored at midnight.

The KudaGo normalizer used to pick an all-day / 00:00 placeholder date row even
when the event also listed real timed sessions, so timed events looked like they
ran 24/7. The fixed `_parse_kudago_dates` prefers a row with a real clock time.

This script re-parses each single-occurrence event's source payload and, ONLY
when the stored occurrence is at midnight (Moscow) AND the re-parse yields a real
time, updates the occurrence in place. Genuine all-day runs (exhibitions, year
long attractions with no session time) re-parse to midnight too → left untouched.

    python -m scripts.backfill_event_times            # full run
    python -m scripts.backfill_event_times --limit 5  # sample
"""
import argparse
from datetime import timezone
from zoneinfo import ZoneInfo

from sqlalchemy import select

from core.db.models import Event, EventOccurrence, EventSource, RawEvent
from core.db.session import SessionLocal
from pipeline.normalizer.rules import _parse_kudago_dates

MSK = ZoneInfo("Europe/Moscow")


def _is_midnight_msk(dt) -> bool:
    if dt is None:
        return False
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    t = dt.astimezone(MSK)
    return t.hour == 0 and t.minute == 0


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()

    db = SessionLocal()
    stats = {"events": 0, "skipped_multi": 0, "midnight": 0, "updated": 0, "no_time_found": 0}
    try:
        events = db.execute(select(Event)).scalars().all()
        if args.limit:
            events = events[: args.limit]
        for e in events:
            stats["events"] += 1
            occs = db.execute(select(EventOccurrence).where(EventOccurrence.event_id == e.event_id)).scalars().all()
            if len(occs) != 1:
                stats["skipped_multi"] += 1
                continue
            occ = occs[0]
            if not _is_midnight_msk(occ.date_start):
                continue  # already has a real time — never touch it
            stats["midnight"] += 1

            src = db.execute(
                select(EventSource).where(EventSource.event_id == e.event_id).order_by(EventSource.id.asc())
            ).scalars().first()
            raw = db.get(RawEvent, src.raw_id) if src else None
            payload = raw.raw_payload_json if raw and isinstance(raw.raw_payload_json, dict) else None
            if not payload or not isinstance(payload.get("dates"), list):
                continue

            new_start, new_end = _parse_kudago_dates(payload)
            if new_start is None or _is_midnight_msk(new_start):
                stats["no_time_found"] += 1  # genuine all-day / run — leave as is
                continue

            occ.date_start = new_start
            occ.date_end = new_end
            db.add(occ)
            db.commit()
            stats["updated"] += 1
        print("BACKFILL TIMES DONE:", stats)
    finally:
        db.close()


if __name__ == "__main__":
    main()
