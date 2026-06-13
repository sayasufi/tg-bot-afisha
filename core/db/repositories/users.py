from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from core.db.models import City, RawEvent, User
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


def save_forward_message(db: Session, message_id: int, chat_id: int, payload: dict) -> RawEvent:
    # Forwarded posts enter the regular ingestion pipeline: the source name starts
    # with "telegram", so normalize_raw_events routes the text through LLM extraction.
    source = ensure_source(db, name="telegram_forward", kind="telegram", base_url="https://t.me")
    raw_text = str(payload.get("text") or payload.get("caption") or "")
    return upsert_raw_event(
        db,
        source_id=source.source_id,
        external_id=f"{chat_id}:{message_id}",
        payload=payload,
        raw_text=raw_text,
    )
