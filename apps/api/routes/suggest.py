"""Public user-submission endpoints (Mini App forms) — «предложить своё мероприятие».

initData-authenticated; each submission lands in ref.pending_submissions for admin moderation (never
straight into the catalog). Cheap validation only (no LLM): required fields, an upcoming date, a place.
Anti-abuse: a per-user daily cap (Redis fast-path + durable fallback).
"""
import asyncio
import base64
import io
import re
import uuid
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from PIL import Image, ImageOps
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.services.telegram_auth import validate_init_data
from core.db.repositories.submissions import count_user_submissions_today, create_submission
from core.db.session import get_async_db
from core.domain.cities import CITIES
from core.infra.redis import get_redis
from core.media.storage import ensure_bucket, public_url, put_image
from pipeline.maintenance.telegram_health import _fetch_subs, _probe, _UA

router = APIRouter(prefix="/v1/suggest", tags=["suggest"])

_MSK = timezone(timedelta(hours=3))
_DAILY_CAP = 10  # submissions per user per day
_CATEGORIES = {
    "concert", "theatre", "exhibition", "cinema", "standup",
    "festival", "lecture", "tour", "party", "quest", "kids", "other",
}
_MAX_UPLOAD = 8 * 1024 * 1024  # 8 MB (compressed)
_MAX_DIM = 1600  # px — downscale the long edge
_UPLOAD_CAP = 30  # images per user per day
_MAX_PIXELS = 40_000_000  # decompression-bomb guard: a tiny compressed file can decode to huge pixels
_MAX_EDGE = 12000  # …or an absurd single dimension
Image.MAX_IMAGE_PIXELS = 50_000_000  # Pillow hard ceiling too (defence in depth)
_PROBE_SEM = asyncio.Semaphore(6)  # cap concurrent outbound t.me probes (DoS / amplification / DB-pool)
_PROBE_BUDGET = 12.0  # hard total-time budget (s) per channel probe


def _process_and_store(raw: bytes) -> str:
    """Validate + normalize an uploaded image (honour EXIF orientation, then strip metadata, downscale,
    re-encode JPEG) and store it in MinIO. Returns the public URL. Blocking — call via threadpool."""
    Image.open(io.BytesIO(raw)).verify()  # reject truncated / non-image bytes
    src = Image.open(io.BytesIO(raw))  # reopen — verify() leaves the file unusable
    w, h = src.size  # header-only, no pixel decode yet → cheap decompression-bomb guard BEFORE convert()
    if w * h > _MAX_PIXELS or max(w, h) > _MAX_EDGE:
        raise ValueError("image dimensions too large")
    img = ImageOps.exif_transpose(src).convert("RGB")
    img.thumbnail((_MAX_DIM, _MAX_DIM))
    out = io.BytesIO()
    img.save(out, format="JPEG", quality=85)
    key = f"submissions/{uuid.uuid4().hex}.jpg"
    ensure_bucket()
    put_image(key, out.getvalue(), "image/jpeg")
    return public_url(key)


async def _upload_limit_ok(uid: int) -> bool:
    # Uploads leave no durable per-user row to count (unlike submissions), so there is no safe fallback:
    # fail CLOSED when Redis is unavailable, or the whole cap vanishes the moment Redis blips (which would
    # let one initData store unbounded images in MinIO). Uploads briefly disabled ≫ storage exhaustion.
    day = datetime.now(_MSK).strftime("%Y%m%d")
    try:
        r = get_redis(decode=True)
        if r is None:
            return False
        key = f"suggest:upl:{uid}:{day}"
        n = await r.incr(key)
        if n == 1:
            await r.expire(key, 86400)
        return n <= _UPLOAD_CAP
    except Exception:
        return False


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


def _parse_future(s: str, tz: timezone) -> datetime | None:
    """Parse an ISO datetime. A naive value is the event's LOCAL wall-clock in its city's timezone `tz`
    (NOT always Moscow — Новосибирск is +7 etc). Require its local calendar day to be today or later."""
    try:
        dt = datetime.fromisoformat((s or "").strip().replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=tz)
    if dt.astimezone(tz).date() < datetime.now(tz).date():
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
    # Resolve the city FIRST so the event's naive datetime is read in ITS timezone, not always Moscow.
    city_slug = await _resolve_city_slug(db, int(uid), payload.city)
    city_tz = timezone(timedelta(hours=CITIES[city_slug].utc_offset_hours))
    dt = _parse_future(payload.date_start, city_tz)
    if dt is None:
        raise HTTPException(status_code=422, detail="Дата должна быть сегодня или в будущем")
    venue = (payload.venue or "").strip()
    address = (payload.address or "").strip()
    if not venue and not address:
        raise HTTPException(status_code=422, detail="Укажи место или адрес")

    if not await _rate_limit_ok(db, int(uid)):
        raise HTTPException(status_code=429, detail="Слишком много заявок за сегодня — попробуй завтра")

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
    try:
        url = await run_in_threadpool(_process_and_store, raw)
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=422, detail="Не удалось обработать изображение")
    # Квоту тратим ТОЛЬКО после успешного сохранения — битый/непрочитанный файл (422/413) её не жжёт.
    if not await _upload_limit_ok(int(uid)):
        raise HTTPException(status_code=429, detail="Слишком много загрузок за сегодня")
    return {"ok": True, "url": url}


# ---- Channel submissions ----------------------------------------------------

_CHANNEL_RE = re.compile(r"^[a-z0-9_]{5,32}$")


def _norm_channel(raw: str) -> str | None:
    """Normalize a Telegram channel handle → lower ASCII, or None if it isn't a valid handle. The
    ASCII-only gate rejects Cyrillic-homoglyph look-alikes (а/a, о/o) that would dodge dedup."""
    u = (raw or "").strip()
    for prefix in ("https://t.me/", "http://t.me/", "t.me/", "@"):
        if u.lower().startswith(prefix):
            u = u[len(prefix):]
    u = u.strip().lstrip("@").strip().rstrip("/").lower()
    return u if _CHANNEL_RE.match(u) else None


async def _probe_channel(username: str) -> dict:
    """Cheap liveness/reach probe reusing the production prune helpers (follow_redirects=False, so a
    disabled-preview 302 is detected). No LLM — just t.me/s reachability + subscriber count."""
    timeout = httpx.Timeout(connect=5, read=6, write=5, pool=5)
    checks: dict = {}
    try:
        async with httpx.AsyncClient(timeout=timeout, headers=_UA, follow_redirects=False) as client:
            status, info = await _probe(client, username)
            checks["probe"] = status
            if status == "ok" and hasattr(info, "isoformat"):
                checks["newest"] = info.isoformat()
            checks["subscribers"] = await _fetch_subs(client, username)
    except Exception:
        checks["probe"] = "error"
    return checks


class ChannelSuggestRequest(BaseModel):
    init_data: str
    username: str = Field(max_length=120)
    city: str | None = None


@router.post("/channel")
async def suggest_channel(payload: ChannelSuggestRequest, request: Request, db: AsyncSession = Depends(get_async_db)):
    user = validate_init_data(payload.init_data)
    uid = user.get("id")
    if not uid:
        raise HTTPException(status_code=401, detail="no user")
    uname = _norm_channel(payload.username)
    if not uname:
        raise HTTPException(status_code=422, detail="Укажи @username канала (латиница, 5–32 символа)")
    if not await _rate_limit_ok(db, int(uid)):
        raise HTTPException(status_code=429, detail="Слишком много заявок за сегодня — попробуй завтра")
    # Already a source? (case-insensitive — stored usernames are mixed-case)
    row = (await db.execute(
        text("SELECT is_active FROM ref.telegram_channels WHERE LOWER(username) = :u"), {"u": uname}
    )).first()
    if row and row[0]:
        raise HTTPException(status_code=409, detail="Этот канал уже подключён — события из него уже собираем")
    reactivation = bool(row and not row[0])
    # Release the DB connection BEFORE the (bounded) outbound probe — otherwise the open transaction holds
    # a pooled connection for the whole probe and a few slow probes exhaust the per-worker pool (500s).
    await db.commit()
    # Cheap liveness check (no LLM), BOUNDED: a global semaphore caps concurrent outbound t.me probes and
    # wait_for caps total time, so a slow/hanging t.me can't pile up on the request path (DoS/amplification).
    async with _PROBE_SEM:
        try:
            checks = await asyncio.wait_for(_probe_channel(uname), timeout=_PROBE_BUDGET)
        except Exception:
            checks = {"probe": "error"}  # our own timeout/error → let the admin see «не проверен», don't 500
    checks["reactivation"] = reactivation
    if checks.get("probe") == "gone":
        raise HTTPException(status_code=422, detail="Канал не найден или без постов — проверь @username")
    city_slug = await _resolve_city_slug(db, int(uid), payload.city)
    data = {"username_norm": uname, "username_raw": payload.username.strip()[:120], "city_slug": city_slug}
    try:
        sid = await create_submission(
            db, kind="channel", data=data, submitted_by=int(uid),
            submitted_username=user.get("username"), city_slug=city_slug,
            status="needs_review", checks=checks,
        )
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=409, detail="Этот канал уже на модерации")
    return {"ok": True, "submission_id": sid, "status": "needs_review"}
