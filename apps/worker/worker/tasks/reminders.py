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
from apps.worker.worker.tasks.tg_send import PACE, classify, retry_after
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


async def _send_reminder(client, base, r, caption, image, markup) -> str:
    """Send one reminder (photo with a text fallback), with a single 429/5xx wait+retry. Returns
    'ok' | 'permanent' (deliver-failed for good → stamp, no retry) | 'retry' (transient → do NOT stamp)."""
    text_payload = {
        "chat_id": r["user_id"], "text": caption, "parse_mode": "HTML",
        "reply_markup": markup, "disable_web_page_preview": True, "message_effect_id": _FIRE_EFFECT,
    }
    for attempt in range(2):
        try:
            if image:
                resp = await client.post(
                    f"{base}/sendPhoto",
                    json={"chat_id": r["user_id"], "photo": image, "caption": caption, "parse_mode": "HTML",
                          "reply_markup": markup, "message_effect_id": _FIRE_EFFECT},
                )
                data = resp.json()
                if classify(data) == "permanent":
                    # Photo rejected (expired/oversized URL) — try the text form before giving up.
                    resp = await client.post(f"{base}/sendMessage", json=text_payload)
                    data = resp.json()
            else:
                resp = await client.post(f"{base}/sendMessage", json=text_payload)
                data = resp.json()
        except Exception:
            return "retry"  # transient network/infra → leave unsent, next sweep retries
        verdict = classify(data)
        if verdict != "retry":
            return verdict
        if attempt == 0:
            await asyncio.sleep(retry_after(data))  # flood-wait → wait once, then retry
    return "retry"


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
                raw_image = r.get("image")  # cached/reliable — the raw-photo fallback
                # Brand the cover from the ORIGINAL full-res source (acid spine, grain,
                # окрест wordmark, code), rendered+cached in MinIO; fall back to the raw photo.
                image = raw_image
                src_for_brand = r.get("image_primary") or raw_image
                if src_for_brand:
                    try:
                        branded = await asyncio.to_thread(
                            ensure_reminder_cover, r["event_id"], src_for_brand, r.get("code")
                        )
                        if branded:
                            image = branded
                    except Exception:
                        image = raw_image
                markup = {"inline_keyboard": [[{"text": "смотреть →", "url": _open_url(r["event_id"])}]]}
                result = await _send_reminder(client, base, r, caption, image, markup)
                if result == "retry":
                    continue  # 429 / transient → leave unstamped; the next sweep retries it
                # Delivered OR permanently undeliverable (blocked / never started) → stamp ONCE and
                # commit NOW, so a flow retry or a mid-sweep crash can't re-send to anyone already done.
                await mark_sent(db, r["user_id"], r["event_id"])
                await db.commit()
                if result == "ok":
                    sent += 1
                await asyncio.sleep(PACE)  # stay under Telegram's flood threshold
    if sent:
        log.info("sent %s reminders", sent)
    return sent
