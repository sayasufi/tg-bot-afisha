"""Weekly digest sweep — the second OUTBOUND re-engagement loop.

Once a week, DMs each opted-in user one bundled roundup: what's newly listed at the venues
they follow + the best of the coming weekend in their city. Strictly opt-in (notify_digest),
sent over the raw Telegram HTTP API like the reminder sweep. Not idempotent across re-runs by
design — the cron fires once and the flow does not retry (a double-send is worse than a miss).
"""
import logging
from datetime import datetime, timezone

import httpx

from apps.bot.bot.formatting import digest_message, weekend_label
from core.config.settings import get_settings
from core.db.repositories.digest import build_digest, opted_in_users, weekend_window
from core.db.session import WorkerAsyncSessionLocal

log = logging.getLogger(__name__)
_BOT_USERNAME = "okrestmap_bot"


def _app_url() -> str:
    # startapp link with no event → opens the Mini App home ("вся афиша" button).
    return f"https://t.me/{_BOT_USERNAME}?startapp=weekend"


async def _send_digest_impl() -> int:
    token = get_settings().telegram_bot_token
    if not token:
        return 0
    base = f"https://api.telegram.org/bot{token}"
    now = datetime.now(timezone.utc)
    sent = 0
    async with WorkerAsyncSessionLocal() as db:
        users = await opted_in_users(db)
        if not users:
            return 0
        sat, sun, _, _ = weekend_window(now)
        label = weekend_label(sat, sun)
        markup = {"inline_keyboard": [[{"text": "вся афиша →", "url": _app_url()}]]}
        async with httpx.AsyncClient(timeout=15) as client:
            for u in users:
                venue_items, weekend_items = await build_digest(db, u, now)
                if not venue_items and not weekend_items:
                    continue  # nothing fresh for this user this week — stay quiet
                text = digest_message(venue_items, weekend_items, label, now)
                try:
                    resp = await client.post(
                        f"{base}/sendMessage",
                        json={
                            "chat_id": u["user_id"],
                            "text": text,
                            "parse_mode": "HTML",
                            "reply_markup": markup,
                            "disable_web_page_preview": True,
                        },
                    )
                    if resp.json().get("ok"):
                        sent += 1
                except Exception:  # transient send failure → skip this user (no retry, no double-send)
                    continue
    if sent:
        log.info("sent %s digests", sent)
    return sent
