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


async def request_friend(db: AsyncSession, target: int, requester: int, *, src_event_id: str | None = None) -> bool:
    """Record a PENDING friend request: `requester` accepted `target`'s signed «Пойдём?» → `target`
    (the inviter) must CONFIRM it. Crucial: a pending edge exposes NOTHING (friends_who_favorited /
    count_friends require 'accepted'), so a link forwarded to a group can't auto-befriend or leak a
    single favourite — the inviter chooses who becomes a friend. No commit. Returns True iff a new
    pending request was created. Skips self, a non-existent account (FK), a blocked pair, an existing
    friendship, or a target already at the friend cap."""
    target, requester = int(target), int(requester)
    if target == requester:
        return False
    if not await _both_exist(db, target, requester):
        return False
    blocked = await db.scalar(
        select(func.count()).select_from(UserMute).where(
            or_(
                and_(UserMute.user_id == target, UserMute.muted_user_id == requester),
                and_(UserMute.user_id == requester, UserMute.muted_user_id == target),
            )
        )
    )
    if blocked:
        return False
    already = await db.scalar(
        select(func.count()).select_from(UserFriend).where(
            UserFriend.user_id == target, UserFriend.friend_id == requester, UserFriend.status == "accepted"
        )
    )
    if already:
        return False
    if await count_friends(db, target) >= _FRIEND_CAP:
        return False
    eid: uuid.UUID | None = None
    if src_event_id:
        try:
            eid = uuid.UUID(str(src_event_id))
        except (ValueError, TypeError):
            eid = None
    res = await db.execute(
        pg_insert(UserFriend.__table__)
        .values(user_id=target, friend_id=requester, status="pending", src_event_id=eid)
        .on_conflict_do_nothing()  # don't downgrade an existing accepted/pending edge
    )
    return bool(res.rowcount)


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


async def friends_who_favorited(db: AsyncSession, uid: int, event_ids: list[str]) -> dict[str, list[dict]]:
    """For each given event, the friends (mini-profiles) who favourited it — the «друг сохранил это»
    signal. Honours every privacy gate: accepted edge only, friend not globally private, the favourite
    not per-item hidden, and neither side has muted the other. Capped per event."""
    uid = int(uid)
    eids = _as_uuids(event_ids, 200)
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
    eids = _as_uuids(event_ids, 200)
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
