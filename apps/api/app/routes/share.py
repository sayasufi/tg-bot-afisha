"""Shareable event page with Open Graph tags — gives a branded card preview when
the link is shared into any Telegram chat (or anywhere)."""
from datetime import datetime
from html import escape
from uuid import UUID

from fastapi import APIRouter, HTTPException
from fastapi.responses import HTMLResponse
from sqlalchemy import select

from core.config.settings import get_settings
from core.db.models import Event, EventOccurrence, Venue
from core.db.session import SessionLocal

router = APIRouter(prefix="/v1/share", tags=["share"])

BOT_URL = "https://t.me/okrestmap_bot"

_MONTHS = [
    "января", "февраля", "марта", "апреля", "мая", "июня",
    "июля", "августа", "сентября", "октября", "ноября", "декабря",
]


def _when(dt: datetime | None) -> str:
    if not dt:
        return ""
    return f"{dt.day} {_MONTHS[dt.month - 1]}, {dt:%H:%M}"


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
    image = event.cached_image_url or event.primary_image_url or ""
    base = get_settings().telegram_webapp_url.rstrip("/")
    parts = [p for p in [_when(occ.date_start if occ else None), venue] if p]
    desc = " · ".join(parts) + (" · " if parts else "") + "Окрест — события рядом"
    cover_style = f"background-image:url('{escape(image)}')" if image else ""

    html = (
        _PAGE.replace("__TITLE__", escape(title))
        .replace("__DESC__", escape(desc))
        .replace("__IMAGE__", escape(image))
        .replace("__URL__", escape(f"{base}/v1/share/{event_id}"))
        .replace("__COVERSTYLE__", cover_style)
        .replace("__BOT__", BOT_URL)
    )
    return HTMLResponse(html, headers={"Cache-Control": "public, max-age=600"})
