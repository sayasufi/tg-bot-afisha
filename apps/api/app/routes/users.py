from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from apps.api.app.services.geo import reverse_city
from apps.api.app.services.telegram_auth import validate_init_data
from core.db.repositories.users import (
    add_favorites,
    get_or_create_city,
    get_settings,
    list_favorite_ids,
    set_favorite,
    update_settings,
    upsert_user,
    upsert_user_city,
)
from core.db.session import SessionLocal

router = APIRouter(prefix="/v1/users", tags=["users"])


class LocationRequest(BaseModel):
    init_data: str
    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)


class FavoritesSyncRequest(BaseModel):
    init_data: str
    add: list[str] = []  # this device's local favourites to merge in (once, on first sync)


class FavoriteToggleRequest(BaseModel):
    init_data: str
    event_id: str
    on: bool


class SettingsRequest(BaseModel):
    init_data: str
    # Each field: a value sets it, None leaves it unchanged (the client only ever sets).
    theme: str | None = None
    city: str | None = None
    onboarded: bool | None = None
    coach: bool | None = None
    swipe_seen: bool | None = None


def _auth(init_data: str) -> tuple[dict, int]:
    """Verify the Telegram signature and return (user dict, telegram user id)."""
    user = validate_init_data(init_data)
    uid = user.get("id")
    if not uid:
        raise HTTPException(status_code=400, detail="no user id in init data")
    return user, int(uid)


@router.post("/location")
def save_location(payload: LocationRequest):
    """Persist the user's home city, derived from their map geolocation.

    Replaces the old in-bot "choose a city" step: the Mini App sends the first
    location fix once, we reverse-geocode it to a city and store it on the user.
    """
    user, uid = _auth(payload.init_data)
    city_name = reverse_city(payload.lat, payload.lon)
    db = SessionLocal()
    try:
        upsert_user(db, uid, username=user.get("username"), first_name=user.get("first_name"))
        city_out = None
        if city_name:
            city = get_or_create_city(db, city_name)
            upsert_user_city(db, uid, city)
            city_out = city.name
        return {"ok": True, "city": city_out}
    finally:
        db.close()


@router.post("/favorites/sync")
def sync_favorites(payload: FavoritesSyncRequest):
    """Return the account's favourites; on a device's first sync, merge that device's
    local favourites in (one-time migration from the old per-device localStorage). Deleted
    events are removed by the FK (ON DELETE CASCADE), so there's nothing to prune here."""
    user, uid = _auth(payload.init_data)
    db = SessionLocal()
    try:
        # Records the open (last_active) + creates the row the merge insert needs.
        upsert_user(db, uid, username=user.get("username"), first_name=user.get("first_name"))
        if payload.add:
            add_favorites(db, uid, payload.add)
        return {"ids": list_favorite_ids(db, uid)}
    finally:
        db.close()


@router.post("/favorites")
def toggle_favorite(payload: FavoriteToggleRequest):
    """Heart / un-heart one event for the account; returns the updated full list."""
    user, uid = _auth(payload.init_data)
    db = SessionLocal()
    try:
        upsert_user(db, uid, username=user.get("username"), first_name=user.get("first_name"))
        set_favorite(db, uid, payload.event_id, payload.on)
        return {"ids": list_favorite_ids(db, uid)}
    finally:
        db.close()


@router.post("/settings")
def user_settings(payload: SettingsRequest):
    """Read, or set-then-read, the account's app settings (theme, city, first-run flags)."""
    user, uid = _auth(payload.init_data)
    db = SessionLocal()
    try:
        changing = any(
            v is not None for v in (payload.theme, payload.city, payload.onboarded, payload.coach, payload.swipe_seen)
        )
        if changing:
            # Only write the user row when actually changing a setting (a pure read on app
            # open shouldn't UPDATE+commit — favorites/sync already recorded the open).
            upsert_user(db, uid, username=user.get("username"), first_name=user.get("first_name"))
            settings = update_settings(
                db,
                uid,
                theme=payload.theme,
                city=payload.city,
                onboarded=payload.onboarded,
                coach=payload.coach,
                swipe_seen=payload.swipe_seen,
            )
        else:
            settings = get_settings(db, uid)
        return {"settings": settings}
    finally:
        db.close()
