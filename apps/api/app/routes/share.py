"""Shareable event page with Open Graph tags — gives a branded card preview when
the link is shared into any Telegram chat (or anywhere)."""
from datetime import datetime
from html import escape
from urllib.parse import urlparse
from uuid import UUID

import httpx
from fastapi import APIRouter, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from sqlalchemy import select

from apps.api.app.services.card import ensure_card
from apps.api.app.services.telegram_auth import validate_init_data
from core.config.settings import get_settings
from core.db.models import Event, EventOccurrence, Venue
from core.db.session import SessionLocal

router = APIRouter(prefix="/v1/share", tags=["share"])

BOT_USERNAME = "okrestmap_bot"


def _open_url(event_id) -> str:
    # startapp deep link → opens the Mini App with this event as the start param.
    return f"https://t.me/{BOT_USERNAME}?startapp={event_id}"

_MONTHS = [
    "января", "февраля", "марта", "апреля", "мая", "июня",
    "июля", "августа", "сентября", "октября", "ноября", "декабря",
]


def _when(dt: datetime | None) -> str:
    if not dt:
        return ""
    return f"{dt.day} {_MONTHS[dt.month - 1]}, {dt:%H:%M}"


def _safe_image(url: str) -> str:
    """Image URLs may come from untrusted feeds and land in inline CSS url() and
    meta attributes — html.escape is the wrong context, so validate strictly:
    only clean http(s) URLs without quotes/backslash/parens/whitespace."""
    if not url:
        return ""
    try:
        scheme = urlparse(url).scheme
    except Exception:
        return ""
    if scheme not in ("http", "https"):
        return ""
    if any(c in url for c in "'\"\\()<> \n\r\t"):
        return ""
    return url


_PAGE = """<!doctype html>
<html lang="ru">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>__TITLE__ — Окрест</title>
<meta property="og:type" content="website">
<meta property="og:site_name" content="Окрест">
<meta property="og:title" content="__TITLE__">
<meta property="og:description" content="__DESC__">
<meta property="og:image" content="__IMAGE__">
<meta property="og:url" content="__URL__">
<meta name="twitter:card" content="summary_large_image">
<meta name="twitter:title" content="__TITLE__">
<meta name="twitter:description" content="__DESC__">
<meta name="twitter:image" content="__IMAGE__">
<style>
  * { margin: 0; box-sizing: border-box; }
  body { background: #f4f4ef; color: #0b0b0b; font-family: -apple-system, "Segoe UI", system-ui, sans-serif;
         min-height: 100vh; display: flex; align-items: center; justify-content: center; padding: 24px; }
  .card { width: 100%; max-width: 380px; background: #fff; border: 1px solid #0b0b0b; }
  .cover { aspect-ratio: 16 / 9; background: #ccff00 center/cover no-repeat; border-bottom: 1px solid #0b0b0b; }
  .body { padding: 22px 20px 24px; }
  .brand { display: inline-flex; align-items: center; gap: 7px; font-weight: 800; letter-spacing: -.04em;
           font-size: 18px; text-transform: lowercase; margin-bottom: 14px; }
  .brand svg { width: .9em; height: .9em; }
  .title { font-size: 24px; font-weight: 800; line-height: 1.15; letter-spacing: -.02em; margin-bottom: 12px; }
  .meta { font-size: 13px; letter-spacing: .04em; text-transform: uppercase; color: #6b6b66; margin-bottom: 22px; }
  .open { display: block; text-align: center; text-decoration: none; background: #ccff00; color: #0b0b0b;
          font-weight: 700; letter-spacing: .08em; text-transform: uppercase; font-size: 13px; padding: 16px;
          border: 1px solid #0b0b0b; box-shadow: 1.6px 1.6px 0 #e63312; }
</style>
</head>
<body>
  <div class="card">
    <div class="cover" style="__COVERSTYLE__"></div>
    <div class="body">
      <span class="brand">
        <svg viewBox="0 0 512 512" aria-hidden="true"><path d="M256 56 C168.9 56 98 126.9 98 214 C98 320 256 456 256 456 C256 456 414 320 414 214 C414 126.9 343.1 56 256 56 Z" fill="#0b0b0b"/><circle cx="256" cy="202" r="84" fill="#ccff00"/><circle cx="256" cy="202" r="32" fill="#0b0b0b"/></svg>окрест
      </span>
      <div class="title">__TITLE__</div>
      <div class="meta">__DESC__</div>
      <a class="open" href="__BOT__">Открыть в Окрест</a>
    </div>
  </div>
</body>
</html>"""


@router.get("/{event_id}", response_class=HTMLResponse)
def share(event_id: UUID):
    db = SessionLocal()
    try:
        row = db.execute(
            select(Event, EventOccurrence, Venue.name.label("venue"))
            .join(EventOccurrence, EventOccurrence.event_id == Event.event_id)
            .outerjoin(Venue, Venue.venue_id == EventOccurrence.venue_id)
            .where(Event.event_id == event_id)
            .order_by(EventOccurrence.date_start.asc())
            .limit(1)
        ).first()
    finally:
        db.close()
    if not row:
        raise HTTPException(status_code=404, detail="not found")

    event, occ, venue = row
    title = event.canonical_title or "Событие"
    image = _safe_image(event.cached_image_url or event.primary_image_url or "")
    base = get_settings().telegram_webapp_url.rstrip("/")
    parts = [p for p in [_when(occ.date_start if occ else None), venue] if p]
    desc = " · ".join(parts) + (" · " if parts else "") + "Окрест — события рядом"
    # Branded VITRINE card for the link preview; raw photo for the page cover.
    card = ensure_card(str(event_id), title, " · ".join(parts) or "Событие", event.category, image)
    og_image = card or image
    cover_style = f"background-image:url('{image}')" if image else ""

    html = (
        _PAGE.replace("__TITLE__", escape(title))
        .replace("__DESC__", escape(desc))
        .replace("__IMAGE__", escape(og_image))
        .replace("__URL__", escape(f"{base}/v1/share/{event_id}"))
        .replace("__COVERSTYLE__", cover_style)
        .replace("__BOT__", _open_url(event_id))
    )
    return HTMLResponse(html, headers={"Cache-Control": "public, max-age=600"})


class PrepareRequest(BaseModel):
    init_data: str
    event_id: UUID


@router.post("/prepare")
def prepare(payload: PrepareRequest):
    """Prepare a photo inline-message for the user so the Mini App can share an
    actual image (not a link) into any chat via Telegram.WebApp.shareMessage."""
    user = validate_init_data(payload.init_data)
    uid = user.get("id")
    settings = get_settings()
    if not uid or not settings.telegram_bot_token:
        raise HTTPException(status_code=400, detail="cannot prepare")

    db = SessionLocal()
    try:
        row = db.execute(
            select(Event, EventOccurrence, Venue.name.label("venue"))
            .join(EventOccurrence, EventOccurrence.event_id == Event.event_id)
            .outerjoin(Venue, Venue.venue_id == EventOccurrence.venue_id)
            .where(Event.event_id == payload.event_id)
            .order_by(EventOccurrence.date_start.asc())
            .limit(1)
        ).first()
    finally:
        db.close()
    if not row:
        raise HTTPException(status_code=404, detail="not found")

    event, occ, venue = row
    title = event.canonical_title or "Событие"
    image = _safe_image(event.cached_image_url or event.primary_image_url or "")
    parts = [p for p in [_when(occ.date_start if occ else None), venue] if p]
    # Send the branded VITRINE card as the photo; fall back to the raw image.
    photo_url = ensure_card(str(payload.event_id), title, " · ".join(parts) or "Событие", event.category, image) or image
    if not photo_url:
        return {"ok": False}  # nothing to send → caller falls back to a link share

    caption = f"<b>{escape(title)}</b>"
    if parts:
        caption += "\n" + escape(" · ".join(parts))
    caption += "\nОкрест — события рядом"

    result = {
        "type": "photo",
        "id": str(payload.event_id),
        "photo_url": photo_url,
        "thumbnail_url": photo_url,
        "caption": caption[:1024],
        "parse_mode": "HTML",
        "reply_markup": {"inline_keyboard": [[{"text": "Открыть в Окрест", "url": _open_url(payload.event_id)}]]},
    }
    try:
        resp = httpx.post(
            f"https://api.telegram.org/bot{settings.telegram_bot_token}/savePreparedInlineMessage",
            json={
                "user_id": int(uid),
                "result": result,
                "allow_user_chats": True,
                "allow_group_chats": True,
                "allow_channel_chats": True,
            },
            timeout=10,
        )
        data = resp.json()
    except Exception:
        raise HTTPException(status_code=502, detail="telegram unreachable")

    if not data.get("ok"):
        return {"ok": False}
    return {"ok": True, "id": data["result"]["id"]}
