"""Event lifecycle: mark events whose last occurrence has already passed as
``expired`` so the map, list, search and recommendations (all of which filter
``status='active'``) stop showing them — and revive any event that has since
gained an upcoming occurrence.

An event is "live" while it has at least one occurrence whose Moscow *end day* is
today or later, so a same-day event stays visible until the end of its day, and a
multi-day run stays until it finishes. Events with no occurrence at all are not
live and get expired too. Idempotent — safe to run on a schedule.

Run:      docker compose -p tg-bot-afisha exec -T prefect-serve python -m scripts.expire_past_events
Preview:  ... python -m scripts.expire_past_events --dry-run
"""
import sys

from sqlalchemy import text

from core.db.session import SessionLocal

_HAS_LIVE_OCC = """
exists (
  select 1 from events.event_occurrences o
  where o.event_id = e.event_id
    and coalesce((o.date_end   at time zone 'Europe/Moscow')::date,
                 (o.date_start at time zone 'Europe/Moscow')::date)
        >= (now() at time zone 'Europe/Moscow')::date
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
