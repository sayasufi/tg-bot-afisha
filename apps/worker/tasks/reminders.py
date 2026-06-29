"""Reminder sweep — the product's first OUTBOUND message.

Finds due saved-event reminders and DMs the user via the bot (a couple hours before the
event), then stamps sent_at so each fires once. Sends over the raw Telegram HTTP API
(same approach as the share prepare flow) — no aiogram session lifecycle in the flow.
"""
import asyncio
import json
import logging
from datetime import datetime, timezone

import httpx

from core.render.card import build_reminder_card
from core.render.formatting import reminder_caption, reminder_caption_card, when_phrase
from apps.worker.tasks.tg_send import PACE, classify, retry_after
from core.config.settings import get_settings
from core.db.repositories.reminders import due_reminders, mark_sent, reap_stale_reminders, sample_upcoming_event
from core.db.session import WorkerAsyncSessionLocal

log = logging.getLogger(__name__)
_BOT_USERNAME = "okrestmap_bot"
# Full-screen "fire" message effect — free, no Premium needed, private chats only (= our
# DMs). A reminder is inherently "starting soon", so the urgency animation fits every send.
_FIRE_EFFECT = "5104841245755180586"


def _open_url(event_id: str) -> str:
    # startapp deep link → opens the Mini App on this event.
    return f"https://t.me/{_BOT_USERNAME}?startapp={event_id}"


async def _send_reminder(client, base, r, caption, card_bytes, fallback_caption, markup) -> str:
    """Send one reminder: the composed VITRINE card uploaded as multipart bytes (with a short
    caption for the chat-list preview), falling back to a full-text DM if there's no card or the
    photo is rejected. One 429/5xx wait+retry. Returns 'ok' | 'permanent' (stamp, no retry) |
    'retry' (transient → do NOT stamp)."""
    text_payload = {
        "chat_id": r["user_id"], "text": fallback_caption, "parse_mode": "HTML",
        "reply_markup": markup, "disable_web_page_preview": True, "message_effect_id": _FIRE_EFFECT,
    }
    for attempt in range(2):
        try:
            if card_bytes:
                resp = await client.post(
                    f"{base}/sendPhoto",
                    data={"chat_id": str(r["user_id"]), "caption": caption, "parse_mode": "HTML",
                          "reply_markup": json.dumps(markup), "message_effect_id": _FIRE_EFFECT},
                    files={"photo": ("okrest.jpg", card_bytes, "image/jpeg")},
                )
                data = resp.json()
                if classify(data) == "permanent":
                    # Photo rejected → try the full text form before giving up.
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
        # Clear reminders whose time passed long ago (muted user / past downtime) so they neither
        # burst-fire on unmute nor keep the bell armed. Then send the genuinely-due ones.
        if await reap_stale_reminders(db, now):
            await db.commit()
        due = await due_reminders(db, now)
        if not due:
            return 0
        async with httpx.AsyncClient(timeout=20) as client:
            for r in due:
                # Render the fully-composed VITRINE card (photo hero + typeset when/title/code/venue/
                # price) off the event loop — PIL is CPU-bound and the `when` is live, so it's built
                # per send. Fall back to a full-text DM if it can't be built.
                item = {**r, "when": when_phrase(r.get("date_start"), r.get("date_end"), now)}
                try:
                    card_bytes = await asyncio.to_thread(build_reminder_card, item)
                except Exception:
                    card_bytes = None
                caption = reminder_caption_card(r, now) if card_bytes else reminder_caption(r, now)
                fallback = reminder_caption(r, now)
                markup = {"inline_keyboard": [[{"text": "смотреть →", "url": _open_url(r["event_id"])}]]}
                result = await _send_reminder(client, base, r, caption, card_bytes, fallback, markup)
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


async def send_test_reminder(only_user_id: int) -> int:
    """ТЕСТ из админки: отправить ОДНОМУ пользователю карточку-напоминание для образца ближайшего события
    (превью). НЕ трогает реальные напоминания (sent_at не ставит). Адресат — строго only_user_id (хард-гард)."""
    token = get_settings().telegram_bot_token
    if not token or not only_user_id:
        return 0
    base = f"https://api.telegram.org/bot{token}"
    now = datetime.now(timezone.utc)
    async with WorkerAsyncSessionLocal() as db:
        item = await sample_upcoming_event(db, now)
    if not item:
        return 0
    item["user_id"] = int(only_user_id)  # ХАРД-таргет: единственный адресат превью
    item["when"] = when_phrase(item.get("date_start"), item.get("date_end"), now)
    try:
        card_bytes = await asyncio.to_thread(build_reminder_card, item)
    except Exception:
        card_bytes = None
    caption = reminder_caption_card(item, now) if card_bytes else reminder_caption(item, now)
    markup = {"inline_keyboard": [[{"text": "смотреть →", "url": _open_url(item["event_id"])}]]}
    async with httpx.AsyncClient(timeout=20) as client:
        result = await _send_reminder(client, base, item, caption, card_bytes, reminder_caption(item, now), markup)
    return 1 if result == "ok" else 0
