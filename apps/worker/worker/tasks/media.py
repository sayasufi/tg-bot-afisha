"""Cache external event images into MinIO (downscaled JPEG) for fast serving."""
import io
import logging

import httpx
from PIL import Image
from sqlalchemy import select

from core.db.models import Event
from core.db.session import SessionLocal
from core.http_safety import is_public_http_url
from core.media.storage import ensure_bucket, public_url, put_image

logger = logging.getLogger(__name__)

MAX_WIDTH = 900
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
