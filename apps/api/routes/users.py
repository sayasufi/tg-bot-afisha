import asyncio
import re
from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta, timezone
from html import escape

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

_SRC_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


def _acq_source(raw: str | None) -> str | None:
    """Источник из deep-link start_param. «src_<x>» → «<x>» (обычно username канала); санитизация."""
    if not raw:
        return None
    s = raw.strip()
    if s.startswith("src_"):
        s = s[4:]
    # M10: нижний регистр — adstat.channels.username всегда lowercase, а джойн аттрибуции точный → иначе
    # любая заглавная буква в src-метке тихо обнуляла «привёл».
    return s.lower() if s and _SRC_RE.match(s) else None

from apps.api.services.geo import reverse_city
from apps.api.services.telegram_auth import validate_init_data
from core.render.formatting import ce
from core.domain.cities import city_by_name
from core.config.settings import get_settings as get_app_settings
from core.services.invite import sign_friend, verify as invite_verify, verify_friend
from core.db.repositories.reminders import (
    arm_reminder_if_unsent,
    cancel_reminder,
    list_reminder_ids,
    set_reminder,
    soonest_future_end,
    soonest_future_start,
)
from core.db.repositories.friends import (
    accept_request,
    are_friends,
    befriend,
    bump_friend_link_ver,
    count_friends,
    decline_request,
    find_searchable,
    friend_activity,
    friend_link_ver,
    friend_profile,
    friends_who_favorited,
    list_friends,
    list_requests,
    my_hidden_event_ids,
    relation,
    remove_friend,
    request_friend,
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
from core.infra.redis import get_redis

# Remind this long before the soonest session starts.
_REMINDER_LEAD = timedelta(hours=2)
# For an ONGOING event (exhibition/open run) with no upcoming start — remind this long before it CLOSES,
# so a «схожу потом» save brings the user back near the deadline rather than arming nothing.
_CLOSING_LEAD = timedelta(days=2)


async def _reminder_fire_at(db: AsyncSession, event_id: str):
    """Когда слать напоминание по сохранённому событию: за _REMINDER_LEAD до ближайшего БУДУЩЕГО старта;
    если будущего старта нет, но событие ещё идёт — за _CLOSING_LEAD до закрытия; иначе None (всё в прошлом)."""
    now = datetime.now(timezone.utc)
    start = await soonest_future_start(db, event_id)
    if start is not None:
        return max(now + timedelta(seconds=45), start - _REMINDER_LEAD)
    end = await soonest_future_end(db, event_id)
    if end is None:
        return None
    return max(now + timedelta(hours=1), end - _CLOSING_LEAD)

# A3: best-effort DM fan-out MUST NOT run inside the request handler while it holds a pooled async DB
# connection — a single «друг сохранил это» save can address up to 30 friends, and 30 sequential
# 8-second TG POSTs pin the connection for the whole burst, exhausting the pool under load. `_fanout`
# schedules the network sends as a DETACHED task that runs after the handler returns (so the DB session
# is already released), fires them CONCURRENTLY through ONE reusable httpx client, and caps in-flight
# POSTs with a shared semaphore. Handlers resolve everything the sends need (recipient ids, titles) from
# the DB first, then hand `_fanout` pure network coroutines — nothing in here touches the DB session.
_TG_SEM = asyncio.Semaphore(8)  # cap concurrent outbound TG sendMessage calls across all fan-outs
_BG_TASKS: set[asyncio.Task] = set()  # strong refs so a detached fan-out task isn't GC'd mid-flight


async def _post_tg(client: httpx.AsyncClient, chat_id: int, text_msg: str, markup: dict) -> None:
    """One best-effort TG sendMessage on a SHARED client, under the concurrency cap. Never raises."""
    async with _TG_SEM:
        try:
            await client.post(
                f"https://api.telegram.org/bot{get_app_settings().telegram_bot_token}/sendMessage",
                json={"chat_id": int(chat_id), "text": text_msg, "parse_mode": "HTML",
                      "reply_markup": markup, "disable_web_page_preview": True},
            )
        except Exception:
            pass  # the underlying action is already recorded; the nudge is best-effort


def _fanout(sends: list[Callable[[httpx.AsyncClient], Awaitable[None]]]) -> None:
    """Fire a batch of best-effort DMs AFTER the handler returns: one shared httpx client for the whole
    batch, concurrent gather, never awaited by the caller (so the response — and its DB connection — is
    released first). Each `send` is a coroutine factory taking the shared client; none may touch the DB."""
    if not sends:
        return

    async def _run() -> None:
        try:
            async with httpx.AsyncClient(timeout=8) as client:
                await asyncio.gather(*(s(client) for s in sends), return_exceptions=True)
        except Exception:
            pass  # the whole fan-out is best-effort — a DM burst must never surface as an error

    task = asyncio.create_task(_run())
    _BG_TASKS.add(task)  # hold a strong ref (asyncio only keeps weak ones) until it finishes
    task.add_done_callback(_BG_TASKS.discard)


# A18: when Redis is unavailable the anti-abuse day-caps must NOT fail-OPEN (that turns a Redis blip into
# an uncapped spam/enumeration window). Instead they degrade to this in-process, short-window per-user
# limiter: a small fixed number of actions per bucket per ~minute, per worker. It's not shared across
# workers, but it bounds the blast radius of any single account far below the daily cap while Redis heals.
_LOCAL_WINDOW = 60.0  # seconds
_LOCAL_LIMIT = 3  # actions per bucket, per user, per window, per worker (fallback only)
_local_hits: dict[str, tuple[float, int]] = {}


def _local_rate_ok(bucket: str, uid: int, limit: int = _LOCAL_LIMIT, window: float = _LOCAL_WINDOW) -> bool:
    """Fail-CLOSED fallback for the Redis day-caps: allow at most `limit` `bucket` actions per `uid` per
    `window` seconds in THIS process. Fixed-window; opportunistically evicts stale keys to stay bounded."""
    import time

    now = time.monotonic()
    if len(_local_hits) > 4096:  # keep the map bounded — drop everything already expired
        for k in [k for k, (t0, _) in _local_hits.items() if now - t0 >= window]:
            _local_hits.pop(k, None)
    key = f"{bucket}:{uid}"
    t0, n = _local_hits.get(key, (now, 0))
    if now - t0 >= window:
        t0, n = now, 0
    n += 1
    _local_hits[key] = (t0, n)
    return n <= limit


async def _claim_favorites_merge(db: AsyncSession, uid: int) -> bool:
    """A16: atomically claim the one-time local-favourites merge. Flip favorites_merged false→true in a
    single conditional UPDATE and return True ONLY if THIS statement did the flip (rowcount==1). A
    concurrent bootstrap⟂favorites/sync request blocks on the row lock, then re-reads the committed
    true and gets rowcount==0 — so the stale device's `add` list is merged at most once, and never after
    a delete on another device resurrects a removed favourite. No commit (the route commits once)."""
    res = await db.execute(text(
        "UPDATE ref.users SET favorites_merged=true "
        "WHERE telegram_user_id=:uid AND favorites_merged=false"
    ), {"uid": uid})
    return (res.rowcount or 0) == 1


router = APIRouter(prefix="/v1/users", tags=["users"])


class LocationRequest(BaseModel):
    init_data: str
    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)


class FavoritesSyncRequest(BaseModel):
    init_data: str
    add: list[str] = []  # this device's local favourites to merge in (once, on first sync)


class BootstrapRequest(BaseModel):
    init_data: str
    add: list[str] = []  # this device's local favourites to merge in on first run (same gate as favorites/sync)
    source: str | None = None  # deep-link start_param «src_<channel>» — first-touch acquisition source


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
    notify_broadcasts: bool | None = None  # opt-out of custom admin broadcasts (default on)
    friends_private: bool | None = None  # hide ALL my favourites from friends (default off)


class FriendsFavoritedRequest(BaseModel):
    init_data: str
    event_ids: list[str] = []  # which events to resolve «friends who saved this» for


class FriendsRequest(BaseModel):
    init_data: str
    action: str | None = None  # 'accept'|'decline'|'remove'|'block'|'unblock' — omit to LIST friends+requests
    friend_id: int | None = None


class FriendsActivityRequest(BaseModel):
    init_data: str


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


class InviteToFriendRequest(BaseModel):
    init_data: str
    event_id: str
    friend_id: int  # a mutual friend to DM «X зовёт тебя на <event>»


class FindFriendRequest(BaseModel):
    init_data: str
    username: str  # exact @handle to look up — anyone with a handle is findable
    send: bool = False  # false = peek the card + relation; true = send a pending friend request


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
    await upsert_user_async(db, uid, username=user.get("username"), first_name=user.get("first_name"))
    # A16: the merge gate must be ATOMIC. Reading favorites_merged then setting it lets bootstrap and
    # favorites/sync race — both read False, both merge, and a merge can even land AFTER a concurrent
    # delete, resurrecting a removed favourite. Flip the flag conditionally in one statement and merge
    # ONLY when THIS request won the flip (rowcount==1), so the stale device's `add` is applied at most once.
    if payload.add and await _claim_favorites_merge(db, uid):
        await add_favorites(db, uid, payload.add)
    await db.commit()
    return {"ids": await list_favorite_ids(db, uid)}


@router.post("/bootstrap")
async def bootstrap(payload: BootstrapRequest, db: AsyncSession = Depends(get_async_db)):
    """One round-trip on app open: upsert the user once, run the first-run favourites merge if needed, and
    return everything the client pulls on open — settings + favourite ids + followed venue ids + friend
    count. Replaces 4 separate authed POSTs (favorites/sync + venues + friends + settings), each of which
    re-validated initData (and favorites/sync upserted). The client falls back to those 4 if this fails, so
    the consolidation can never make the open WORSE than before."""
    user, uid = _auth(payload.init_data)
    await upsert_user_async(
        db, uid, username=user.get("username"), first_name=user.get("first_name"), photo_url=user.get("photo_url")
    )
    # Same one-time, server-gated migration as favorites/sync — a stale device can't resurrect removed
    # ones. A16: claim the merge atomically (see _claim_favorites_merge) so a bootstrap⟂favorites/sync
    # race can't double-merge or merge after a delete.
    if payload.add and await _claim_favorites_merge(db, uid):
        await add_favorites(db, uid, payload.add)
    # M11: реальное ОТКРЫТИЕ приложения (bootstrap = вызов из мини-аппы). last_active_at бьётся и бот-командами,
    # поэтому удержание в воронке закупок меряем по этой колонке, а не по last_active_at.
    await db.execute(text("UPDATE ref.users SET last_app_open_at=now() WHERE telegram_user_id=:uid"), {"uid": uid})
    # Аттрибуция first-touch: фиксируем источник один раз (не перезаписываем).
    src = _acq_source(payload.source)
    if src:
        await db.execute(text(
            "UPDATE ref.users SET acq_source=:s, acq_at=now() WHERE telegram_user_id=:uid AND acq_source IS NULL"
        ), {"s": src, "uid": uid})
    await db.commit()  # the upsert (records the open) + the optional merge — a pure read otherwise
    return {
        "settings": await get_settings(db, uid),
        "favorite_ids": await list_favorite_ids(db, uid),
        "venue_follow_ids": await list_followed_venue_ids(db, uid),
        "friends_count": await count_friends(db, uid),
    }


@router.post("/favorites")
async def toggle_favorite(payload: FavoriteToggleRequest, db: AsyncSession = Depends(get_async_db)):
    """Heart / un-heart one event. Favouriting also arms its pre-event reminder (unless reminders are
    globally muted); accepting a signed «Пойдём?» invite additionally makes the inviter a mutual FRIEND
    instantly (accepting is the consent) and DMs them once."""
    user, uid = _auth(payload.init_data)
    await upsert_user_async(
        db, uid, username=user.get("username"), first_name=user.get("first_name"), photo_url=user.get("photo_url")
    )
    inserted = await set_favorite(db, uid, payload.event_id, payload.on)
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
            # Friend notifications are always on (the «О друзьях» opt-out was removed).
            if await _invite_dm_once(uid, payload.event_id, inviter):
                title = await event_title(db, payload.event_id)
                notify = (inviter, title or "")
    else:
        await cancel_reminder(db, uid, payload.event_id)  # un-fav → drop its reminder
    await db.commit()
    ids = await list_favorite_ids(db, uid)
    if notify:
        _notify_inviter(notify[0], user.get("first_name") or "", notify[1], payload.event_id)
    # ПЕРВОЕ в жизни сохранение → DM из бота, закрепляющий петлю прямо в канале (напоминание + дайджест).
    # Once-ever (Redis NX), плюс гейт len(ids)==1 — на случай Redis-простоя не дёргать на повторных.
    if payload.on and inserted and len(ids) == 1 and await _first_save_dm_once(uid):
        _notify_first_save(uid, payload.event_id)
    # Соц-доказательство: на НОВОЕ сохранение пушим друзьям-землякам «друг сохранил это» (возврат-триггер),
    # с приватностью/городом/mute/дедупом/дневным капом. Best-effort.
    if payload.on and inserted:
        await _notify_friends_of_save(db, uid, user.get("first_name") or "", payload.event_id)
    return {"ids": ids, "friend": friend, "first_friend": first_friend}


@router.post("/reminders")
async def toggle_reminder(payload: ReminderRequest, db: AsyncSession = Depends(get_async_db)):
    """Arm / cancel a reminder for an event (the bot DMs you ~2h before it starts), or — with
    no event_id — just list the account's active reminders. Returns the current id list."""
    user, uid = _auth(payload.init_data)
    await upsert_user_async(db, uid, username=user.get("username"), first_name=user.get("first_name"))
    if payload.event_id is not None and payload.on is not None:
        if payload.on:
            fire_at = await _reminder_fire_at(db, payload.event_id)  # будущий старт ИЛИ закрытие ongoing
            if fire_at is not None:  # всё в прошлом → напомнить не о чем; тихо no-op
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


@router.post("/friends-activity")
async def get_friends_activity(payload: FriendsActivityRequest, db: AsyncSession = Depends(get_async_db)):
    """My friends' recent saves (newest first) — the «Активность друзей» feed at the top of the «Друзья»
    screen. Each row = a friend + the event they saved + when; the event_ids are hydrated into the rich
    map-item shape (reusing the favourites by-ids path) so a tap opens the full sheet. Read-only. Privacy +
    live-only gating lives in friend_activity (accepted / not hidden / friend not private / not muted)."""
    _user, uid = _auth(payload.init_data)
    acts = await friend_activity(db, uid, limit=24)
    if not acts:
        return {"activity": []}
    from apps.api.services.events_service import EventQueryService

    hydrated = await EventQueryService(db).list_by_ids([a["event_id"] for a in acts])
    by_id = {str(it["event_id"]): it for it in hydrated.get("items", [])}
    activity = [
        {"friend": a["friend"], "at": a["at"], "event": ev}
        for a in acts
        if (ev := by_id.get(str(a["event_id"])))
    ]
    return {"activity": activity}


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
async def make_friend_link(payload: FriendLinkRequest, db: AsyncSession = Depends(get_async_db)):
    """A personal «добавь меня в друзья» deep-link for the current account (sign_friend), separate from
    event invites. Opening it shows an accept screen, then instant friends. SINGLE-USE: signed at the
    account's current friend_link_ver, which the first successful add bumps — so the link can't be reused
    or broadcast. Tapping «пригласить друга» again after an add mints a fresh one."""
    _user, uid = _auth(payload.init_data)
    ver = await friend_link_ver(db, uid)
    return {"link": f"https://t.me/okrestmap_bot?startapp=friend_{uid}_{sign_friend(uid, ver)}"}


@router.post("/friend-peek")
async def peek_friend_link(payload: FriendInviteRequest, db: AsyncSession = Depends(get_async_db)):
    """Who is behind an «add me» link — name/@username/photo for the accept screen. Gated on a valid sig
    (you can't peek an arbitrary id's card), and never self. The version is loaded from the DB by inviter
    id (never trusted from the client) so a rotated-away link fails here."""
    _user, uid = _auth(payload.init_data)
    if int(payload.inviter_id) == uid:
        raise HTTPException(status_code=403, detail="bad friend link")
    ver = await friend_link_ver(db, int(payload.inviter_id))
    if not verify_friend(payload.inviter_id, payload.sig, ver):
        raise HTTPException(status_code=403, detail="bad friend link")
    card = await user_card(db, int(payload.inviter_id))
    if not card:
        raise HTTPException(status_code=404, detail="no such user")
    return card


@router.post("/friend-accept")
async def accept_friend_link(payload: FriendInviteRequest, db: AsyncSession = Depends(get_async_db)):
    """Accept an «add me» link → instant mutual friends (accepting IS the consent). The link is SINGLE-USE:
    a successful add bumps the owner's friend_link_ver, so the link (and any copies) dies — no broadcast,
    no manual reset. DMs the link owner once. 403 on a forged/self/already-used link. Returns the new
    friend's card + first_friend. The link version is loaded from the DB by inviter id, never the client."""
    user, uid = _auth(payload.init_data)
    await upsert_user_async(
        db, uid, username=user.get("username"), first_name=user.get("first_name"), photo_url=user.get("photo_url")
    )
    if int(payload.inviter_id) == uid:
        raise HTTPException(status_code=403, detail="bad friend link")
    ver = await friend_link_ver(db, int(payload.inviter_id))
    if not verify_friend(payload.inviter_id, payload.sig, ver):
        raise HTTPException(status_code=403, detail="bad friend link")
    inviter = int(payload.inviter_id)
    friend = await befriend(db, uid, inviter)
    if friend == "accepted":
        await bump_friend_link_ver(db, inviter)  # single-use: consuming the link invalidates it + any copies
    first_friend = friend == "accepted" and await count_friends(db, uid) == 1
    card = await user_card(db, inviter)
    notify = False
    if friend == "accepted":
        # Friend notifications are always on (the «О друзьях» opt-out was removed).
        if await _friend_add_dm_once(inviter, uid):
            notify = True
    await db.commit()
    if notify:
        _notify_friend_added(inviter, user.get("first_name") or "")
    return {"friend": card, "first_friend": first_friend, "added": friend == "accepted"}


@router.post("/invite-friend")
async def invite_to_friend(payload: InviteToFriendRequest, db: AsyncSession = Depends(get_async_db)):
    """Send THIS event to a specific MUTUAL friend's DM («X зовёт тебя на <event>»). Read-only + a
    best-effort DM. 403 if not a friend; deduped per (you, them, event), capped per sender per day.
    `sent` = whether a DM actually went out. Friend notifications are always on (the opt-out was removed)."""
    user, uid = _auth(payload.init_data)
    fid = int(payload.friend_id)
    if fid == uid or not await are_friends(db, uid, fid):
        raise HTTPException(status_code=403, detail="not a friend")
    if not await _friend_invite_dm_once(uid, fid, payload.event_id):
        return {"ok": True, "sent": False}  # already invited this friend to this event
    if not await _friend_invite_day_ok(uid):
        raise HTTPException(status_code=429, detail="too many invites today")
    title = await event_title(db, payload.event_id)
    _notify_friend_invited(fid, user.get("first_name") or "", title, payload.event_id)
    return {"ok": True, "sent": True}


@router.post("/find-friend")
async def find_friend(payload: FindFriendRequest, db: AsyncSession = Depends(get_async_db)):
    """Find an account by EXACT @username (anyone with a handle is findable) and optionally send a PENDING
    friend request. Privacy-first: no match / self / blocked ALL return the same {found:false}, so search
    can't probe who is a user. Per-searcher daily cap blunts enumeration. send=true creates a
    request the target confirms in «Заявки» — the searcher initiated, so it needs the target's consent (NOT
    instant friends like a bearer link). Reciprocal (they searched you too) auto-accepts to friends."""
    user, uid = _auth(payload.init_data)
    if not await _friend_search_day_ok(uid):
        raise HTTPException(status_code=429, detail="too many searches today")
    card = await find_searchable(db, uid, payload.username)
    if not card:
        return {"found": False}
    tid = int(card["id"])
    if not payload.send:
        return {"found": True, "user": card, "relation": await relation(db, uid, tid)}
    # Keep the searcher's own handle/avatar fresh so the target sees who's asking, then create the request.
    await upsert_user_async(
        db, uid, username=user.get("username"), first_name=user.get("first_name"), photo_url=user.get("photo_url")
    )
    status = await request_friend(db, uid, tid)
    await db.commit()
    if status == "pending":
        # Friend notifications are always on (the «О друзьях» opt-out was removed).
        if await _friend_request_dm_once(uid, tid):
            _notify_friend_request(tid, user.get("first_name") or "")
    return {"found": True, "user": card, "relation": await relation(db, uid, tid), "status": status}


def _notify_inviter(inviter_id: int, name: str, title: str | None, event_id: str) -> None:
    """DM the inviter that someone accepted their «Пойдём?» (added it to favourites) — best-effort, fired
    AFTER the handler returns (via _fanout, so it never holds the request's DB connection). The inviter
    started the bot (they shared from the Mini App)."""
    token = get_app_settings().telegram_bot_token
    if not token or not inviter_id:
        return
    text = (
        f"{ce('🎉')} <b>{escape(name or 'Кто-то')}</b> принял твоё приглашение\n{escape(title or 'на событие')}\n\n"
        "Теперь вы друзья — смотрите, что друг у друга в избранном."
    )
    markup = {"inline_keyboard": [[{"text": "смотреть →", "url": f"https://t.me/okrestmap_bot?startapp={event_id}"}]]}
    _fanout([lambda client: _post_tg(client, int(inviter_id), text, markup)])


async def _first_save_dm_once(uid: int) -> bool:
    """Redis NX: True только в самый первый раз для юзера — DM на первое сохранение шлём ровно однажды."""
    client = get_redis(decode=True)
    if client is None:
        return True
    try:
        return bool(await client.set(f"firstsave:dm:{uid}", "1", nx=True, ex=365 * 24 * 3600))
    except Exception:
        return True


def _notify_first_save(uid: int, event_id: str) -> None:
    """Лучший-effort DM на ПЕРВОЕ сохранение: закрепляем петлю прямо в боте (напоминание + дайджест).
    Отправка ПОСЛЕ ответа (через _fanout — не держит соединение БД запроса)."""
    token = get_app_settings().telegram_bot_token
    if not token or not uid:
        return
    text = (
        f"{ce('❤️')} <b>Сохранено!</b> Напомню за 2 часа до начала — не пропустишь.\n\n"
        f"{ce('🔔')} А по выходным присылаю подборку афиши твоего города в личку — уже включена "
        "(выключить можно в <b>Профиле</b>)."
    )
    markup = {"inline_keyboard": [[{"text": "Открыть афишу →", "url": f"https://t.me/okrestmap_bot?startapp={event_id}"}]]}
    _fanout([lambda client: _post_tg(client, int(uid), text, markup)])


async def _friend_save_day_ok(recipient_id: int, cap: int = 3) -> bool:
    """Дневной кап friend-saved-DM на ПОЛУЧАТЕЛЯ — анти-спам. A18: Redis-down → НЕ fail-open, а короткое
    per-user окно в процессе (иначе блип Redis = неограниченный спам получателю)."""
    client = get_redis(decode=True)
    if client is None:
        return _local_rate_ok("friendsave", recipient_id)
    key = f"friendsave:day:{recipient_id}:{datetime.now(timezone.utc).strftime('%Y%m%d')}"
    try:
        n = await client.incr(key)
        if n == 1:
            await client.expire(key, 2 * 24 * 3600)
        return n <= cap
    except Exception:
        return _local_rate_ok("friendsave", recipient_id)


async def _friend_save_dm_once(recipient_id: int, saver_id: int, event_id: str) -> bool:
    """Redis NX: один friend-saved-DM на (получатель, сохранивший, событие) — без повторов на ре-сейвах."""
    client = get_redis(decode=True)
    if client is None:
        return True
    try:
        return bool(await client.set(f"friendsave:once:{recipient_id}:{saver_id}:{event_id}", "1", nx=True, ex=30 * 24 * 3600))
    except Exception:
        return True


def _friend_save_dm(recipient_id: int, saver_name: str, title: str | None, event_id: str) -> Callable[[httpx.AsyncClient], Awaitable[None]]:
    """Build the «друг сохранил это» send as a factory over the shared client (fired post-return by _fanout)."""
    text_msg = (
        f"{ce('👥')} <b>{escape(saver_name or 'Друг')}</b> сохранил(а) событие\n{escape(title or '')}\n\n"
        "Загляни — может, сходите вместе."
    )
    markup = {"inline_keyboard": [[{"text": "смотреть →", "url": f"https://t.me/okrestmap_bot?startapp={event_id}"}]]}
    return lambda client: _post_tg(client, recipient_id, text_msg, markup)


async def _notify_friends_of_save(db: AsyncSession, saver_id: int, saver_name: str, event_id: str) -> None:
    """Соц-доказательство: уведомить друзей-ЗЕМЛЯКОВ, что ты сохранил событие (возврат-триггер). Уважает
    приватность (friends_private), гейт по городу сохранившего, mute, ОПТ-АУТ рассылок получателя, дедуп и
    дневной кап получателя — чтобы не спамить. Резолвит получателей из БД, а сами DM отправляет ПОСЛЕ
    ответа (через _fanout: сессия БД уже освобождена, отправка конкурентная, один переиспользуемый клиент)."""
    if not get_app_settings().telegram_bot_token:
        return
    row = (await db.execute(text(
        "SELECT friends_private, city_slug FROM ref.users WHERE telegram_user_id = :u"), {"u": saver_id})).first()
    if not row or row[0] or not row[1]:  # приватный ИЛИ нет города → не пушим
        return
    # A5: уважать опт-аут пуш-рассылок получателя (notify_broadcasts) — раньше «друг сохранил это» его игнорил.
    friends = (await db.execute(text(
        "SELECT f.friend_id FROM ref.user_friends f JOIN ref.users u ON u.telegram_user_id = f.friend_id "
        "WHERE f.user_id = :s AND f.status = 'accepted' AND u.city_slug = :c AND u.notify_broadcasts IS TRUE "
        "AND NOT EXISTS (SELECT 1 FROM ref.user_mutes m WHERE (m.user_id = f.friend_id AND m.muted_user_id = :s) "
        "                OR (m.user_id = :s AND m.muted_user_id = f.friend_id)) LIMIT 30"
    ), {"s": saver_id, "c": row[1]})).scalars().all()
    if not friends:
        return
    title = await event_title(db, event_id)
    # Дедуп/кап (Redis) считаем ЗДЕСЬ, пока держим контекст, но сеть выносим за ответ. saver_id не может
    # быть собственным другом, но фильтр self оставлен из осторожности.
    sends: list[Callable[[httpx.AsyncClient], Awaitable[None]]] = []
    for fid in friends:
        if int(fid) == int(saver_id):
            continue
        if not await _friend_save_day_ok(int(fid)):
            continue
        if not await _friend_save_dm_once(int(fid), saver_id, event_id):
            continue
        sends.append(_friend_save_dm(int(fid), saver_name, title, event_id))
    _fanout(sends)


async def _arm_reminder(db: AsyncSession, uid: int, event_id: str) -> None:
    """Arm the pre-event reminder for one favourited event — UNLESS reminders are globally muted, or the
    event has no UPCOMING session (never remind about something that already happened). Reminders are
    now driven by favourites (no per-event bell)."""
    settings = await get_settings(db, uid)
    if settings.get("notify_reminders") is False:
        return
    fire_at = await _reminder_fire_at(db, event_id)  # будущий старт ИЛИ закрытие ongoing-события
    if fire_at is None:
        return
    await arm_reminder_if_unsent(db, uid, event_id, fire_at)


async def _arm_all_favorite_reminders(db: AsyncSession, uid: int) -> None:
    """Arm reminders for every favourited event with an UPCOMING session (or an ongoing run that's still
    open) — run when the user switches the profile notifications toggle ON, so reminders cover everything
    saved while it was off. Non-destructive (arm_reminder_if_unsent): never re-fires/never arms a past event."""
    for fid in await list_favorite_ids(db, uid):
        fire_at = await _reminder_fire_at(db, fid)
        if fire_at is not None:
            await arm_reminder_if_unsent(db, uid, fid, fire_at)


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


def _notify_friend_added(inviter_id: int, name: str) -> None:
    """DM the friend-link owner that someone added them via it (now friends) — best-effort, fired AFTER
    the handler returns (via _fanout — never holds the request's DB connection)."""
    token = get_app_settings().telegram_bot_token
    if not token or not inviter_id:
        return
    text = f"{ce('👋')} <b>{escape(name or 'Кто-то')}</b> добавил тебя в друзья по твоей ссылке"
    markup = {"inline_keyboard": [[{"text": "друзья →", "url": "https://t.me/okrestmap_bot?startapp=friends"}]]}
    _fanout([lambda client: _post_tg(client, int(inviter_id), text, markup)])


async def _friend_invite_dm_once(from_id: int, to_id: int, event_id: str) -> bool:
    """Redis NX: don't DM the SAME friend the SAME event invite twice (idempotent re-taps). 30-day TTL."""
    client = get_redis(decode=True)
    if client is None:
        return True
    try:
        return bool(await client.set(f"friend:invite:{from_id}:{to_id}:{event_id}", "1", nx=True, ex=30 * 24 * 3600))
    except Exception:
        return True


async def _friend_invite_day_ok(from_id: int, cap: int = 50) -> bool:
    """Per-sender daily cap on addressed friend invites — anti-spam. A18: Redis-down → short in-process
    per-user window instead of fail-open, so a Redis blip can't become an uncapped invite-spam burst."""
    client = get_redis(decode=True)
    if client is None:
        return _local_rate_ok("friend:invite", from_id)
    key = f"friend:invite:day:{from_id}:{datetime.now(timezone.utc).strftime('%Y%m%d')}"
    try:
        n = await client.incr(key)
        if n == 1:
            await client.expire(key, 2 * 24 * 3600)
        return n <= cap
    except Exception:
        return _local_rate_ok("friend:invite", from_id)


def _notify_friend_invited(friend_id: int, name: str, title: str | None, event_id: str) -> None:
    """DM a friend that <name> invites them to <event> — best-effort, fired AFTER the handler returns
    (via _fanout — never holds the request's DB connection)."""
    token = get_app_settings().telegram_bot_token
    if not token or not friend_id:
        return
    text = f"{ce('👋')} <b>{escape(name or 'Друг')}</b> зовёт тебя\n{escape(title or 'на событие')}"
    markup = {"inline_keyboard": [[{"text": "смотреть →", "url": f"https://t.me/okrestmap_bot?startapp={event_id}"}]]}
    _fanout([lambda client: _post_tg(client, int(friend_id), text, markup)])


async def _friend_search_day_ok(uid: int, cap: int = 50) -> bool:
    """Per-searcher daily cap on @username lookups — blunts userbase enumeration. A18: Redis-down → short
    in-process per-user window instead of fail-open, so a Redis blip can't open an uncapped enumeration
    window against the userbase."""
    client = get_redis(decode=True)
    if client is None:
        return _local_rate_ok("friend:search", uid)
    key = f"friend:search:day:{uid}:{datetime.now(timezone.utc).strftime('%Y%m%d')}"
    try:
        n = await client.incr(key)
        if n == 1:
            await client.expire(key, 2 * 24 * 3600)
        return n <= cap
    except Exception:
        return _local_rate_ok("friend:search", uid)


async def _friend_request_dm_once(from_id: int, to_id: int) -> bool:
    """Redis NX: don't re-DM the SAME person about the SAME requester's friend request (idempotent re-taps).
    7-day TTL. Best-effort (Redis down → allow)."""
    client = get_redis(decode=True)
    if client is None:
        return True
    try:
        return bool(await client.set(f"friend:req:dm:{from_id}:{to_id}", "1", nx=True, ex=7 * 24 * 3600))
    except Exception:
        return True


def _notify_friend_request(target_id: int, name: str) -> None:
    """DM a user that <name> wants to add them as a friend (→ «Заявки») — best-effort, fired AFTER the
    handler returns (via _fanout — never holds the request's DB connection)."""
    token = get_app_settings().telegram_bot_token
    if not token or not target_id:
        return
    text = f"{ce('👋')} <b>{escape(name or 'Кто-то')}</b> хочет добавить тебя в друзья"
    markup = {"inline_keyboard": [[{"text": "заявки →", "url": "https://t.me/okrestmap_bot?startapp=friends"}]]}
    _fanout([lambda client: _post_tg(client, int(target_id), text, markup)])


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
        for v in (payload.theme, payload.city, payload.onboarded, payload.coach, payload.swipe_seen, payload.interests, payload.notify_reminders, payload.notify_digest, payload.notify_broadcasts, payload.friends_private)
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
            notify_broadcasts=payload.notify_broadcasts,
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
