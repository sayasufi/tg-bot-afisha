"""Weekly digest — the second OUTBOUND re-engagement loop (after reminders).

Builds, per opted-in user, a single bundled roundup: what's newly listed at the venues
they follow (closes the 2.3 follow loop) + the best of this coming weekend in their city.
All read-only query composition; the Prefect flow in apps/worker formats + sends it.
"""
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from core.cities import city_by_slug, region_predicate_sql
from core.codes import event_code
from core.db.models import Event, EventOccurrence, Venue
from core.db.models.ref.user import User
from core.db.models.ref.user_venue_follow import UserVenueFollow

_MSK = timezone(timedelta(hours=3))
# "New since the last weekly send" — an 8-day window (1-day overlap with the weekly cron)
# so a freshly-listed event is never missed at the boundary, and a long-running exhibition
# isn't re-announced every single week.
_NEW_WINDOW = timedelta(days=8)


def weekend_window(now: datetime) -> tuple[datetime, datetime, datetime, datetime]:
    """The upcoming Sat+Sun as (sat_date, sun_date, start_utc, end_utc). Computed in Moscow
    time so 'this weekend' means the local calendar weekend; on Sat/Sun it's the current one."""
    today = now.astimezone(_MSK).date()
    sat = today + timedelta(days=(5 - today.weekday()) % 7)  # Mon..Fri → coming Sat; Sat → today
    sun = sat + timedelta(days=1)
    start = datetime(sat.year, sat.month, sat.day, 0, 0, 0, tzinfo=_MSK).astimezone(timezone.utc)
    end = datetime(sun.year, sun.month, sun.day, 23, 59, 59, tzinfo=_MSK).astimezone(timezone.utc)
    return sat, sun, start, end


def _item(row) -> dict:
    """Shared row → bot-item dict (same column order in both queries)."""
    event_id, title, category, display_no, date_start, date_end, price_min, venue_name, venue_city = row
    return {
        "event_id": str(event_id),
        "title": title,
        "category": category,
        "code": event_code(display_no, venue_city),
        "date_start": date_start.isoformat() if date_start else None,
        "date_end": date_end.isoformat() if date_end else None,
        "price_min": float(price_min) if price_min is not None else None,
        "venue": venue_name,
    }


_COLS = (
    Event.event_id,
    Event.canonical_title,
    Event.category,
    Event.display_no,
)


async def opted_in_users(db: AsyncSession) -> list[dict]:
    """Accounts that opted into the weekly digest (strictly opt-in; default off)."""
    rows = (
        await db.execute(
            select(User.telegram_user_id, User.city_slug, User.interests).where(User.notify_digest.is_(True))
        )
    ).all()
    return [{"user_id": r[0], "city_slug": r[1], "interests": list(r[2] or [])} for r in rows]


async def new_at_followed_venues(db: AsyncSession, user_id: int, now: datetime, limit: int = 4) -> list[dict]:
    """Freshly-listed UPCOMING events at the venues the user follows — the 'new at your places'
    section. New = Event.created_at within the weekly window; upcoming = a session still ahead."""
    venue_ids = (
        await db.execute(select(UserVenueFollow.venue_id).where(UserVenueFollow.telegram_user_id == user_id))
    ).scalars().all()
    if not venue_ids:
        return []
    soon = (
        select(
            EventOccurrence.event_id.label("eid"),
            EventOccurrence.date_start,
            EventOccurrence.date_end,
            EventOccurrence.price_min,
            EventOccurrence.venue_id,
        )
        .distinct(EventOccurrence.event_id)
        .where(EventOccurrence.date_start >= now, EventOccurrence.venue_id.in_(venue_ids))
        .order_by(EventOccurrence.event_id, EventOccurrence.date_start.asc())
        .subquery()
    )
    rows = (
        await db.execute(
            select(*_COLS, soon.c.date_start, soon.c.date_end, soon.c.price_min, Venue.name, Venue.city)
            .join(soon, soon.c.eid == Event.event_id)
            .join(Venue, Venue.venue_id == soon.c.venue_id)
            .where(Event.status == "active", Event.created_at >= now - _NEW_WINDOW)
            .order_by(soon.c.date_start.asc())
            .limit(limit)
        )
    ).all()
    return [_item(r) for r in rows]


async def weekend_events(
    db: AsyncSession, city_slug: str | None, interests: list[str], exclude_ids: list[str], now: datetime, limit: int = 5
) -> list[dict]:
    """The best of this coming weekend in the user's city — popularity-first, filtered to the
    user's interests if they picked any, and minus anything already in the followed-venue list."""
    _, _, start, end = weekend_window(now)
    soon = (
        select(
            EventOccurrence.event_id.label("eid"),
            EventOccurrence.date_start,
            EventOccurrence.date_end,
            EventOccurrence.price_min,
            EventOccurrence.venue_id,
        )
        .distinct(EventOccurrence.event_id)
        .where(EventOccurrence.date_start >= start, EventOccurrence.date_start <= end)
        .order_by(EventOccurrence.event_id, EventOccurrence.date_start.asc())
        .subquery()
    )
    q = (
        select(*_COLS, soon.c.date_start, soon.c.date_end, soon.c.price_min, Venue.name, Venue.city)
        .join(soon, soon.c.eid == Event.event_id)
        .join(Venue, Venue.venue_id == soon.c.venue_id)
        # Region guard (the app's single source for it) — keeps the digest to the user's city.
        .where(Event.status == "active", text(region_predicate_sql(city_by_slug(city_slug))))
    )
    if interests:
        q = q.where(Event.category.in_(interests))
    exclude = [uuid.UUID(x) for x in exclude_ids if x]
    if exclude:
        q = q.where(Event.event_id.not_in(exclude))
    q = q.order_by(Event.popularity_score.desc(), soon.c.date_start.asc()).limit(limit)
    rows = (await db.execute(q)).all()
    return [_item(r) for r in rows]


async def build_digest(db: AsyncSession, user: dict, now: datetime) -> tuple[list[dict], list[dict]]:
    """(followed-venue items, weekend items) for one opted-in user. Either may be empty; the
    caller skips the send when both are."""
    venue_items = await new_at_followed_venues(db, user["user_id"], now)
    weekend_items = await weekend_events(
        db, user.get("city_slug"), user.get("interests") or [], [e["event_id"] for e in venue_items], now
    )
    return venue_items, weekend_items
