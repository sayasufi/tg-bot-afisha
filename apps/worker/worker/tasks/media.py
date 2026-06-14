"""Cache external event images into MinIO (downscaled JPEG) for fast serving."""
import io
import ipaddress
import logging
import socket
from urllib.parse import urlparse

import httpx
from PIL import Image
from sqlalchemy import select

from apps.worker.worker.celery_app import celery_app
from core.db.models import Event
from core.db.session import SessionLocal
from core.media.storage import ensure_bucket, public_url, put_image

logger = logging.getLogger(__name__)

MAX_WIDTH = 900
BATCH = 40


def _is_public_url(url: str) -> bool:
    """SSRF guard: image URLs come from external feeds, so only allow http(s)
    hosts that resolve exclusively to globally-routable IPs (no loopback,
    private, link-local or reserved ranges)."""
    try:
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https") or not parsed.hostname:
            return False
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
        infos = socket.getaddrinfo(parsed.hostname, port, proto=socket.IPPROTO_TCP)
        if not infos:
            return False
        return all(ipaddress.ip_address(info[4][0]).is_global for info in infos)
    except Exception:
        return False


def _cache_one(db, event: Event) -> bool:
    src = (event.primary_image_url or "").strip()
    if not _is_public_url(src):
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


@celery_app.task(name="apps.worker.worker.tasks.media.cache_event_images")
def cache_event_images() -> dict:
    """Cache a batch of not-yet-cached event images into MinIO."""
    ensure_bucket()
    db = SessionLocal()
    cached = 0
    events: list[Event] = []
    try:
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
    finally:
        db.close()
    return {"scanned": len(events), "cached": cached}
