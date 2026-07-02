"""Weekly digest — the second OUTBOUND re-engagement loop (after reminders).

Builds, per opted-in user, a single bundled roundup: what's newly listed at the venues
they follow (closes the 2.3 follow loop) + the best of this coming weekend in their city.
All read-only query composition; the Prefect flow in apps/worker formats + sends it.
"""
from datetime import datetime, timedelta, timezone

from sqlalchemy import and_, exists, func, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from core.domain.cities import city_by_slug, region_predicate_sql
from core.domain.codes import event_code
from core.db.models import Event, EventOccurrence, UserFavorite, UserFriend, UserMute, Venue
from core.db.models.ref.user import User
from core.db.models.ref.user_venue_follow import UserVenueFollow

_MSK = timezone(timedelta(hours=3))
# "New since the last weekly send" — an 8-day window (1-day overlap with the weekly cron)
# so a freshly-listed event is never missed at the boundary, and a long-running exhibition
# isn't re-announced every single week.
_NEW_WINDOW = timedelta(days=8)
# Effectively "all weekend candidates": the pool is fetched once per city and ranked in Python
# by rec:views, so this cap only bounds a pathological data state (Moscow is ~1.4k now). Ordered
# upcoming-first, so if the cap is ever hit it sheds plentiful ongoing runs — never the scarce
# timed weekend events (concerts/shows) users actually plan around.
_POOL_CAP = 3000


def weekend_window(now: datetime, offset_hours: int = 3) -> tuple[datetime, datetime, datetime, datetime]:
    """The upcoming Sat+Sun as (sat_date, sun_date, start_utc, end_exclusive_utc), computed in the
    CITY's local time (offset_hours; default MSK=+3). Multi-city: a +7 city's «this weekend» is its
    OWN Sat 00:00 → Mon 00:00 local, not clipped to Moscow's — else a Novosibirsk user's Saturday
    morning events fall outside the window and Moscow's late-Sunday spill in. The end is HALF-OPEN
    (local Monday 00:00, exclusive) → callers gate with `< end`."""
    tz = timezone(timedelta(hours=offset_hours))
    today = now.astimezone(tz).date()
    sat = today + timedelta(days=(5 - today.weekday()) % 7)  # Mon..Fri → coming Sat; Sat → today
    sun = sat + timedelta(days=1)
    mon = sun + timedelta(days=1)
    start = datetime(sat.year, sat.month, sat.day, 0, 0, 0, tzinfo=tz).astimezone(timezone.utc)
    end_exclusive = datetime(mon.year, mon.month, mon.day, 0, 0, 0, tzinfo=tz).astimezone(timezone.utc)
    return sat, sun, start, end_exclusive


def _city_offset(city_slug: str | None) -> int:
    """UTC offset (hours) for a city slug, defaulting to Moscow (+3) when unknown — so the weekend
    window is anchored to the user's own wall-clock."""
    cfg = city_by_slug(city_slug)
    return cfg.utc_offset_hours if cfg else 3


def _item(row) -> dict:
    """Shared row → bot-item dict (same column order in both queries)."""
    (event_id, title, category, display_no, cached_img, primary_img,
     date_start, date_end, price_min, price_max, venue_name, venue_city) = row
    return {
        "event_id": str(event_id),
        "title": title,
        "category": category,
        "code": event_code(display_no, venue_city),
        # Cover for the digest poster: the ORIGINAL source first (full-res, not the 900px cache),
        # so the poster tile isn't upscaled-blurry; fall back to our cached copy.
        "image": primary_img or cached_img or None,
        "date_start": date_start.isoformat() if date_start else None,
        "date_end": date_end.isoformat() if date_end else None,
        "price_min": float(price_min) if price_min is not None else None,
        "price_max": float(price_max) if price_max is not None else None,
        "venue": venue_name,
    }


_COLS = (
    Event.event_id,
    Event.canonical_title,
    Event.category,
    Event.display_no,
    Event.cached_image_url,
    Event.primary_image_url,
)


async def opted_in_users(db: AsyncSession, since: datetime, only_user_id: int | None = None) -> list[dict]:
    """Accounts that opted into the weekly digest (strictly opt-in; default off) AND haven't
    already been sent this week's digest — idempotency guard against redeploy/manual re-run/
    missed-run catchup: only users with no stamp, or a stamp older than this week's start.

    only_user_id задан (ТЕСТ из админки) → возвращаем СТРОГО этого пользователя, минуя opt-in/last-sent
    фильтры (чтобы превью всегда уходило). Адресат гардится повторно в _send_digest_impl."""
    base = select(User.telegram_user_id, User.city_slug, User.interests)
    if only_user_id is not None:
        stmt = base.where(User.telegram_user_id == only_user_id)
    else:
        stmt = base.where(
            User.notify_digest.is_(True),
            (User.last_digest_sent_at.is_(None)) | (User.last_digest_sent_at < since),
        )
    rows = (await db.execute(stmt)).all()
    return [
        {"user_id": r[0], "city_slug": r[1], "interests": list(r[2] or [])}
        for r in rows
    ]


async def new_at_followed_venues(db: AsyncSession, user_id: int, now: datetime, limit: int = 4) -> list[dict]:
    """Freshly-listed events still LIVE at the venues the user follows — the 'new at your places'
    section. New = Event.created_at within the weekly window; live = a session whose run hasn't
    ended (coalesce(date_end, date_start) >= now), so ongoing exhibitions/long runs are kept."""
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
            EventOccurrence.price_max,
            EventOccurrence.venue_id,
        )
        .distinct(EventOccurrence.event_id)
        # Live = run not yet ended; future-FIRST (mirroring reminders) so the rendered session
        # is the soonest UPCOMING one (or the ongoing one), not an earlier already-past date.
        .where(
            func.coalesce(EventOccurrence.date_end, EventOccurrence.date_start) >= now,
            EventOccurrence.venue_id.in_(venue_ids),
        )
        .order_by(
            EventOccurrence.event_id,
            (EventOccurrence.date_start < now).asc(),  # upcoming (false) before past (true)
            EventOccurrence.date_start.asc(),
        )
        .subquery()
    )
    rows = (
        await db.execute(
            select(*_COLS, soon.c.date_start, soon.c.date_end, soon.c.price_min, soon.c.price_max, Venue.name, Venue.city)
            .join(soon, soon.c.eid == Event.event_id)
            .join(Venue, Venue.venue_id == soon.c.venue_id)
            .where(Event.status == "active", Event.created_at >= now - _NEW_WINDOW)
            .order_by(soon.c.date_start.asc())
            .limit(limit)
        )
    ).all()
    return [_item(r) for r in rows]


async def friends_saved(db: AsyncSession, user_id: int, now: datetime, limit: int = 3, city_slug: str | None = None) -> list[dict]:
    """Events the user's FRIENDS saved that overlap the coming weekend — the «что сохранили друзья»
    digest section. Privacy-gated exactly like the in-app signal (accepted friend, friend not globally
    private, the favourite not per-item hidden, neither side muted). Ranked by how many friends saved
    each (DESC) then soonest. Each item carries `nfriends`. Empty → the section is skipped."""
    muted = exists().where(
        or_(
            and_(UserMute.user_id == user_id, UserMute.muted_user_id == UserFriend.friend_id),
            and_(UserMute.user_id == UserFriend.friend_id, UserMute.muted_user_id == user_id),
        )
    )
    counts = (
        await db.execute(
            select(UserFavorite.event_id, func.count(func.distinct(UserFriend.friend_id)).label("n"))
            .select_from(UserFriend)
            .join(UserFavorite, UserFavorite.telegram_user_id == UserFriend.friend_id)
            .join(User, User.telegram_user_id == UserFriend.friend_id)
            .where(
                UserFriend.user_id == user_id,
                UserFriend.status == "accepted",
                UserFavorite.hidden_from_friends.is_(False),
                User.friends_private.is_(False),
                ~muted,
            )
            .group_by(UserFavorite.event_id)
        )
    ).all()
    if not counts:
        return []
    nby = {r.event_id: int(r.n) for r in counts}
    _, _, start, end = weekend_window(now, _city_offset(city_slug))  # user's own-city weekend window
    soon = (
        select(
            EventOccurrence.event_id.label("eid"),
            EventOccurrence.date_start,
            EventOccurrence.date_end,
            EventOccurrence.price_min,
            EventOccurrence.price_max,
            EventOccurrence.venue_id,
        )
        .distinct(EventOccurrence.event_id)
        .where(
            EventOccurrence.event_id.in_(list(nby.keys())),
            EventOccurrence.date_start < end,
            func.coalesce(EventOccurrence.date_end, EventOccurrence.date_start) >= start,
        )
        .order_by(EventOccurrence.event_id, (EventOccurrence.date_start < now).asc(), EventOccurrence.date_start.asc())
        .subquery()
    )
    rows = (
        await db.execute(
            select(*_COLS, soon.c.date_start, soon.c.date_end, soon.c.price_min, soon.c.price_max, Venue.name, Venue.city)
            .join(soon, soon.c.eid == Event.event_id)
            .join(Venue, Venue.venue_id == soon.c.venue_id)
            .where(Event.status == "active")
        )
    ).all()
    items = [{**_item(r), "nfriends": nby.get(r[0], 0)} for r in rows]
    items.sort(key=lambda it: (-int(it.get("nfriends") or 0), it.get("date_start") or ""))
    return items[:limit]


async def weekend_pool(
    db: AsyncSession, city_slug: str | None, now: datetime, limit: int = _POOL_CAP
) -> list[dict]:
    """The weekend pool for a city — every active event whose run OVERLAPS the coming weekend,
    region-guarded, WITHOUT any interest filter. Fetched ONCE per distinct city (then ranked
    per-user in memory). An event overlaps the window if it starts before the (half-open) end
    AND its run hasn't finished before the start: date_start < end AND coalesce(end, start) >= start."""
    _, _, start, end = weekend_window(now, _city_offset(city_slug))  # weekend in the CITY's tz, not always MSK
    soon = (
        select(
            EventOccurrence.event_id.label("eid"),
            EventOccurrence.date_start,
            EventOccurrence.date_end,
            EventOccurrence.price_min,
            EventOccurrence.price_max,
            EventOccurrence.venue_id,
        )
        .distinct(EventOccurrence.event_id)
        .where(
            EventOccurrence.date_start < end,
            func.coalesce(EventOccurrence.date_end, EventOccurrence.date_start) >= start,
        )
        # Future-FIRST so the rendered session is the soonest weekend one (or ongoing), not a
        # past midnight date that happens to share the event_id.
        .order_by(
            EventOccurrence.event_id,
            (EventOccurrence.date_start < now).asc(),
            EventOccurrence.date_start.asc(),
        )
        .subquery()
    )
    q = (
        select(*_COLS, soon.c.date_start, soon.c.date_end, soon.c.price_min, soon.c.price_max, Venue.name, Venue.city)
        .join(soon, soon.c.eid == Event.event_id)
        .join(Venue, Venue.venue_id == soon.c.venue_id)
        # Region guard (the app's single source for it) — keeps the digest to the user's city.
        .where(Event.status == "active", text(region_predicate_sql(city_by_slug(city_slug))))
        # Upcoming-first, then soonest: a stable pre-order whose ONLY effect is which rows survive
        # the cap — keep the scarce timed weekend events over plentiful ongoing runs. The real
        # ranking (rec:views) is applied in rank_weekend, NOT popularity_score (a dead 0 column).
        .order_by((soon.c.date_start < now).asc(), soon.c.date_start.asc())
        .limit(limit)
    )
    rows = (await db.execute(q)).all()
    return [_item(r) for r in rows]


def rank_weekend(
    pool: list[dict],
    interests: list[str],
    exclude_ids: list[str],
    view_counts: dict,
    limit: int = 5,
) -> list[dict]:
    """Pure, per-user ranking of a (shared) weekend pool: PREFER the user's interests, drop anything
    already shown in their followed-venue list, sort by the LIVE rec:views signal (DESC) and soonest
    start (ASC). МЯГКИЙ фильтр: интересы — приоритет, а не отсечка; если профильных меньше limit,
    добиваем городским топом — иначе узкий пик интересов (напр. только «стендап») давал пустой/тощий
    weekend-блок и юзер получал молчащий дайджест при полном городе событий."""
    wanted = set(interests or [])
    skip = {x for x in (exclude_ids or []) if x}
    pool_ok = [it for it in pool if it["event_id"] not in skip]
    key = lambda it: (-int(view_counts.get(it["event_id"], 0) or 0), it.get("date_start") or "")  # noqa: E731
    matched = sorted([it for it in pool_ok if not wanted or (it.get("category") in wanted)], key=key)
    if len(matched) >= limit or not wanted:
        return matched[:limit]
    rest = sorted([it for it in pool_ok if it.get("category") not in wanted], key=key)
    return (matched + rest)[:limit]


async def mark_digest_sent(db: AsyncSession, user_ids: list[int]) -> None:
    """Stamp last_digest_sent_at=now() for the users Telegram actually answered for (one bulk
    UPDATE), so a redeploy/manual re-run/catchup this same week skips them — the per-send ledger."""
    ids = [int(x) for x in user_ids if x is not None]
    if not ids:
        return
    await db.execute(
        text("UPDATE ref.users SET last_digest_sent_at = now() WHERE telegram_user_id = ANY(:ids)"),
        {"ids": ids},
    )
