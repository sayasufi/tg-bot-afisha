"""Saved-event reminders — the product's first re-engagement loop.

A user taps "Напомнить" on an event; we schedule a fire time (a couple hours before the
soonest session) and a Prefect sweep DMs them via the bot. All async (API + worker paths).
"""
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

# A reminder fires only within this many hours of its scheduled time. Past that it's stale: the event
# has effectively started, so a late "starts soon" DM is noise. This also caps catch-up after worker
# downtime and — crucially — stops a muted user's parked reminders from BURST-firing when they unmute.
_FIRE_GRACE_HOURS = 6

from core.codes import event_code
from core.db.models import Event, EventOccurrence, Venue
from core.db.models.ref.event_reminder import EventReminder
from core.db.models.ref.user import User


async def soonest_start(db: AsyncSession, event_id: str) -> datetime | None:
    """The soonest UPCOMING session start for an event (future-first); falls back to the
    soonest start overall (ongoing/just-started). None if the event has no sessions."""
    now = datetime.now(timezone.utc)
    future = await db.scalar(
        select(func.min(EventOccurrence.date_start)).where(
            EventOccurrence.event_id == event_id, EventOccurrence.date_start >= now
        )
    )
    if future is not None:
        return future
    return await db.scalar(select(func.min(EventOccurrence.date_start)).where(EventOccurrence.event_id == event_id))


async def set_reminder(db: AsyncSession, user_id: int, event_id: str, fire_at: datetime) -> None:
    """Arm (or re-arm) a reminder. Re-setting clears sent_at so it fires again."""
    await db.execute(
        pg_insert(EventReminder)
        .values(telegram_user_id=user_id, event_id=event_id, fire_at=fire_at, sent_at=None)
        .on_conflict_do_update(
            index_elements=[EventReminder.telegram_user_id, EventReminder.event_id],
            set_={"fire_at": fire_at, "sent_at": None},
        )
    )


async def cancel_reminder(db: AsyncSession, user_id: int, event_id: str) -> None:
    await db.execute(
        delete(EventReminder).where(
            EventReminder.telegram_user_id == user_id, EventReminder.event_id == event_id
        )
    )


async def list_reminder_ids(db: AsyncSession, user_id: int) -> list[str]:
    """Event ids with an active (not-yet-fired) reminder — drives the bell's on/off state."""
    rows = await db.execute(
        select(EventReminder.event_id).where(
            EventReminder.telegram_user_id == user_id, EventReminder.sent_at.is_(None)
        )
    )
    return [str(r[0]) for r in rows.all()]


async def due_reminders(db: AsyncSession, now: datetime, limit: int = 200) -> list[dict]:
    """Reminders whose time has come, for users who haven't muted reminders — joined to the
    event's soonest session + venue so the sweep can render the bot card with no N+1."""
    soon = (
        select(
            EventOccurrence.event_id.label("eid"),
            EventOccurrence.date_start,
            EventOccurrence.date_end,
            EventOccurrence.price_min,
            EventOccurrence.venue_id,
        )
        .distinct(EventOccurrence.event_id)
        # Future-FIRST, mirroring soonest_start (which set fire_at): describe the soonest
        # UPCOMING session, not the earliest overall. Otherwise a multi-session run (an
        # excursion/exhibition whose first date is in the past) gets a date_start <= now and
        # is wrongly captioned "идёт сейчас" when the next session is still hours away.
        .order_by(
            EventOccurrence.event_id,
            (EventOccurrence.date_start < now).asc(),  # upcoming (false) before past (true)
            EventOccurrence.date_start.asc(),
        )
        .subquery()
    )
    rows = (
        await db.execute(
            select(
                EventReminder.telegram_user_id,
                EventReminder.event_id,
                Event.canonical_title,
                Event.category,
                Event.display_no,
                Event.cached_image_url,
                Event.primary_image_url,
                soon.c.date_start,
                soon.c.date_end,
                soon.c.price_min,
                Venue.name,
                Venue.city,
            )
            .join(Event, Event.event_id == EventReminder.event_id)
            .join(User, User.telegram_user_id == EventReminder.telegram_user_id)
            .outerjoin(soon, soon.c.eid == EventReminder.event_id)
            .outerjoin(Venue, Venue.venue_id == soon.c.venue_id)
            .where(
                EventReminder.sent_at.is_(None),
                EventReminder.fire_at <= now,
                EventReminder.fire_at >= now - timedelta(hours=_FIRE_GRACE_HOURS),  # never fire stale
                User.notify_reminders.is_(True),
                Event.status == "active",
            )
            .limit(limit)
        )
    ).all()
    return [
        {
            "user_id": r[0],
            "event_id": str(r[1]),
            "title": r[2],
            "category": r[3],
            "code": event_code(r[4], r[11]),
            "image": r[5] or r[6] or None,  # cached cover (reliable) — raw-photo fallback
            "image_primary": r[6] or r[5] or None,  # ORIGINAL source — full-res for the branded cover
            "date_start": r[7].isoformat() if r[7] else None,
            "date_end": r[8].isoformat() if r[8] else None,
            "price_min": float(r[9]) if r[9] is not None else None,
            "venue": r[10],
        }
        for r in rows
    ]


async def reap_stale_reminders(db: AsyncSession, now: datetime) -> int:
    """Stamp (as sent) every undelivered reminder whose fire time passed more than the grace window
    ago — the user was muted, or the sweep was down. Without this they linger as sent_at=NULL and
    (a) burst-fire the instant a muted user unmutes, (b) keep the event's bell falsely armed forever."""
    cutoff = now - timedelta(hours=_FIRE_GRACE_HOURS)
    result = await db.execute(
        update(EventReminder)
        .where(EventReminder.sent_at.is_(None), EventReminder.fire_at < cutoff)
        .values(sent_at=func.now())
    )
    return result.rowcount or 0


async def mark_sent(db: AsyncSession, user_id: int, event_id: str) -> None:
    await db.execute(
        update(EventReminder)
        .where(EventReminder.telegram_user_id == user_id, EventReminder.event_id == event_id)
        .values(sent_at=func.now())
    )
