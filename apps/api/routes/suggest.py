"""Public user-submission endpoints (Mini App forms) — «предложить своё мероприятие».

initData-authenticated; each submission lands in ref.pending_submissions for admin moderation (never
straight into the catalog). Cheap validation only (no LLM): required fields, an upcoming date, a place.
Anti-abuse: a per-user daily cap (Redis fast-path + durable fallback).
"""
import base64
import io
import uuid
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from PIL import Image, ImageOps
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.services.telegram_auth import validate_init_data
from core.db.repositories.submissions import count_user_submissions_today, create_submission
from core.db.session import get_async_db
from core.domain.cities import CITIES
from core.infra.redis import get_redis
from core.media.storage import ensure_bucket, public_url, put_image

router = APIRouter(prefix="/v1/suggest", tags=["suggest"])

_MSK = timezone(timedelta(hours=3))
_DAILY_CAP = 10  # submissions per user per day
_CATEGORIES = {
    "concert", "theatre", "exhibition", "cinema", "standup",
    "festival", "lecture", "tour", "party", "quest", "kids", "other",
}
_MAX_UPLOAD = 8 * 1024 * 1024  # 8 MB
_MAX_DIM = 1600  # px — downscale the long edge
_UPLOAD_CAP = 30  # images per user per day


def _process_and_store(raw: bytes) -> str:
    """Validate + normalize an uploaded image (honour EXIF orientation, then strip metadata, downscale,
    re-encode JPEG) and store it in MinIO. Returns the public URL. Blocking — call via threadpool."""
    Image.open(io.BytesIO(raw)).verify()  # reject truncated / non-image bytes
    img = ImageOps.exif_transpose(Image.open(io.BytesIO(raw))).convert("RGB")
    img.thumbnail((_MAX_DIM, _MAX_DIM))
    out = io.BytesIO()
    img.save(out, format="JPEG", quality=85)
    key = f"submissions/{uuid.uuid4().hex}.jpg"
    ensure_bucket()
    put_image(key, out.getvalue(), "image/jpeg")
    return public_url(key)


async def _upload_limit_ok(uid: int) -> bool:
    day = datetime.now(_MSK).strftime("%Y%m%d")
    try:
        r = get_redis(decode=True)
        if r is not None:
            key = f"suggest:upl:{uid}:{day}"
            n = await r.incr(key)
            if n == 1:
                await r.expire(key, 86400)
            return n <= _UPLOAD_CAP
    except Exception:
        pass
    return True  # Redis unavailable → don't block uploads


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


class ImageUploadRequest(BaseModel):
    init_data: str
    data_url: str = Field(max_length=14_000_000)  # base64 of ≤8MB ≈ 10.7MB + data: prefix headroom


@router.post("/upload")
async def suggest_upload(payload: ImageUploadRequest):
    """Upload a poster/photo for an event submission (base64 data URL) → MinIO, returns the public URL
    the form stores in `image`. Base64/JSON keeps it on the existing stack (no multipart dependency)."""
    user = validate_init_data(payload.init_data)
    uid = user.get("id")
    if not uid:
        raise HTTPException(status_code=401, detail="no user")
    b64 = payload.data_url.strip()
    if b64.lower().startswith("data:") and "," in b64:
        b64 = b64.split(",", 1)[1]  # strip the «data:image/…;base64,» prefix
    try:
        raw = base64.b64decode(b64, validate=True)
    except Exception:
        raise HTTPException(status_code=422, detail="Не удалось прочитать файл")
    if not raw:
        raise HTTPException(status_code=422, detail="Пустой файл")
    if len(raw) > _MAX_UPLOAD:
        raise HTTPException(status_code=413, detail="Файл слишком большой — до 8 МБ")
    if not await _upload_limit_ok(int(uid)):
        raise HTTPException(status_code=429, detail="Слишком много загрузок за сегодня")
    try:
        url = await run_in_threadpool(_process_and_store, raw)
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=422, detail="Не удалось обработать изображение")
    return {"ok": True, "url": url}
