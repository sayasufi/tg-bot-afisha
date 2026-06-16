"""Event lifecycle: mark events whose last occurrence has already passed as
``expired`` so the map, list, search and recommendations (all of which filter
``status='active'``) stop showing them — and revive any event that has since
gained an upcoming occurrence.

An event is "live" while it has at least one occurrence that hasn't finished:
  * a TIMED occurrence — until its end time, or 3 hours after it starts when no
    end is known (so an event drops off soon after it actually ends, not at
    midnight);
  * an ALL-DAY occurrence (Moscow-midnight start, no specific time) — until the
    end of its Moscow day, so all-day/date-only listings aren't hidden mid-day;
  * a multi-day run — until its end day.
Events with no occurrence at all are not live and get expired too. Idempotent.

Run:      docker compose -p tg-bot-afisha exec -T prefect-serve python -m pipeline.maintenance.lifecycle
Preview:  ... python -m pipeline.maintenance.lifecycle --dry-run
"""
import sys

from sqlalchemy import text

from core.db.session import SessionLocal

_GRACE = "interval '3 hours'"  # how long after a timed start an event stays live

_HAS_LIVE_OCC = f"""
exists (
  select 1 from events.event_occurrences o
  where o.event_id = e.event_id
    and case
      when (o.date_start at time zone 'Europe/Moscow')::time = time '00:00' then
        coalesce((o.date_end   at time zone 'Europe/Moscow')::date,
                 (o.date_start at time zone 'Europe/Moscow')::date)
            >= (now() at time zone 'Europe/Moscow')::date
      else
        coalesce(o.date_end, o.date_start + {_GRACE}) >= now()
    end
)
"""


def expire_past_events(apply: bool) -> dict:
    db = SessionLocal()
    try:
        expired = db.execute(text(
            "update events.events e set status = 'expired' "
            "where e.status = 'active' and not " + _HAS_LIVE_OCC
        )).rowcount
        revived = db.execute(text(
            "update events.events e set status = 'active' "
            "where e.status = 'expired' and " + _HAS_LIVE_OCC
        )).rowcount
        if apply:
            db.commit()
        else:
            db.rollback()
        return {"expired": expired, "revived": revived, "applied": apply}
    finally:
        db.close()


def main(apply: bool) -> None:
    print(("APPLIED" if apply else "DRY RUN (rolled back)") + ": " + str(expire_past_events(apply)))


if __name__ == "__main__":
    main(apply="--dry-run" not in sys.argv)
