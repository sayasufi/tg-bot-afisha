"""Friends graph — Phase 1. Symmetric edges (ref.user_friends), mutes (ref.user_mutes), and the hot
«which of my friends favorited these events» query. All async, none commit — the route commits once."""
import uuid

from sqlalchemy import and_, delete, exists, func, or_, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from core.db.models import User, UserFavorite, UserFriend, UserMute

_FRIEND_CAP = 500  # a sane upper bound; a real account never has this many, but caps fan-out abuse
_FACES_PER_EVENT = 8  # cap faces returned per event (the UI shows ≤2-3, this bounds the payload)


def _as_uuids(ids: list[str], limit: int) -> list[uuid.UUID]:
    out: list[uuid.UUID] = []
    for e in ids[:limit]:
        try:
            out.append(uuid.UUID(str(e)))
        except (ValueError, TypeError):
            continue
    return out


async def count_friends(db: AsyncSession, uid: int) -> int:
    """How many ACCEPTED friends this account has."""
    return int(
        await db.scalar(
            select(func.count()).select_from(UserFriend).where(
                UserFriend.user_id == int(uid), UserFriend.status == "accepted"
            )
        )
        or 0
    )


async def _both_exist(db: AsyncSession, a: int, b: int) -> bool:
    """True iff both telegram ids are real accounts in ref.users — the friendship edge FK requires it,
    and a "Пойдём?" link can carry a forged/typo'd/never-opened inviter id (share.py signs any ?ref)."""
    rows = (
        await db.execute(select(User.telegram_user_id).where(User.telegram_user_id.in_([a, b])))
    ).scalars().all()
    return a in rows and b in rows


async def befriend(db: AsyncSession, a: int, b: int, *, src_event_id: str | None = None) -> str:
    """Make `a` and `b` mutual friends NOW — accepting a «Пойдём?» invite IS the consent, no
    confirmation step. Writes the symmetric 'accepted' pair (upgrading a Phase-2 pending edge if one
    exists). No commit. Returns 'accepted' (a NEW friendship formed) or 'none' (skipped: self /
    non-existent account (FK) / blocked pair / already friends / either at the friend cap)."""
    a, b = int(a), int(b)
    if a == b:
        return "none"
    if not await _both_exist(db, a, b):
        return "none"
    blocked = await db.scalar(
        select(func.count()).select_from(UserMute).where(
            or_(
                and_(UserMute.user_id == a, UserMute.muted_user_id == b),
                and_(UserMute.user_id == b, UserMute.muted_user_id == a),
            )
        )
    )
    if blocked:
        return "none"
    already = await db.scalar(
        select(func.count()).select_from(UserFriend).where(
            UserFriend.user_id == a, UserFriend.friend_id == b, UserFriend.status == "accepted"
        )
    )
    if already:
        return "none"  # already friends
    if await count_friends(db, a) >= _FRIEND_CAP or await count_friends(db, b) >= _FRIEND_CAP:
        return "none"
    eid: uuid.UUID | None = None
    if src_event_id:
        try:
            eid = uuid.UUID(str(src_event_id))
        except (ValueError, TypeError):
            eid = None
    await db.execute(
        pg_insert(UserFriend.__table__)
        .values(
            [
                {"user_id": a, "friend_id": b, "status": "accepted", "src_event_id": eid},
                {"user_id": b, "friend_id": a, "status": "accepted", "src_event_id": eid},
            ]
        )
        .on_conflict_do_update(index_elements=["user_id", "friend_id"], set_={"status": "accepted"})
    )
    return "accepted"


async def accept_request(db: AsyncSession, uid: int, requester: int) -> bool:
    """The inviter CONFIRMS an incoming request → the edge becomes a mutual 'accepted' pair. Only works
    if such a pending request actually exists (so nobody self-promotes a forwarded link). Returns True
    iff it newly became a friendship. No commit."""
    uid, requester = int(uid), int(requester)
    res = await db.execute(
        update(UserFriend)
        .where(UserFriend.user_id == uid, UserFriend.friend_id == requester, UserFriend.status == "pending")
        .values(status="accepted")
    )
    if not res.rowcount:
        return False  # no pending request from this account — nothing to confirm
    await db.execute(
        pg_insert(UserFriend.__table__)
        .values(user_id=requester, friend_id=uid, status="accepted")
        .on_conflict_do_update(index_elements=["user_id", "friend_id"], set_={"status": "accepted"})
    )
    return True


async def decline_request(db: AsyncSession, uid: int, requester: int) -> None:
    """Decline an incoming pending request (delete just that row). No commit."""
    await db.execute(
        delete(UserFriend).where(
            UserFriend.user_id == int(uid), UserFriend.friend_id == int(requester), UserFriend.status == "pending"
        )
    )


async def list_requests(db: AsyncSession, uid: int) -> list[dict]:
    """Incoming pending friend requests (people who accepted MY invite, awaiting my confirm)."""
    rows = (
        await db.execute(
            select(User.telegram_user_id, User.first_name, User.username, User.photo_url)
            .join(UserFriend, UserFriend.friend_id == User.telegram_user_id)
            .where(UserFriend.user_id == int(uid), UserFriend.status == "pending")
            .order_by(UserFriend.created_at.desc())
        )
    ).all()
    return [
        {"id": r.telegram_user_id, "name": r.first_name or "", "username": r.username, "photo_url": r.photo_url}
        for r in rows
    ]


async def request_friend(db: AsyncSession, requester: int, target: int) -> str:
    """`requester` asks to befriend `target` (found by @username). Writes ONE pending row `target` sees in
    «Заявки» (user_id=target, friend_id=requester). If `target` ALREADY has an outstanding request to
    `requester` (they searched each other), upgrade straight to a mutual friendship — both have consented.
    Same guards as befriend (self / FK / blocked / already friends / cap). No commit. Returns 'accepted'
    (reciprocal → instant friends), 'pending' (request created or already pending), or 'none' (rejected)."""
    requester, target = int(requester), int(target)
    if requester == target:
        return "none"
    if not await _both_exist(db, requester, target):
        return "none"
    blocked = await db.scalar(
        select(func.count()).select_from(UserMute).where(
            or_(
                and_(UserMute.user_id == requester, UserMute.muted_user_id == target),
                and_(UserMute.user_id == target, UserMute.muted_user_id == requester),
            )
        )
    )
    if blocked:
        return "none"
    if await are_friends(db, requester, target):
        return "none"  # already friends — no-op
    # Reciprocal: target already requested requester (a pending row target→requester awaiting requester's
    # confirm) → accepting it makes them friends now. accept_request promotes that row + writes the reverse.
    reciprocal = await db.scalar(
        select(func.count()).select_from(UserFriend).where(
            UserFriend.user_id == requester, UserFriend.friend_id == target, UserFriend.status == "pending"
        )
    )
    if reciprocal:
        await accept_request(db, requester, target)
        return "accepted"
    if await count_friends(db, requester) >= _FRIEND_CAP:
        return "none"
    await db.execute(
        pg_insert(UserFriend.__table__)
        .values(user_id=target, friend_id=requester, status="pending")
        .on_conflict_do_nothing(index_elements=["user_id", "friend_id"])
    )
    return "pending"


async def friends_who_favorited(db: AsyncSession, uid: int, event_ids: list[str]) -> dict[str, list[dict]]:
    """For each given event, the friends (mini-profiles) who favourited it — the «друг сохранил это»
    signal. Honours every privacy gate: accepted edge only, friend not globally private, the favourite
    not per-item hidden, and neither side has muted the other. Capped per event."""
    uid = int(uid)
    eids = _as_uuids(event_ids, 250)
    if not eids:
        return {}
    muted = exists().where(
        or_(
            and_(UserMute.user_id == uid, UserMute.muted_user_id == UserFriend.friend_id),
            and_(UserMute.user_id == UserFriend.friend_id, UserMute.muted_user_id == uid),
        )
    )
    rows = (
        await db.execute(
            select(
                UserFavorite.event_id,
                User.telegram_user_id,
                User.first_name,
                User.username,
                User.photo_url,
            )
            .select_from(UserFriend)
            .join(UserFavorite, UserFavorite.telegram_user_id == UserFriend.friend_id)
            .join(User, User.telegram_user_id == UserFriend.friend_id)
            .where(
                UserFriend.user_id == uid,
                UserFriend.status == "accepted",
                UserFavorite.event_id.in_(eids),
                UserFavorite.hidden_from_friends.is_(False),
                User.friends_private.is_(False),
                ~muted,
            )
            .order_by(UserFavorite.event_id, UserFavorite.created_at.desc())
        )
    ).all()
    out: dict[str, list[dict]] = {}
    for r in rows:
        lst = out.setdefault(str(r.event_id), [])
        if len(lst) < _FACES_PER_EVENT:
            lst.append(
                {"id": r.telegram_user_id, "name": r.first_name or "", "username": r.username, "photo_url": r.photo_url}
            )
    return out


async def my_hidden_event_ids(db: AsyncSession, uid: int, event_ids: list[str]) -> list[str]:
    """Of the given events, the ones whose favourite THIS user has hidden from friends — so the sheet
    renders the per-item toggle in its real state."""
    eids = _as_uuids(event_ids, 250)
    if not eids:
        return []
    rows = (
        await db.execute(
            select(UserFavorite.event_id).where(
                UserFavorite.telegram_user_id == int(uid),
                UserFavorite.event_id.in_(eids),
                UserFavorite.hidden_from_friends.is_(True),
            )
        )
    ).scalars().all()
    return [str(r) for r in rows]


async def are_friends(db: AsyncSession, a: int, b: int) -> bool:
    """True iff a and b are mutual accepted friends (one accepted row a→b suffices — they're symmetric)."""
    return bool(
        await db.scalar(
            select(func.count()).select_from(UserFriend).where(
                UserFriend.user_id == int(a), UserFriend.friend_id == int(b), UserFriend.status == "accepted"
            )
        )
    )


async def user_card(db: AsyncSession, uid: int) -> dict | None:
    """A user's public mini-card (id/name/@username/photo) — for the «X хочет добавить тебя» accept
    screen and DMs. No relationship gate (the caller already proved the friend-link sig)."""
    u = await db.get(User, int(uid))
    if not u:
        return None
    return {"id": u.telegram_user_id, "name": u.first_name or "", "username": u.username, "photo_url": u.photo_url}


async def find_searchable(db: AsyncSession, uid: int, username: str) -> dict | None:
    """Find an account by exact, case-insensitive @username — the «add by @username» lookup. Anyone with a
    handle is findable (the opt-in is_searchable gate was removed). Returns the target's mini-card, or None
    for: no match / self / a blocked pair. Exact match only (no prefix/LIKE) so you can't walk the alphabet
    to enumerate the userbase, and a blocked pair still stays hidden."""
    handle = (username or "").strip().lstrip("@").lower()
    if not handle or len(handle) > 64:
        return None
    row = (
        await db.execute(
            select(User.telegram_user_id, User.first_name, User.username, User.photo_url)
            .where(
                func.lower(User.username) == handle,
                User.telegram_user_id != int(uid),
            )
            .order_by(User.last_active_at.desc())  # newest if a handle ever collides across rows
            .limit(1)
        )
    ).first()
    if not row:
        return None
    blocked = await db.scalar(
        select(func.count()).select_from(UserMute).where(
            or_(
                and_(UserMute.user_id == int(uid), UserMute.muted_user_id == row.telegram_user_id),
                and_(UserMute.user_id == row.telegram_user_id, UserMute.muted_user_id == int(uid)),
            )
        )
    )
    if blocked:
        return None
    return {"id": row.telegram_user_id, "name": row.first_name or "", "username": row.username, "photo_url": row.photo_url}


async def relation(db: AsyncSession, uid: int, other: int) -> str:
    """My relationship to `other`: 'friends' | 'pending_out' (I requested them) | 'pending_in' (they
    requested me) | 'none'. Drives the «add by username» result button."""
    uid, other = int(uid), int(other)
    if await are_friends(db, uid, other):
        return "friends"
    if await db.scalar(
        select(func.count()).select_from(UserFriend).where(
            UserFriend.user_id == other, UserFriend.friend_id == uid, UserFriend.status == "pending"
        )
    ):
        return "pending_out"
    if await db.scalar(
        select(func.count()).select_from(UserFriend).where(
            UserFriend.user_id == uid, UserFriend.friend_id == other, UserFriend.status == "pending"
        )
    ):
        return "pending_in"
    return "none"


async def friend_link_ver(db: AsyncSession, uid: int) -> int:
    """The account's current «add me» link version (0 if never rotated / unknown). Load this from the DB
    at sign + verify time — never trust a client-supplied version, or the kill-switch is bypassable."""
    return int(await db.scalar(select(User.friend_link_ver).where(User.telegram_user_id == int(uid))) or 0)


async def bump_friend_link_ver(db: AsyncSession, uid: int) -> int:
    """Rotate (kill) the account's outstanding friend-links: increment friend_link_ver, return the new
    value. No commit. Links signed at a lower version stop verifying immediately."""
    res = await db.execute(
        update(User)
        .where(User.telegram_user_id == int(uid))
        .values(friend_link_ver=User.friend_link_ver + 1)
        .returning(User.friend_link_ver)
    )
    return int(res.scalar() or 0)


async def friend_profile(db: AsyncSession, uid: int, friend_id: int) -> dict | None:
    """A friend's profile to view «что он лайкнул» — ONLY if uid and friend_id are mutual accepted
    friends and neither has blocked the other. Returns name/username/photo_url + their visible favourite
    event_ids (excluding per-item hidden ones; EMPTY if they've gone friends_private). None → caller 403s,
    so you can't read a stranger's or a blocked person's taste by id."""
    uid, friend_id = int(uid), int(friend_id)
    is_friend = await db.scalar(
        select(func.count()).select_from(UserFriend).where(
            UserFriend.user_id == uid, UserFriend.friend_id == friend_id, UserFriend.status == "accepted"
        )
    )
    if not is_friend:
        return None
    blocked = await db.scalar(
        select(func.count()).select_from(UserMute).where(
            or_(
                and_(UserMute.user_id == uid, UserMute.muted_user_id == friend_id),
                and_(UserMute.user_id == friend_id, UserMute.muted_user_id == uid),
            )
        )
    )
    if blocked:
        return None
    u = await db.get(User, friend_id)
    if not u:
        return None
    fav_ids: list[str] = []
    if not u.friends_private:
        rows = (
            await db.execute(
                select(UserFavorite.event_id)
                .where(UserFavorite.telegram_user_id == friend_id, UserFavorite.hidden_from_friends.is_(False))
                .order_by(UserFavorite.created_at.desc())
                .limit(300)
            )
        ).scalars().all()
        fav_ids = [str(r) for r in rows]
    return {
        "id": friend_id,
        "name": u.first_name or "",
        "username": u.username,
        "photo_url": u.photo_url,
        "private": bool(u.friends_private),
        "favorite_ids": fav_ids,
    }


async def list_friends(db: AsyncSession, uid: int) -> list[dict]:
    """The account's accepted friends as mini-profiles (newest first) — for the profile friend list."""
    rows = (
        await db.execute(
            select(User.telegram_user_id, User.first_name, User.username, User.photo_url)
            .join(UserFriend, UserFriend.friend_id == User.telegram_user_id)
            .where(UserFriend.user_id == int(uid), UserFriend.status == "accepted")
            .order_by(UserFriend.created_at.desc())
        )
    ).all()
    return [
        {"id": r.telegram_user_id, "name": r.first_name or "", "username": r.username, "photo_url": r.photo_url}
        for r in rows
    ]


async def remove_friend(db: AsyncSession, uid: int, other: int) -> None:
    """Unfriend — delete BOTH directions in one statement (visibility drops both ways at once). No commit."""
    uid, other = int(uid), int(other)
    await db.execute(
        delete(UserFriend).where(
            or_(
                and_(UserFriend.user_id == uid, UserFriend.friend_id == other),
                and_(UserFriend.user_id == other, UserFriend.friend_id == uid),
            )
        )
    )


async def set_mute(db: AsyncSession, uid: int, other: int, on: bool) -> None:
    """Block/unblock. Blocking also unfriends (both edges gone) and survives across re-friend attempts —
    add_friend_edges refuses a blocked pair. The blocked user is never told. No commit."""
    uid, other = int(uid), int(other)
    if uid == other:
        return
    if on:
        await db.execute(
            pg_insert(UserMute.__table__).values(user_id=uid, muted_user_id=other).on_conflict_do_nothing()
        )
        await remove_friend(db, uid, other)
    else:
        await db.execute(delete(UserMute).where(UserMute.user_id == uid, UserMute.muted_user_id == other))


async def set_favorite_hidden(db: AsyncSession, uid: int, event_id: str, hidden: bool) -> None:
    """Hide / unhide one favourite from friends (per-item privacy). No-op if it isn't favourited. No commit."""
    try:
        eid = uuid.UUID(str(event_id))
    except (ValueError, TypeError):
        return
    await db.execute(
        update(UserFavorite)
        .where(UserFavorite.telegram_user_id == int(uid), UserFavorite.event_id == eid)
        .values(hidden_from_friends=bool(hidden))
    )
