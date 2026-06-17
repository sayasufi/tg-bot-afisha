import uuid
from datetime import datetime, timezone

from sqlalchemy import delete, select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from core.db.models import City, RawEvent, User, UserFavorite
from core.db.repositories.ingestion import ensure_source, upsert_raw_event


def upsert_user(db: Session, telegram_user_id: int, username: str | None = None, first_name: str | None = None) -> User:
    """Create or refresh a bot user (profile + last-active)."""
    user = db.get(User, telegram_user_id)
    if not user:
        user = User(telegram_user_id=telegram_user_id)
    user.username = username
    user.first_name = first_name
    user.last_active_at = datetime.now(timezone.utc)
    db.add(user)
    db.commit()
    db.refresh(user)
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


def upsert_user_city(db: Session, telegram_user_id: int, city: City) -> User:
    user = db.get(User, telegram_user_id)
    if not user:
        user = User(telegram_user_id=telegram_user_id, city_id=city.city_id)
    else:
        user.city_id = city.city_id
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def get_settings(db: Session, telegram_user_id: int) -> dict:
    """The account's app settings (explicit columns), shaped for the Mini App."""
    user = db.get(User, telegram_user_id)
    if not user:
        return {}
    return {
        "theme": user.theme,
        "city": user.city_slug,
        "onboarded": user.onboarded,
        "coach": user.coach,
        "swipe_seen": user.swipe_seen,
    }


def update_settings(
    db: Session,
    telegram_user_id: int,
    *,
    theme: str | None = None,
    city: str | None = None,
    onboarded: bool | None = None,
    coach: bool | None = None,
    swipe_seen: bool | None = None,
) -> dict:
    """Set the provided settings (None = leave unchanged); returns the full set.
    The client only ever sets values (never clears), so None means 'not provided'."""
    user = db.get(User, telegram_user_id)
    if not user:
        return {}
    if theme in ("light", "dark"):
        user.theme = theme
    if city:
        user.city_slug = str(city)[:64]
    if onboarded is not None:
        user.onboarded = bool(onboarded)
    if coach is not None:
        user.coach = bool(coach)
    if swipe_seen is not None:
        user.swipe_seen = bool(swipe_seen)
    db.add(user)
    db.commit()
    return get_settings(db, telegram_user_id)


def list_favorite_ids(db: Session, telegram_user_id: int) -> list[str]:
    """Every event the user has hearted (as string UUIDs, for the Mini App)."""
    rows = (
        db.execute(select(UserFavorite.event_id).where(UserFavorite.telegram_user_id == telegram_user_id))
        .scalars()
        .all()
    )
    return [str(r) for r in rows]


def set_favorite(db: Session, telegram_user_id: int, event_id: str, on: bool) -> None:
    """Heart (on) or un-heart (off) a single event. Idempotent."""
    try:
        eid = uuid.UUID(str(event_id))
    except (ValueError, TypeError):
        return
    if on:
        db.execute(
            pg_insert(UserFavorite.__table__)
            .values(telegram_user_id=telegram_user_id, event_id=eid)
            .on_conflict_do_nothing()
        )
    else:
        db.execute(
            delete(UserFavorite).where(
                UserFavorite.telegram_user_id == telegram_user_id,
                UserFavorite.event_id == eid,
            )
        )
    db.commit()


def prune_stale_favorites(db: Session, telegram_user_id: int) -> None:
    """Drop favourites whose event no longer exists (removed by the dedup/prune pipeline)
    or has no future/ongoing occurrence — so the count and the list only ever reflect
    events the user can still go to. There's no FK to events.events on purpose; this is
    where stale references get cleaned up (on every sync)."""
    db.execute(
        text(
            "DELETE FROM ref.user_favorites uf "
            "WHERE uf.telegram_user_id = :uid "
            "AND NOT EXISTS ("
            "  SELECT 1 FROM events.event_occurrences o "
            "  WHERE o.event_id = uf.event_id "
            "  AND coalesce(o.date_end, o.date_start) >= date_trunc('day', now())"
            ")"
        ),
        {"uid": telegram_user_id},
    )
    db.commit()


def add_favorites(db: Session, telegram_user_id: int, event_ids: list[str]) -> None:
    """Bulk-add (used once per device to merge its local favourites into the account)."""
    eids = []
    for e in event_ids[:500]:  # cap: a sane upper bound, never a real user's count
        try:
            eids.append(uuid.UUID(str(e)))
        except (ValueError, TypeError):
            continue
    if not eids:
        return
    db.execute(
        pg_insert(UserFavorite.__table__)
        .values([{"telegram_user_id": telegram_user_id, "event_id": e} for e in eids])
        .on_conflict_do_nothing()
    )
    db.commit()


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
