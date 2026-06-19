from datetime import datetime, timedelta, timezone
from html import escape

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.app.services.geo import reverse_city
from apps.api.app.services.telegram_auth import validate_init_data
from core.cities import city_by_name
from core.config.settings import get_settings as get_app_settings
from core.db.repositories.reminders import (
    cancel_reminder,
    list_reminder_ids,
    set_reminder,
    soonest_start,
)
from core.db.repositories.users import (
    add_favorites,
    event_title,
    get_settings,
    list_favorite_ids,
    list_followed_venue_ids,
    list_going_ids,
    set_favorite,
    set_going,
    set_venue_follow,
    update_settings,
    upsert_user,  # sync — for the low-frequency /location route
    upsert_user_async,
    warm_interests_from,
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


class VenueFollowRequest(BaseModel):
    init_data: str
    venue_id: int | None = None  # omit (just LIST the followed venues) or include to toggle
    on: bool | None = None


class GoingRequest(BaseModel):
    init_data: str
    event_id: str | None = None  # omit (just LIST going ids) or include to confirm «Я иду»
    inviter_id: int | None = None  # the sharer who invited me (from the share deep-link), if any


class InvitedRequest(BaseModel):
    init_data: str
    inviter_id: int  # the sharer whose «Пойдём?» deep-link I opened


class SettingsRequest(BaseModel):
    init_data: str
    # Each field: a value sets it, None leaves it unchanged (the client only ever sets).
    theme: str | None = None
    city: str | None = None
    onboarded: bool | None = None
    coach: bool | None = None
    swipe_seen: bool | None = None
    interests: list[str] | None = None  # categories picked at onboarding (warms «Для тебя»)
    notify_digest: bool | None = None  # opt-in to the weekly digest DM (default off)


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


@router.post("/venues")
async def toggle_venue_follow(payload: VenueFollowRequest, db: AsyncSession = Depends(get_async_db)):
    """Follow / unfollow a venue (account-scoped, синхронно по устройствам), or — with no
    venue_id — just list the followed venue ids. Returns the current id list."""
    user, uid = _auth(payload.init_data)
    await upsert_user_async(db, uid, username=user.get("username"), first_name=user.get("first_name"))
    if payload.venue_id is not None and payload.on is not None:
        await set_venue_follow(db, uid, payload.venue_id, payload.on)
    await db.commit()
    return {"ids": await list_followed_venue_ids(db, uid)}


async def _notify_inviter(inviter_id: int, name: str, title: str | None, event_id: str) -> None:
    """DM the inviter that someone accepted their «Пойдём?» — best-effort, never blocks the
    response. The inviter started the bot (they shared from the Mini App), so the DM is allowed."""
    token = get_app_settings().telegram_bot_token
    if not token or not inviter_id:
        return
    text = f"🎉 <b>{escape(name or 'Кто-то')}</b> идёт с тобой\n{escape(title or 'на событие')}"
    markup = {"inline_keyboard": [[{"text": "смотреть →", "url": f"https://t.me/okrestmap_bot?startapp={event_id}"}]]}
    try:
        async with httpx.AsyncClient(timeout=8) as client:
            await client.post(
                f"https://api.telegram.org/bot{token}/sendMessage",
                json={"chat_id": int(inviter_id), "text": text, "parse_mode": "HTML",
                      "reply_markup": markup, "disable_web_page_preview": True},
            )
    except Exception:
        pass  # the going is already recorded; the nudge is best-effort


@router.post("/going")
async def toggle_going(payload: GoingRequest, db: AsyncSession = Depends(get_async_db)):
    """Confirm «Я иду» on an event (idempotent), or — with no event_id — just list going ids.
    On the FIRST confirmation that carries an inviter, DM the inviter that you're coming."""
    user, uid = _auth(payload.init_data)
    await upsert_user_async(db, uid, username=user.get("username"), first_name=user.get("first_name"))
    notify: tuple[int, str] | None = None
    if payload.event_id is not None:
        first_time = await set_going(db, uid, payload.event_id, payload.inviter_id)
        if first_time and payload.inviter_id and int(payload.inviter_id) != uid:
            title = await event_title(db, payload.event_id)
            notify = (int(payload.inviter_id), title or "")
    await db.commit()
    # Send the nudge AFTER the commit so the going is durable even if Telegram is slow/down.
    if notify:
        await _notify_inviter(notify[0], user.get("first_name") or "", notify[1], payload.event_id)
    return {"ids": await list_going_ids(db, uid)}


@router.post("/invited")
async def mark_invited(payload: InvitedRequest, db: AsyncSession = Depends(get_async_db)):
    """A «Пойдём?» invite was opened — attribute the inviter and, if this account is still cold,
    warm its feed from the inviter's taste (referral cold-start cure). Returns the interests now
    driving the feed so the Mini App can apply them this session."""
    user, uid = _auth(payload.init_data)
    await upsert_user_async(db, uid, username=user.get("username"), first_name=user.get("first_name"))
    interests = await warm_interests_from(db, uid, payload.inviter_id)
    await db.commit()
    return {"interests": interests}


@router.post("/settings")
async def user_settings(payload: SettingsRequest, db: AsyncSession = Depends(get_async_db)):
    """Read, or set-then-read, the account's app settings (theme, city, first-run flags)."""
    user, uid = _auth(payload.init_data)
    changing = any(
        v is not None
        for v in (payload.theme, payload.city, payload.onboarded, payload.coach, payload.swipe_seen, payload.interests, payload.notify_digest)
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
            interests=payload.interests,
            notify_digest=payload.notify_digest,
        )
        await db.commit()
    else:
        settings = await get_settings(db, uid)
    return {"settings": settings}
