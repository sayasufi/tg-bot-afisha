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
from core.invite import sign_friend, verify as invite_verify, verify_friend
from core.db.repositories.reminders import (
    arm_reminder_if_unsent,
    cancel_reminder,
    list_reminder_ids,
    set_reminder,
    soonest_future_start,
)
from core.db.repositories.friends import (
    accept_request,
    befriend,
    count_friends,
    decline_request,
    friend_profile,
    friends_who_favorited,
    list_friends,
    list_requests,
    my_hidden_event_ids,
    remove_friend,
    set_favorite_hidden,
    set_mute,
    user_card,
)
from core.db.repositories.users import (
    add_favorites,
    event_title,
    get_settings,
    list_favorite_ids,
    list_followed_venue_ids,
    set_favorite,
    set_venue_follow,
    update_settings,
    upsert_user,  # sync — for the low-frequency /location route
    upsert_user_async,
    warm_interests_from,
)
from core.db.session import SessionLocal, get_async_db
from core.redis import get_redis

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
    inviter_id: int | None = None  # set when favouriting via a «Пойдём?» invite (→ DM the inviter)
    sig: str | None = None  # HMAC over (event_id, inviter_id) — proves the inviter wasn't forged


class ReminderRequest(BaseModel):
    init_data: str
    event_id: str | None = None  # omit (with on) to just LIST the account's reminders
    on: bool | None = None


class VenueFollowRequest(BaseModel):
    init_data: str
    venue_id: int | None = None  # omit (just LIST the followed venues) or include to toggle
    on: bool | None = None


class InvitedRequest(BaseModel):
    init_data: str
    inviter_id: int  # the sharer whose «Пойдём?» deep-link I opened
    event_id: str | None = None  # the invited event — needed to verify the signature
    sig: str | None = None  # HMAC over (event_id, inviter_id) — gates the referral warm-start


class SettingsRequest(BaseModel):
    init_data: str
    # Each field: a value sets it, None leaves it unchanged (the client only ever sets).
    theme: str | None = None
    city: str | None = None
    onboarded: bool | None = None
    coach: bool | None = None
    swipe_seen: bool | None = None
    interests: list[str] | None = None  # categories picked at onboarding (warms «Для тебя»)
    notify_reminders: bool | None = None  # global mute for the per-event reminder DMs (default on)
    notify_digest: bool | None = None  # opt-in to the weekly digest DM (default off)
    friends_private: bool | None = None  # hide ALL my favourites from friends (default off)


class FriendsFavoritedRequest(BaseModel):
    init_data: str
    event_ids: list[str] = []  # which events to resolve «friends who saved this» for


class FriendsRequest(BaseModel):
    init_data: str
    action: str | None = None  # 'accept'|'decline'|'remove'|'block'|'unblock' — omit to LIST friends+requests
    friend_id: int | None = None


class HideFavoriteRequest(BaseModel):
    init_data: str
    event_id: str
    hidden: bool  # hide this favourite from friends (per-item privacy)


class FriendProfileRequest(BaseModel):
    init_data: str
    friend_id: int


class FriendLinkRequest(BaseModel):
    init_data: str


class FriendInviteRequest(BaseModel):
    init_data: str
    inviter_id: int  # the owner of the «add me as a friend» link
    sig: str  # HMAC(friend:<inviter_id>) — proves the link is genuine


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
    """Heart / un-heart one event. Favouriting also arms its pre-event reminder (unless reminders are
    globally muted); accepting a signed «Пойдём?» invite additionally makes the inviter a mutual FRIEND
    instantly (accepting is the consent) and DMs them once."""
    user, uid = _auth(payload.init_data)
    await upsert_user_async(
        db, uid, username=user.get("username"), first_name=user.get("first_name"), photo_url=user.get("photo_url")
    )
    await set_favorite(db, uid, payload.event_id, payload.on)
    notify: tuple[int, str] | None = None
    friend = "none"  # friendship outcome of this accept: 'accepted' (mutual friends now) / 'none'
    first_friend = False
    if payload.on:
        await _arm_reminder(db, uid, payload.event_id)
        # Invite accept via a genuine SIGNED «Пойдём?» link → become mutual friends with the inviter NOW
        # (accepting is the consent — no confirmation). DM the inviter once (Redis-deduped). Independent
        # of whether the event was already favourited. Never self / muted / non-existent inviter.
        if (
            payload.inviter_id
            and int(payload.inviter_id) != uid
            and invite_verify(payload.event_id, payload.inviter_id, payload.sig)
        ):
            inviter = int(payload.inviter_id)
            friend = await befriend(db, uid, inviter, src_event_id=payload.event_id)
            if friend == "accepted" and await count_friends(db, uid) == 1:
                first_friend = True  # my first friend, formed instantly → one-time disclosure
            recip = await get_settings(db, inviter)
            if (
                recip
                and recip.get("notify_reminders") is not False
                and await _invite_dm_once(uid, payload.event_id, inviter)
            ):
                title = await event_title(db, payload.event_id)
                notify = (inviter, title or "")
    else:
        await cancel_reminder(db, uid, payload.event_id)  # un-fav → drop its reminder
    await db.commit()
    if notify:
        await _notify_inviter(notify[0], user.get("first_name") or "", notify[1], payload.event_id)
    return {"ids": await list_favorite_ids(db, uid), "friend": friend, "first_friend": first_friend}


@router.post("/reminders")
async def toggle_reminder(payload: ReminderRequest, db: AsyncSession = Depends(get_async_db)):
    """Arm / cancel a reminder for an event (the bot DMs you ~2h before it starts), or — with
    no event_id — just list the account's active reminders. Returns the current id list."""
    user, uid = _auth(payload.init_data)
    await upsert_user_async(db, uid, username=user.get("username"), first_name=user.get("first_name"))
    if payload.event_id is not None and payload.on is not None:
        if payload.on:
            start = await soonest_future_start(db, payload.event_id)
            if start is not None:  # no UPCOMING session → can't remind; silently no-op
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


@router.post("/friends-favorited")
async def get_friends_favorited(payload: FriendsFavoritedRequest, db: AsyncSession = Depends(get_async_db)):
    """For the given events, which of MY friends favourited each — the «друг сохранил это» signal in the
    event sheet. Read-only (no commit). Privacy is enforced in the query (accepted edge, not private, not
    hidden, not muted). Also returns which of these I've hidden, so the sheet's per-item toggle is correct."""
    _user, uid = _auth(payload.init_data)
    ids = payload.event_ids[:250]  # the map sends the visible pins at detail zoom; the sheet sends 1
    return {
        "friends": await friends_who_favorited(db, uid, ids),
        "hidden": await my_hidden_event_ids(db, uid, ids),
        "has_friends": await count_friends(db, uid) > 0,
    }


@router.post("/friends")
async def manage_friends(payload: FriendsRequest, db: AsyncSession = Depends(get_async_db)):
    """List my friends + incoming requests, or act on one: accept / decline a pending request, remove
    (unfriend, both edges), block (mute + unfriend) / unblock. Returns the resulting friends + requests,
    and `first_friend` when an accept created my very first friendship (→ one-time disclosure)."""
    _user, uid = _auth(payload.init_data)
    first_friend = False
    if payload.action and payload.friend_id and int(payload.friend_id) != uid:
        other = int(payload.friend_id)
        if payload.action == "accept":
            if await accept_request(db, uid, other) and await count_friends(db, uid) == 1:
                first_friend = True
        elif payload.action == "decline":
            await decline_request(db, uid, other)
        elif payload.action == "remove":
            await remove_friend(db, uid, other)
        elif payload.action == "block":
            await set_mute(db, uid, other, True)
        elif payload.action == "unblock":
            await set_mute(db, uid, other, False)
        await db.commit()
    return {
        "friends": await list_friends(db, uid),
        "requests": await list_requests(db, uid),
        "first_friend": first_friend,
    }


@router.post("/favorites/hide")
async def hide_favorite(payload: HideFavoriteRequest, db: AsyncSession = Depends(get_async_db)):
    """Hide / unhide one of my favourites from friends (per-item privacy). No-op if it isn't favourited."""
    _user, uid = _auth(payload.init_data)
    await set_favorite_hidden(db, uid, payload.event_id, payload.hidden)
    await db.commit()
    return {"ok": True}


@router.post("/friend-profile")
async def get_friend_profile(payload: FriendProfileRequest, db: AsyncSession = Depends(get_async_db)):
    """A friend's profile — «что он лайкнул» (their visible favourite event_ids + identity). Read-only.
    403 unless we're mutual accepted friends and unblocked (you can't read a stranger's taste by id)."""
    _user, uid = _auth(payload.init_data)
    prof = await friend_profile(db, uid, int(payload.friend_id))
    if prof is None:
        raise HTTPException(status_code=403, detail="not a friend")
    return prof


@router.post("/friend-link")
async def make_friend_link(payload: FriendLinkRequest):
    """A personal «добавь меня в друзья» deep-link for the current account (sign_friend) — durable +
    reshareable, separate from event invites. Opening it shows an accept screen, then instant friends."""
    _user, uid = _auth(payload.init_data)
    return {"link": f"https://t.me/okrestmap_bot?startapp=friend_{uid}_{sign_friend(uid)}"}


@router.post("/friend-peek")
async def peek_friend_link(payload: FriendInviteRequest, db: AsyncSession = Depends(get_async_db)):
    """Who is behind an «add me» link — name/@username/photo for the accept screen. Gated on a valid sig
    (you can't peek an arbitrary id's card), and never self."""
    _user, uid = _auth(payload.init_data)
    if int(payload.inviter_id) == uid or not verify_friend(payload.inviter_id, payload.sig):
        raise HTTPException(status_code=403, detail="bad friend link")
    card = await user_card(db, int(payload.inviter_id))
    if not card:
        raise HTTPException(status_code=404, detail="no such user")
    return card


@router.post("/friend-accept")
async def accept_friend_link(payload: FriendInviteRequest, db: AsyncSession = Depends(get_async_db)):
    """Accept an «add me» link → instant mutual friends (accepting IS the consent). DMs the link owner
    once. 403 on a forged/self link. Returns the new friend's card + first_friend (one-time disclosure)."""
    user, uid = _auth(payload.init_data)
    await upsert_user_async(
        db, uid, username=user.get("username"), first_name=user.get("first_name"), photo_url=user.get("photo_url")
    )
    if int(payload.inviter_id) == uid or not verify_friend(payload.inviter_id, payload.sig):
        raise HTTPException(status_code=403, detail="bad friend link")
    inviter = int(payload.inviter_id)
    friend = await befriend(db, uid, inviter)
    first_friend = friend == "accepted" and await count_friends(db, uid) == 1
    card = await user_card(db, inviter)
    notify = False
    if friend == "accepted":
        recip = await get_settings(db, inviter)
        if recip and recip.get("notify_reminders") is not False and await _friend_add_dm_once(inviter, uid):
            notify = True
    await db.commit()
    if notify:
        await _notify_friend_added(inviter, user.get("first_name") or "")
    return {"friend": card, "first_friend": first_friend, "added": friend == "accepted"}


async def _notify_inviter(inviter_id: int, name: str, title: str | None, event_id: str) -> None:
    """DM the inviter that someone accepted their «Пойдём?» (added it to favourites) — best-effort,
    never blocks the response. The inviter started the bot (they shared from the Mini App)."""
    token = get_app_settings().telegram_bot_token
    if not token or not inviter_id:
        return
    text = (
        f"🎉 <b>{escape(name or 'Кто-то')}</b> принял твоё приглашение\n{escape(title or 'на событие')}\n\n"
        "Теперь вы друзья — смотрите, что друг у друга в избранном."
    )
    markup = {"inline_keyboard": [[{"text": "смотреть →", "url": f"https://t.me/okrestmap_bot?startapp={event_id}"}]]}
    try:
        async with httpx.AsyncClient(timeout=8) as client:
            await client.post(
                f"https://api.telegram.org/bot{token}/sendMessage",
                json={"chat_id": int(inviter_id), "text": text, "parse_mode": "HTML",
                      "reply_markup": markup, "disable_web_page_preview": True},
            )
    except Exception:
        pass  # the favourite is already recorded; the nudge is best-effort


async def _arm_reminder(db: AsyncSession, uid: int, event_id: str) -> None:
    """Arm the pre-event reminder for one favourited event — UNLESS reminders are globally muted, or the
    event has no UPCOMING session (never remind about something that already happened). Reminders are
    now driven by favourites (no per-event bell)."""
    settings = await get_settings(db, uid)
    if settings.get("notify_reminders") is False:
        return
    start = await soonest_future_start(db, event_id)
    if start is None:
        return
    now = datetime.now(timezone.utc)
    await arm_reminder_if_unsent(db, uid, event_id, max(now + timedelta(seconds=45), start - _REMINDER_LEAD))


async def _arm_all_favorite_reminders(db: AsyncSession, uid: int) -> None:
    """Arm reminders for every favourited event with an UPCOMING session — run when the user switches the
    profile notifications toggle ON, so reminders cover everything saved while it was off. Non-destructive
    (arm_reminder_if_unsent): never re-fires a reminder that already delivered, never arms a past event."""
    now = datetime.now(timezone.utc)
    for fid in await list_favorite_ids(db, uid):
        start = await soonest_future_start(db, fid)
        if start is not None:
            await arm_reminder_if_unsent(db, uid, fid, max(now + timedelta(seconds=45), start - _REMINDER_LEAD))


async def _invite_dm_once(invitee_id: int, event_id: str, inviter_id: int) -> bool:
    """Redis NX guard: True only the first time we'd DM `inviter_id` about `invitee_id` accepting the
    invite to `event_id` — so a fav/un-fav/re-fav loop can't re-spam. Best-effort (Redis down → allow)."""
    client = get_redis(decode=True)
    if client is None:
        return True
    try:
        return bool(await client.set(f"invite:dm:{inviter_id}:{invitee_id}:{event_id}", "1", nx=True, ex=120 * 24 * 3600))
    except Exception:
        return True


async def _friend_add_dm_once(inviter_id: int, invitee_id: int) -> bool:
    """Redis NX: True only the first time we'd DM `inviter_id` that `invitee_id` used their «add me»
    friend-link — so re-opening the link can't re-spam. Best-effort (Redis down → allow)."""
    client = get_redis(decode=True)
    if client is None:
        return True
    try:
        return bool(await client.set(f"friend:dm:add:{inviter_id}:{invitee_id}", "1", nx=True, ex=365 * 24 * 3600))
    except Exception:
        return True


async def _notify_friend_added(inviter_id: int, name: str) -> None:
    """DM the friend-link owner that someone added them via it (now friends) — best-effort, never blocks."""
    token = get_app_settings().telegram_bot_token
    if not token or not inviter_id:
        return
    text = f"👋 <b>{escape(name or 'Кто-то')}</b> добавил тебя в друзья по твоей ссылке"
    markup = {"inline_keyboard": [[{"text": "друзья →", "url": "https://t.me/okrestmap_bot?startapp=friends"}]]}
    try:
        async with httpx.AsyncClient(timeout=8) as client:
            await client.post(
                f"https://api.telegram.org/bot{token}/sendMessage",
                json={"chat_id": int(inviter_id), "text": text, "parse_mode": "HTML",
                      "reply_markup": markup, "disable_web_page_preview": True},
            )
    except Exception:
        pass  # the friendship is recorded; the nudge is best-effort


@router.post("/invited")
async def mark_invited(payload: InvitedRequest, db: AsyncSession = Depends(get_async_db)):
    """A «Пойдём?» invite was opened — attribute the inviter and, if this account is still cold,
    warm its feed from the inviter's taste (referral cold-start cure). Returns the interests now
    driving the feed so the Mini App can apply them this session."""
    user, uid = _auth(payload.init_data)
    await upsert_user_async(db, uid, username=user.get("username"), first_name=user.get("first_name"))
    # Warm the feed ONLY for a genuine SIGNED invite — otherwise a client could probe any user's
    # taste by replaying their id as the inviter. Unsigned / forged → no warm, no leak.
    if invite_verify(payload.event_id or "", payload.inviter_id, payload.sig):
        interests = await warm_interests_from(db, uid, payload.inviter_id)
    else:
        interests = []
    await db.commit()
    return {"interests": interests}


@router.post("/settings")
async def user_settings(payload: SettingsRequest, db: AsyncSession = Depends(get_async_db)):
    """Read, or set-then-read, the account's app settings (theme, city, first-run flags)."""
    user, uid = _auth(payload.init_data)
    changing = any(
        v is not None
        for v in (payload.theme, payload.city, payload.onboarded, payload.coach, payload.swipe_seen, payload.interests, payload.notify_reminders, payload.notify_digest, payload.friends_private)
    )
    if changing:
        # Only write the user row when actually changing a setting (a pure read on app
        # open shouldn't UPDATE+commit — favorites/sync already recorded the open).
        await upsert_user_async(db, uid, username=user.get("username"), first_name=user.get("first_name"), photo_url=user.get("photo_url"))
        settings = await update_settings(
            db,
            uid,
            theme=payload.theme,
            city=payload.city,
            onboarded=payload.onboarded,
            coach=payload.coach,
            swipe_seen=payload.swipe_seen,
            interests=payload.interests,
            notify_reminders=payload.notify_reminders,
            notify_digest=payload.notify_digest,
            friends_private=payload.friends_private,
        )
        # Turning notifications ON arms reminders for everything already in favourites (they're now the
        # single reminder source). Turning OFF needs nothing — delivery is gated on notify_reminders.
        if payload.notify_reminders is True:
            await _arm_all_favorite_reminders(db, uid)
        await db.commit()
    else:
        settings = await get_settings(db, uid)
    return {"settings": settings}
