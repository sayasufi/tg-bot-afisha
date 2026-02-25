from sqlalchemy import select
from sqlalchemy.orm import Session

from core.db.models import City, IngestInbox, User


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


def save_forward_message(db: Session, message_id: int, chat_id: int, payload: dict) -> IngestInbox:
    row = IngestInbox(telegram_message_id=message_id, chat_id=chat_id, payload_json=payload, processed=False)
    db.add(row)
    db.commit()
    db.refresh(row)
    return row
