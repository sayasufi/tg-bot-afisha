"""Public user-submission endpoints (Mini App forms) — «предложить своё мероприятие».

initData-authenticated; each submission lands in ref.pending_submissions for admin moderation (never
straight into the catalog). Cheap validation only (no LLM): required fields, an upcoming date, a place.
Anti-abuse: a per-user daily cap (Redis fast-path + durable fallback).
"""
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.services.telegram_auth import validate_init_data
from core.db.repositories.submissions import count_user_submissions_today, create_submission
from core.db.session import get_async_db
from core.domain.cities import CITIES
from core.infra.redis import get_redis

router = APIRouter(prefix="/v1/suggest", tags=["suggest"])

_MSK = timezone(timedelta(hours=3))
_DAILY_CAP = 10  # submissions per user per day
_CATEGORIES = {
    "concert", "theatre", "exhibition", "cinema", "standup",
    "festival", "lecture", "tour", "party", "quest", "kids", "other",
}


class EventSuggestRequest(BaseModel):
    init_data: str
    title: str = Field(min_length=2, max_length=300)
    date_start: str  # ISO-8601; assumed Moscow time if no offset
    date_end: str | None = None
    venue: str | None = Field(default=None, max_length=300)
    address: str | None = Field(default=None, max_length=500)
    category: str | None = None
    price_min: float | None = Field(default=None, ge=0, le=10_000_000)
    price_max: float | None = Field(default=None, ge=0, le=10_000_000)
    is_free: bool = False
    url: str | None = Field(default=None, max_length=1000)
    image: str | None = Field(default=None, max_length=1000)
    description: str | None = Field(default=None, max_length=4000)
    city: str | None = None  # city slug; falls back to the submitter's saved city


def _clean_url(u: str | None) -> str:
    if not u:
        return ""
    u = u.strip()
    try:
        scheme = urlparse(u).scheme
    except Exception:
        return ""
    if scheme not in ("http", "https") or any(c in u for c in "'\"\\<>\n\r\t "):
        return ""
    return u[:1000]


def _parse_future(s: str) -> datetime | None:
    """Parse an ISO datetime (Moscow-assumed if naive) and require its MSK calendar day to be
    today or later — mirrors the pipeline's upcoming-window gate so a past event is rejected up front."""
    try:
        dt = datetime.fromisoformat((s or "").strip().replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=_MSK)
    today_msk = datetime.now(_MSK).date()
    if dt.astimezone(_MSK).date() < today_msk:
        return None
    return dt


async def _resolve_city_slug(db: AsyncSession, uid: int, requested: str | None) -> str:
    if requested and requested in CITIES:
        return requested
    saved = (await db.execute(
        text("SELECT city_slug FROM ref.users WHERE telegram_user_id = :u"), {"u": uid}
    )).scalar()
    return saved if saved in CITIES else "moscow"


async def _rate_limit_ok(db: AsyncSession, uid: int) -> bool:
    """Redis daily counter (fast path); on Redis miss fall back to a durable COUNT."""
    day = datetime.now(_MSK).strftime("%Y%m%d")
    try:
        r = get_redis(decode=True)
        if r is not None:
            key = f"suggest:day:{uid}:{day}"
            n = await r.incr(key)
            if n == 1:
                await r.expire(key, 86400)
            return n <= _DAILY_CAP
    except Exception:
        pass
    return await count_user_submissions_today(db, uid) < _DAILY_CAP


@router.post("/event")
async def suggest_event(payload: EventSuggestRequest, request: Request, db: AsyncSession = Depends(get_async_db)):
    user = validate_init_data(payload.init_data)  # HMAC + freshness
    uid = user.get("id")
    if not uid:
        raise HTTPException(status_code=401, detail="no user")

    title = payload.title.strip()
    if len(title) < 2:
        raise HTTPException(status_code=422, detail="Укажи название события")
    dt = _parse_future(payload.date_start)
    if dt is None:
        raise HTTPException(status_code=422, detail="Дата должна быть сегодня или в будущем")
    venue = (payload.venue or "").strip()
    address = (payload.address or "").strip()
    if not venue and not address:
        raise HTTPException(status_code=422, detail="Укажи место или адрес")

    if not await _rate_limit_ok(db, int(uid)):
        raise HTTPException(status_code=429, detail="Слишком много заявок за сегодня — попробуй завтра")

    city_slug = await _resolve_city_slug(db, int(uid), payload.city)
    category = (payload.category or "").strip().lower() or None
    if category not in _CATEGORIES:
        category = None

    data = {
        "title": title[:300],
        "description": (payload.description or "").strip()[:4000],
        "date_start": dt.isoformat(),
        "date_end": payload.date_end,
        "venue": venue[:300],
        "address": address[:500],
        "category": category,
        "price_min": payload.price_min,
        "price_max": payload.price_max,
        "is_free": bool(payload.is_free),
        "url": _clean_url(payload.url),
        "image": _clean_url(payload.image),
    }
    sid = await create_submission(
        db, kind="event", data=data, submitted_by=int(uid),
        submitted_username=user.get("username"), city_slug=city_slug, status="needs_review",
    )
    return {"ok": True, "submission_id": sid, "status": "needs_review"}
