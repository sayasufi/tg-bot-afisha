from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.app.services.geo import reverse_city
from apps.api.app.services.telegram_auth import validate_init_data
from core.cities import city_by_name
from core.db.repositories.reminders import (
    cancel_reminder,
    list_reminder_ids,
    set_reminder,
    soonest_start,
)
from core.db.repositories.users import (
    add_favorites,
    get_settings,
    list_favorite_ids,
    set_favorite,
    update_settings,
    upsert_user,  # sync — for the low-frequency /location route
    upsert_user_async,
)
from core.db.session import SessionLocal, get_async_db

# Remind this long before the soonest session starts.
_REMINDER_LEAD = timedelta(hours=2)

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


class ReminderRequest(BaseModel):
    init_data: str
    event_id: str | None = None  # omit (with on) to just LIST the account's reminders
    on: bool | None = None


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
    """Persist the user's home city from their first map geolocation. Sync (not on the
    per-open hot path): it does a blocking reverse-geocode and runs once."""
    user, uid = _auth(payload.init_data)
    city_name = reverse_city(payload.lat, payload.lon)  # blocking httpx (cached)
    db = SessionLocal()
    try:
        u = upsert_user(db, uid, username=user.get("username"), first_name=user.get("first_name"))
        # Set the home city once into city_slug (the single column the app reads), but
        # never override an explicit pick from the city switcher.
        if city_name and not u.city_slug:
            cfg = city_by_name(city_name)
            if cfg:
                u.city_slug = cfg.slug
                db.add(u)
                db.commit()
        return {"ok": True, "city": city_name}
    finally:
        db.close()


@router.post("/favorites/sync")
async def sync_favorites(payload: FavoritesSyncRequest, db: AsyncSession = Depends(get_async_db)):
    """Return the account's favourites; on a device's FIRST sync, merge that device's local
    favourites in (once per account, gated by favorites_merged so a stale device can't
    resurrect removed ones). Deleted events are removed by the FK CASCADE — nothing to prune."""
    user, uid = _auth(payload.init_data)
    u = await upsert_user_async(db, uid, username=user.get("username"), first_name=user.get("first_name"))
    if payload.add and not u.favorites_merged:
        await add_favorites(db, uid, payload.add)
        u.favorites_merged = True
    await db.commit()
    return {"ids": await list_favorite_ids(db, uid)}


@router.post("/favorites")
async def toggle_favorite(payload: FavoriteToggleRequest, db: AsyncSession = Depends(get_async_db)):
    """Heart / un-heart one event for the account; returns the updated full list."""
    user, uid = _auth(payload.init_data)
    await upsert_user_async(db, uid, username=user.get("username"), first_name=user.get("first_name"))
    await set_favorite(db, uid, payload.event_id, payload.on)
    await db.commit()
    return {"ids": await list_favorite_ids(db, uid)}


@router.post("/reminders")
async def toggle_reminder(payload: ReminderRequest, db: AsyncSession = Depends(get_async_db)):
    """Arm / cancel a reminder for an event (the bot DMs you ~2h before it starts), or — with
    no event_id — just list the account's active reminders. Returns the current id list."""
    user, uid = _auth(payload.init_data)
    await upsert_user_async(db, uid, username=user.get("username"), first_name=user.get("first_name"))
    if payload.event_id is not None and payload.on is not None:
        if payload.on:
            start = await soonest_start(db, payload.event_id)
            if start is not None:  # no sessions → can't remind; silently no-op (bell won't arm)
                now = datetime.now(timezone.utc)
                # Fire ~2h before; clamp to the near future so imminent events still fire soon.
                fire_at = max(now + timedelta(seconds=45), start - _REMINDER_LEAD)
                await set_reminder(db, uid, payload.event_id, fire_at)
        else:
            await cancel_reminder(db, uid, payload.event_id)
    await db.commit()
    return {"ids": await list_reminder_ids(db, uid)}


@router.post("/settings")
async def user_settings(payload: SettingsRequest, db: AsyncSession = Depends(get_async_db)):
    """Read, or set-then-read, the account's app settings (theme, city, first-run flags)."""
    user, uid = _auth(payload.init_data)
    changing = any(
        v is not None for v in (payload.theme, payload.city, payload.onboarded, payload.coach, payload.swipe_seen)
    )
    if changing:
        # Only write the user row when actually changing a setting (a pure read on app
        # open shouldn't UPDATE+commit — favorites/sync already recorded the open).
        await upsert_user_async(db, uid, username=user.get("username"), first_name=user.get("first_name"))
        settings = await update_settings(
            db,
            uid,
            theme=payload.theme,
            city=payload.city,
            onboarded=payload.onboarded,
            coach=payload.coach,
            swipe_seen=payload.swipe_seen,
        )
        await db.commit()
    else:
        settings = await get_settings(db, uid)
    return {"settings": settings}
