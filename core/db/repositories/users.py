import uuid
from datetime import datetime, timezone

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from core.db.models import City, Event, RawEvent, User, UserFavorite, Venue
from core.db.models.ref.user_venue_follow import UserVenueFollow
from core.db.repositories.ingestion import ensure_source, upsert_raw_event


def upsert_user(db: Session, telegram_user_id: int, username: str | None = None, first_name: str | None = None) -> User:
    """Create or refresh a bot user (profile + last-active). No db.refresh — callers don't
    read the server-default columns back, so it's a wasted round-trip."""
    user = db.get(User, telegram_user_id)
    if not user:
        user = User(telegram_user_id=telegram_user_id)
    user.username = username
    user.first_name = first_name
    user.last_active_at = datetime.now(timezone.utc)
    db.add(user)
    db.commit()
    return user


def get_or_create_city(db: Session, name: str, country: str = "RU") -> City:
    city = db.execute(select(City).where(City.name == name, City.country == country)).scalar_one_or_none()
    if city:
        return city
    city = City(name=name, country=country, timezone="Europe/Moscow")
    db.add(city)
    db.commit()
    db.refresh(city)
    return city


# --- API user/favourites/settings: async (burst endpoints on the async pool), and they
# do NOT commit — each route commits once for the whole request. The sync upsert_user /
# get_or_create_city above stay for the low-frequency /location route + the worker. ---


async def upsert_user_async(
    db: AsyncSession, telegram_user_id: int, username: str | None = None, first_name: str | None = None
) -> User:
    """Create or refresh a bot user (profile + last-active). No commit."""
    user = await db.get(User, telegram_user_id)
    if not user:
        user = User(telegram_user_id=telegram_user_id)
    user.username = username
    user.first_name = first_name
    user.last_active_at = datetime.now(timezone.utc)
    db.add(user)
    return user


def _settings_dict(user: User) -> dict:
    return {
        "theme": user.theme,
        "city": user.city_slug,
        "onboarded": user.onboarded,
        "coach": user.coach,
        "swipe_seen": user.swipe_seen,
        "interests": list(user.interests or []),
    }


async def get_settings(db: AsyncSession, telegram_user_id: int) -> dict:
    """The account's app settings (explicit columns), shaped for the Mini App."""
    user = await db.get(User, telegram_user_id)
    return _settings_dict(user) if user else {}


async def update_settings(
    db: AsyncSession,
    telegram_user_id: int,
    *,
    theme: str | None = None,
    city: str | None = None,
    onboarded: bool | None = None,
    coach: bool | None = None,
    swipe_seen: bool | None = None,
    interests: list[str] | None = None,
) -> dict:
    """Set the provided settings (None = leave unchanged; "" clears city). No commit."""
    user = await db.get(User, telegram_user_id)
    if not user:
        return {}
    if theme in ("light", "dark"):
        user.theme = theme
    if city is not None:
        user.city_slug = str(city)[:64] or None  # "" clears the explicit pick
    if onboarded is not None:
        user.onboarded = bool(onboarded)
    if coach is not None:
        user.coach = bool(coach)
    if swipe_seen is not None:
        user.swipe_seen = bool(swipe_seen)
    if interests is not None:
        # De-dupe, keep order, cap (the picker sends a small closed set of category
        # slugs; the recommend engine filters unknowns, so we just sanitise here).
        seen: list[str] = []
        for c in interests:
            c = str(c)[:32]
            if c and c not in seen:
                seen.append(c)
        user.interests = seen[:20]
    db.add(user)
    return _settings_dict(user)


async def list_favorite_ids(db: AsyncSession, telegram_user_id: int) -> list[str]:
    """Every event the user has hearted (as string UUIDs, for the Mini App)."""
    rows = (
        await db.execute(select(UserFavorite.event_id).where(UserFavorite.telegram_user_id == telegram_user_id))
    ).scalars().all()
    return [str(r) for r in rows]


async def set_favorite(db: AsyncSession, telegram_user_id: int, event_id: str, on: bool) -> None:
    """Heart / un-heart one event (no commit). Inserts only a still-existing event (FK)."""
    try:
        eid = uuid.UUID(str(event_id))
    except (ValueError, TypeError):
        return
    if on:
        if (await db.execute(select(Event.event_id).where(Event.event_id == eid))).first() is None:
            return  # event no longer exists — nothing to favourite
        await db.execute(
            pg_insert(UserFavorite.__table__)
            .values(telegram_user_id=telegram_user_id, event_id=eid)
            .on_conflict_do_nothing()
        )
    else:
        await db.execute(
            delete(UserFavorite).where(
                UserFavorite.telegram_user_id == telegram_user_id,
                UserFavorite.event_id == eid,
            )
        )


async def add_favorites(db: AsyncSession, telegram_user_id: int, event_ids: list[str]) -> None:
    """Bulk-add (one-time per-device merge), filtered to existing events (FK). No commit."""
    eids = []
    for e in event_ids[:500]:  # cap: a sane upper bound, never a real user's count
        try:
            eids.append(uuid.UUID(str(e)))
        except (ValueError, TypeError):
            continue
    if not eids:
        return
    existing = set((await db.execute(select(Event.event_id).where(Event.event_id.in_(eids)))).scalars().all())
    eids = [e for e in eids if e in existing]
    if not eids:
        return
    await db.execute(
        pg_insert(UserFavorite.__table__)
        .values([{"telegram_user_id": telegram_user_id, "event_id": e} for e in eids])
        .on_conflict_do_nothing()
    )


async def list_followed_venue_ids(db: AsyncSession, telegram_user_id: int) -> list[str]:
    """Venue ids the user follows (as strings, for the Mini App)."""
    rows = (
        await db.execute(select(UserVenueFollow.venue_id).where(UserVenueFollow.telegram_user_id == telegram_user_id))
    ).scalars().all()
    return [str(r) for r in rows]


async def set_venue_follow(db: AsyncSession, telegram_user_id: int, venue_id: int, on: bool) -> None:
    """Follow / unfollow one venue (no commit). Inserts only a still-existing venue (FK)."""
    try:
        vid = int(venue_id)
    except (ValueError, TypeError):
        return
    if on:
        if (await db.execute(select(Venue.venue_id).where(Venue.venue_id == vid))).first() is None:
            return  # venue no longer exists — nothing to follow
        await db.execute(
            pg_insert(UserVenueFollow.__table__)
            .values(telegram_user_id=telegram_user_id, venue_id=vid)
            .on_conflict_do_nothing()
        )
    else:
        await db.execute(
            delete(UserVenueFollow).where(
                UserVenueFollow.telegram_user_id == telegram_user_id,
                UserVenueFollow.venue_id == vid,
            )
        )


async def save_forward_message(db: AsyncSession, message_id: int, chat_id: int, payload: dict) -> RawEvent:
    # Forwarded posts enter the regular ingestion pipeline: the source name starts
    # with "telegram", so normalize_raw_events routes the text through LLM extraction.
    # Async (ingestion is async); the bot calls it with an AsyncSession.
    source = await ensure_source(db, name="telegram_forward", kind="telegram", base_url="https://t.me")
    raw_text = str(payload.get("text") or payload.get("caption") or "")
    return await upsert_raw_event(
        db,
        source_id=source.source_id,
        external_id=f"{chat_id}:{message_id}",
        payload=payload,
        raw_text=raw_text,
    )
