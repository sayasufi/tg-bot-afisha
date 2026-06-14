from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from apps.api.app.services.geo import reverse_city
from apps.api.app.services.telegram_auth import validate_init_data
from core.db.repositories.users import get_or_create_city, upsert_user, upsert_user_city
from core.db.session import SessionLocal

router = APIRouter(prefix="/v1/users", tags=["users"])


class LocationRequest(BaseModel):
    init_data: str
    lat: float
    lon: float


@router.post("/location")
def save_location(payload: LocationRequest):
    """Persist the user's home city, derived from their map geolocation.

    Replaces the old in-bot "choose a city" step: the Mini App sends the first
    location fix once, we reverse-geocode it to a city and store it on the user.
    """
    user = validate_init_data(payload.init_data)
    uid = user.get("id")
    if not uid:
        raise HTTPException(status_code=400, detail="no user id in init data")

    city_name = reverse_city(payload.lat, payload.lon)
    db = SessionLocal()
    try:
        upsert_user(db, int(uid), username=user.get("username"), first_name=user.get("first_name"))
        city_out = None
        if city_name:
            city = get_or_create_city(db, city_name)
            upsert_user_city(db, int(uid), city)
            city_out = city.name
        return {"ok": True, "city": city_out}
    finally:
        db.close()
