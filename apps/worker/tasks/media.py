"""Cache external event images into MinIO (downscaled JPEG) for fast serving."""
import asyncio
import io
import logging
import re

import httpx
from PIL import Image, ImageFile, UnidentifiedImageError
from sqlalchemy import func, select, update

from core.db.models import Event, EventSource, RawEvent, Source
from core.db.session import SessionLocal, WorkerAsyncSessionLocal
from core.infra.http_safety import is_public_http_url
from core.media.storage import ensure_bucket, object_exists, public_url, put_image

logger = logging.getLogger(__name__)

MAX_WIDTH = 1080  # retina-sharp for the full-width poster in the event sheet
BATCH = 40

# Some source posters arrive truncated (a dropped connection mid-download) — let PIL render the
# partial image instead of raising OSError, so a good-enough poster still caches.
ImageFile.LOAD_TRUNCATED_IMAGES = True


def _cache_one(db, event: Event) -> bool:
    src = (event.primary_image_url or "").strip()
    if not is_public_http_url(src):
        return False
    try:
        # follow_redirects=False so a public URL can't 30x into an internal host.
        resp = httpx.get(src, timeout=20, follow_redirects=False, headers={"User-Agent": "okrest-media/1.0"})
        resp.raise_for_status()
        img = Image.open(io.BytesIO(resp.content)).convert("RGB")
        img.info.pop("xmp", None)  # some posters carry XMP > 64 KB, which overflows the JPEG marker on save
        if img.width > MAX_WIDTH:
            height = round(img.height * MAX_WIDTH / img.width)
            img = img.resize((MAX_WIDTH, height), Image.LANCZOS)
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=82, optimize=True)
        key = f"events/{event.event_id}.jpg"
        put_image(key, buf.getvalue(), "image/jpeg")
        event.cached_image_url = public_url(key)
        db.add(event)
        return True
    except (httpx.HTTPError, UnidentifiedImageError) as exc:
        # Expected at scale — a blocked/dead/malformed image URL, or bytes that aren't an image.
        # Skip just this one image (the event keeps its source URL); a one-line INFO, not a
        # stack-trace WARNING, so health checks aren't drowned in benign image-cache noise.
        logger.info("media cache skip %s: %s", event.event_id, type(exc).__name__)
        return False
    except Exception:
        logger.warning("media cache failed for %s (%s)", event.event_id, src, exc_info=True)
        return False


def _cache_event_images_impl() -> dict:
    """Cache a batch of not-yet-cached event images into MinIO. Per-image failures are
    logged and skipped (one bad URL must not fail the batch); infra failures (MinIO,
    DB) propagate so the caller retries."""
    db = SessionLocal()
    cached = 0
    events: list[Event] = []
    try:
        ensure_bucket()
        events = (
            db.execute(
                select(Event)
                .where(
                    Event.status == "active",
                    Event.cached_image_url.is_(None),
                    Event.primary_image_url != "",
                )
                .limit(BATCH)
            )
            .scalars()
            .all()
        )
        for event in events:
            if _cache_one(db, event):
                cached += 1
        db.commit()
        return {"scanned": len(events), "cached": cached}
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def _downscale_jpeg(data: bytes, max_width: int = MAX_WIDTH) -> bytes:
    """Downscale to <=max_width and re-encode JPEG (mirrors _cache_one); original bytes on failure."""
    try:
        img = Image.open(io.BytesIO(data)).convert("RGB")
        img.info.pop("xmp", None)  # strip oversized XMP so the JPEG re-encode can't raise
        if img.width > max_width:
            height = round(img.height * max_width / img.width)
            img = img.resize((max_width, height), Image.LANCZOS)
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=82, optimize=True)
        return buf.getvalue()
    except Exception:
        return data


_TG_IMG_CONCURRENCY = 8  # concurrent HTTP fetches (lighter than the old Telethon download path)
_UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"}
# The single-post page carries the post's photo as og:image (a cdn*.telesco.pe URL). Match either order.
_OG_IMAGE_RE = re.compile(r'<meta[^>]+property="og:image"[^>]+content="([^"]+)"')
_OG_IMAGE_RE2 = re.compile(r'<meta[^>]+content="([^"]+)"[^>]+property="og:image"')


async def _post_image_url(client: httpx.AsyncClient, channel: str, msgid: int) -> str | None:
    """The post's photo URL from t.me/<channel>/<msgid> og:image — plain HTTP, no Telethon/flood limits."""
    try:
        r = await client.get(f"https://t.me/{channel}/{msgid}")
    except httpx.HTTPError:
        return None
    if r.status_code != 200:
        return None
    for rx in (_OG_IMAGE_RE, _OG_IMAGE_RE2):
        m = rx.search(r.text)
        if m:
            url = m.group(1).strip()
            if url.startswith("http"):
                return url
    return None


async def _cache_telegram_images_impl(cap: int = 400) -> dict:
    """Fetch the photo for telegram EVENTS that have no image yet, over PLAIN HTTP: the single-post page
    (t.me/<channel>/<msgid>) carries the photo as og:image. Replaces the old Telethon downloader, which
    hit flood limits and failed; aligns with the web-preview fetch. Web-preview-fetched events already
    carry image URLs in their payload and are handled by _cache_event_images_impl, so this targets the
    has_photo posts that have no URL of their own."""
    async with WorkerAsyncSessionLocal() as db:
        rows = (await db.execute(
            select(Event.event_id, RawEvent.raw_payload_json)
            .join(EventSource, EventSource.event_id == Event.event_id)
            .join(Source, Source.source_id == EventSource.source_id)
            .join(RawEvent, RawEvent.raw_id == EventSource.raw_id)
            .where(
                Event.status == "active",
                Source.name.like("telegram_public:%"),
                func.coalesce(Event.cached_image_url, "") == "",
                func.coalesce(Event.primary_image_url, "") == "",
            )
            .limit(cap)
        )).all()
    targets: dict = {}
    for eid, payload in rows:
        p = payload or {}
        if eid not in targets and p.get("has_photo") and p.get("channel_username") and p.get("id"):
            targets[eid] = (p["channel_username"], int(p["id"]))
    if not targets:
        return {"cached": 0, "candidates": 0}

    ensure_bucket()
    sem = asyncio.Semaphore(_TG_IMG_CONCURRENCY)
    cached = 0
    timeout = httpx.Timeout(connect=10, read=20, write=10, pool=10)

    async def _one(http: httpx.AsyncClient, eid, channel: str, msgid: int) -> None:
        nonlocal cached
        key = f"telegram/{channel}/{msgid}.jpg"
        try:
            if not object_exists(key):
                async with sem:
                    img_url = await _post_image_url(http, channel, msgid)
                    if not img_url or not is_public_http_url(img_url):
                        return
                    # follow_redirects=False on the actual download → a URL can't 30x into internal space.
                    resp = await http.get(img_url, follow_redirects=False)
                    resp.raise_for_status()
                    data = resp.content
                if not data:
                    return
                put_image(key, _downscale_jpeg(data), "image/jpeg")
            async with WorkerAsyncSessionLocal() as db2:
                await db2.execute(update(Event).where(Event.event_id == eid).values(cached_image_url=public_url(key)))
                await db2.commit()
            cached += 1
        except httpx.HTTPError as exc:
            # Expected — a dead/blocked og:image URL or a transient fetch drop; skip just this image.
            logger.info("telegram image cache skip %s: %s", eid, type(exc).__name__)
        except Exception:
            logger.warning("telegram_image_cache_failed", extra={"event_id": str(eid), "channel": channel, "msgid": msgid}, exc_info=True)

    async with httpx.AsyncClient(timeout=timeout, headers=_UA, follow_redirects=True) as http:
        await asyncio.gather(*(_one(http, eid, ch, mid) for eid, (ch, mid) in targets.items()), return_exceptions=True)
    return {"cached": cached, "candidates": len(targets)}
