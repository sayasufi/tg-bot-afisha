"""Cache external event images into MinIO (downscaled JPEG) for fast serving."""
import asyncio
import io
import logging

import httpx
from PIL import Image
from sqlalchemy import func, select, update

from core.config.settings import get_settings
from core.db.models import Event, EventSource, RawEvent, Source
from core.db.session import SessionLocal, WorkerAsyncSessionLocal
from core.http_safety import is_public_http_url
from core.media.storage import ensure_bucket, object_exists, public_url, put_image

logger = logging.getLogger(__name__)

MAX_WIDTH = 1080  # retina-sharp for the full-width poster in the event sheet
BATCH = 40


def _cache_one(db, event: Event) -> bool:
    src = (event.primary_image_url or "").strip()
    if not is_public_http_url(src):
        return False
    try:
        # follow_redirects=False so a public URL can't 30x into an internal host.
        resp = httpx.get(src, timeout=20, follow_redirects=False, headers={"User-Agent": "okrest-media/1.0"})
        resp.raise_for_status()
        img = Image.open(io.BytesIO(resp.content)).convert("RGB")
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
        if img.width > max_width:
            height = round(img.height * max_width / img.width)
            img = img.resize((max_width, height), Image.LANCZOS)
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=82, optimize=True)
        return buf.getvalue()
    except Exception:
        return data


_TG_IMG_CONCURRENCY = 4  # concurrent Telethon downloads (heavier than the t.me web; keep modest)


async def _cache_telegram_images_impl(cap: int = 400) -> dict:
    """Lazily fetch the photo for telegram EVENTS that have no image yet — i.e. posts that survived
    the whole pipeline (extraction → enrich → dedup → Event). The connector no longer downloads a
    photo per post (most posts aren't events); this pulls only the ones that matter, via Telethon.
    No-op without a Telethon session."""
    s = get_settings()
    if not (s.telethon_api_id and s.telethon_api_hash and s.telethon_session):
        return {"skipped": "no_telethon"}
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

    from telethon import TelegramClient
    from telethon.sessions import StringSession
    ensure_bucket()
    client = TelegramClient(StringSession(s.telethon_session), s.telethon_api_id, s.telethon_api_hash)
    await client.connect()
    if not await client.is_user_authorized():
        await client.disconnect()
        return {"skipped": "not_authorized"}
    sem = asyncio.Semaphore(_TG_IMG_CONCURRENCY)
    cached = 0

    async def _one(eid, channel: str, msgid: int) -> None:
        nonlocal cached
        key = f"telegram/{channel}/{msgid}.jpg"
        try:
            if not object_exists(key):
                async with sem:
                    msg = await client.get_messages(channel, ids=msgid)
                    if not msg or not getattr(msg, "photo", None):
                        return
                    data = await client.download_media(msg, file=bytes)
                if not data:
                    return
                put_image(key, _downscale_jpeg(data), "image/jpeg")
            async with WorkerAsyncSessionLocal() as db2:
                await db2.execute(update(Event).where(Event.event_id == eid).values(cached_image_url=public_url(key)))
                await db2.commit()
            cached += 1
        except Exception:
            logger.warning("telegram_image_cache_failed", extra={"event_id": str(eid), "channel": channel, "msgid": msgid}, exc_info=True)

    try:
        await asyncio.gather(*(_one(eid, ch, mid) for eid, (ch, mid) in targets.items()), return_exceptions=True)
    finally:
        await client.disconnect()
    return {"cached": cached, "candidates": len(targets)}
