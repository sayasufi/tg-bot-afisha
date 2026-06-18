"""Reminder sweep — the product's first OUTBOUND message.

Finds due saved-event reminders and DMs the user via the bot (a couple hours before the
event), then stamps sent_at so each fires once. Sends over the raw Telegram HTTP API
(same approach as the share prepare flow) — no aiogram session lifecycle in the flow.
"""
import asyncio
import logging
from datetime import datetime, timezone

import httpx

from apps.api.app.services.card import ensure_reminder_cover
from apps.bot.bot.formatting import reminder_caption
from core.config.settings import get_settings
from core.db.repositories.reminders import due_reminders, mark_sent
from core.db.session import WorkerAsyncSessionLocal

log = logging.getLogger(__name__)
_BOT_USERNAME = "okrestmap_bot"
# Full-screen "fire" message effect — free, no Premium needed, private chats only (= our
# DMs). A reminder is inherently "starting soon", so the urgency animation fits every send.
_FIRE_EFFECT = "5104841245755180586"


def _open_url(event_id: str) -> str:
    # startapp deep link → opens the Mini App on this event.
    return f"https://t.me/{_BOT_USERNAME}?startapp={event_id}"


async def _send_reminders_impl() -> int:
    token = get_settings().telegram_bot_token
    if not token:
        return 0
    base = f"https://api.telegram.org/bot{token}"
    now = datetime.now(timezone.utc)
    sent = 0
    async with WorkerAsyncSessionLocal() as db:
        due = await due_reminders(db, now)
        if not due:
            return 0
        async with httpx.AsyncClient(timeout=15) as client:
            for r in due:
                caption = reminder_caption(r, now)
                raw_image = r.get("image")
                # Brand the cover (acid spine, hairline, окрест wordmark, code, colour ribbon),
                # rendered+cached in MinIO; fall back to the raw photo if branding fails.
                image = raw_image
                if raw_image:
                    try:
                        branded = await asyncio.to_thread(
                            ensure_reminder_cover, r["event_id"], raw_image, r.get("code")
                        )
                        if branded:
                            image = branded
                    except Exception:
                        image = raw_image
                markup = {"inline_keyboard": [[{"text": "смотреть →", "url": _open_url(r["event_id"])}]]}
                got_response = False
                ok = False
                try:
                    if image:
                        # The event cover as a photo + the caption — a real VITRINE card,
                        # not a text list. Fall back to a text message if Telegram can't
                        # fetch the image (expired/oversized URL) so the reminder still lands.
                        resp = await client.post(
                            f"{base}/sendPhoto",
                            json={"chat_id": r["user_id"], "photo": image, "caption": caption,
                                  "parse_mode": "HTML", "reply_markup": markup, "message_effect_id": _FIRE_EFFECT},
                        )
                        got_response = True
                        ok = bool(resp.json().get("ok"))
                        if not ok:
                            resp = await client.post(
                                f"{base}/sendMessage",
                                json={"chat_id": r["user_id"], "text": caption, "parse_mode": "HTML",
                                      "reply_markup": markup, "disable_web_page_preview": True,
                                  "message_effect_id": _FIRE_EFFECT},
                            )
                            ok = bool(resp.json().get("ok"))
                    else:
                        resp = await client.post(
                            f"{base}/sendMessage",
                            json={"chat_id": r["user_id"], "text": caption, "parse_mode": "HTML",
                                  "reply_markup": markup, "disable_web_page_preview": True,
                                  "message_effect_id": _FIRE_EFFECT},
                        )
                        got_response = True
                        ok = bool(resp.json().get("ok"))
                except Exception:  # transient network/infra → leave unsent, retry next sweep
                    got_response = False
                # Telegram answered (delivered, OR a permanent 403/400 like blocked/never-started)
                # → stamp sent so we don't retry forever. Only a thrown request retries.
                if got_response:
                    await mark_sent(db, r["user_id"], r["event_id"])
                    if ok:
                        sent += 1
            await db.commit()
    if sent:
        log.info("sent %s reminders", sent)
    return sent
