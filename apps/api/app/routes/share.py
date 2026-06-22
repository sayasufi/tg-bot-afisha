"""Shareable event page with Open Graph tags — gives a branded card preview when
the link is shared into any Telegram chat (or anywhere)."""
from datetime import datetime
from html import escape
from urllib.parse import urlparse
from uuid import UUID

import httpx
from fastapi import APIRouter, Depends, HTTPException
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.app.services.card import ensure_card
from apps.api.app.services.telegram_auth import validate_init_data
from core.codes import event_code
from core.config.settings import get_settings
from core.invite import sign as invite_sign
from core.db.models import Event, EventOccurrence, Venue
from core.db.session import get_async_db

router = APIRouter(prefix="/v1/share", tags=["share"])

BOT_USERNAME = "okrestmap_bot"


def _open_url(event_id, inviter=None) -> str:
    # startapp deep link → opens the Mini App on this event. With an inviter it becomes an answerable
    # invite («тебя зовут» + «Я иду»). Format «<uuid>_<inviter>_<sig>»: the UUID has no '_', so the App
    # splits on '_'; the HMAC sig proves we minted this inviter id so it can't be forged to spam DMs.
    if inviter:
        sig = invite_sign(str(event_id), int(inviter))
        param = f"{event_id}_{inviter}_{sig}"
    else:
        param = f"{event_id}"
    return f"https://t.me/{BOT_USERNAME}?startapp={param}"

_MONTHS = [
    "января", "февраля", "марта", "апреля", "мая", "июня",
    "июля", "августа", "сентября", "октября", "ноября", "декабря",
]


def _when(dt: datetime | None) -> str:
    if not dt:
        return ""
    return f"{dt.day} {_MONTHS[dt.month - 1]}, {dt:%H:%M}"


def _card_when(dt: datetime | None) -> str:
    """Event date for the card's lead line — '16 июня · 16:15' (the card uses · separators)."""
    if not dt:
        return ""
    return f"{dt.day} {_MONTHS[dt.month - 1]} · {dt:%H:%M}"


def _card_item(event, occ, venue, city) -> dict:
    """The data the unified share card needs (code · title · category · venue · price · date)."""
    return {
        "code": event_code(event.display_no, city) if event.display_no else "",
        "title": event.canonical_title or "Событие",
        "category": event.category,
        "venue": venue,
        "price_min": float(occ.price_min) if occ and occ.price_min is not None else None,
        "when": _card_when(occ.date_start if occ else None),
    }


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
async def share(event_id: UUID, ref: int | None = None, db: AsyncSession = Depends(get_async_db)):
    row = (
        await db.execute(
            select(Event, EventOccurrence, Venue.name.label("venue"), Venue.city.label("city"))
            .join(EventOccurrence, EventOccurrence.event_id == Event.event_id)
            .outerjoin(Venue, Venue.venue_id == EventOccurrence.venue_id)
            .where(Event.event_id == event_id)
            .order_by(EventOccurrence.date_start.asc())
            .limit(1)
        )
    ).first()
    if not row:
        raise HTTPException(status_code=404, detail="not found")

    event, occ, venue, city = row
    title = event.canonical_title or "Событие"
    image = _safe_image(event.cached_image_url or event.primary_image_url or "")
    base = get_settings().telegram_webapp_url.rstrip("/")
    parts = [p for p in [_when(occ.date_start if occ else None), venue] if p]
    desc = " · ".join(parts) + (" · " if parts else "") + "Окрест — события рядом"
    # Unified VITRINE card for the link preview; raw photo for the page cover. The render is
    # blocking (image fetch + PIL + MinIO), so it runs in a worker thread, not the event loop.
    card = await run_in_threadpool(
        ensure_card, str(event_id), _card_item(event, occ, venue, city), image
    )
    og_image = card or image
    cover_style = f"background-image:url('{image}')" if image else ""

    html = (
        _PAGE.replace("__TITLE__", escape(title))
        .replace("__DESC__", escape(desc))
        .replace("__IMAGE__", escape(og_image))
        .replace("__URL__", escape(f"{base}/v1/share/{event_id}"))
        .replace("__COVERSTYLE__", cover_style)
        .replace("__BOT__", _open_url(event_id, ref))
    )
    # Don't shared-cache the invite variant (the button differs per inviter); the plain page can.
    cache = "no-store" if ref else "public, max-age=600"
    return HTMLResponse(html, headers={"Cache-Control": cache})


class PrepareRequest(BaseModel):
    init_data: str
    event_id: UUID


@router.post("/prepare")
async def prepare(payload: PrepareRequest, db: AsyncSession = Depends(get_async_db)):
    """Prepare a photo inline-message for the user so the Mini App can share an
    actual image (not a link) into any chat via Telegram.WebApp.shareMessage."""
    user = validate_init_data(payload.init_data)  # HMAC check — fast, fine on the loop
    uid = user.get("id")
    settings = get_settings()
    if not uid or not settings.telegram_bot_token:
        raise HTTPException(status_code=400, detail="cannot prepare")

    row = (
        await db.execute(
            select(Event, EventOccurrence, Venue.name.label("venue"), Venue.city.label("city"))
            .join(EventOccurrence, EventOccurrence.event_id == Event.event_id)
            .outerjoin(Venue, Venue.venue_id == EventOccurrence.venue_id)
            .where(Event.event_id == payload.event_id)
            .order_by(EventOccurrence.date_start.asc())
            .limit(1)
        )
    ).first()
    if not row:
        raise HTTPException(status_code=404, detail="not found")

    event, occ, venue, city = row
    title = event.canonical_title or "Событие"
    image = _safe_image(event.cached_image_url or event.primary_image_url or "")
    parts = [p for p in [_when(occ.date_start if occ else None), venue] if p]
    # Send the unified VITRINE card as the photo; fall back to the raw image. The blocking
    # render runs in a worker thread.
    photo_url = (
        await run_in_threadpool(ensure_card, str(payload.event_id), _card_item(event, occ, venue, city), image)
        or image
    )
    if not photo_url:
        return {"ok": False}  # nothing to send → caller falls back to a link share

    # The card already carries date · venue · price; keep the caption light — bold title + a meta line.
    caption = f"<b>{escape(title)}</b>"
    if parts:
        caption += "\n\n" + escape(" · ".join(parts))

    result = {
        "type": "photo",
        "id": str(payload.event_id),
        "photo_url": photo_url,
        "thumbnail_url": photo_url,
        "caption": caption[:1024],
        "parse_mode": "HTML",
        "reply_markup": {"inline_keyboard": [[{"text": "Открыть в Окрест", "url": _open_url(payload.event_id, uid)}]]},
    }
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(
                f"https://api.telegram.org/bot{settings.telegram_bot_token}/savePreparedInlineMessage",
                json={
                    "user_id": int(uid),
                    "result": result,
                    "allow_user_chats": True,
                    "allow_group_chats": True,
                    "allow_channel_chats": True,
                },
            )
        data = resp.json()
    except Exception:
        raise HTTPException(status_code=502, detail="telegram unreachable")

    if not data.get("ok"):
        return {"ok": False}
    return {"ok": True, "id": data["result"]["id"]}
