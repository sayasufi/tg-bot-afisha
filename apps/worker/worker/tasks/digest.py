"""Weekly digest sweep — the second OUTBOUND re-engagement loop.

Once a week, DMs each opted-in user one bundled roundup: what's newly listed at the venues
they follow + the best of the coming weekend in their city. Strictly opt-in (notify_digest),
sent over the raw Telegram HTTP API like the reminder sweep. Idempotent within a week via a
per-user ledger (ref.users.last_digest_sent_at) so a redeploy / manual re-run / missed-run
catchup never double-sends; only a thrown (transient) send leaves a user unstamped.
"""
import logging
from datetime import datetime, timedelta, timezone

import httpx

from apps.bot.bot.formatting import digest_message, weekend_label
from core.config.settings import get_settings
from core.db.repositories.digest import (
    mark_digest_sent,
    new_at_followed_venues,
    opted_in_users,
    rank_weekend,
    weekend_pool,
    weekend_window,
)
from core.db.session import WorkerAsyncSessionLocal
from core.redis import get_redis

log = logging.getLogger(__name__)
_BOT_USERNAME = "okrestmap_bot"


def _app_url() -> str:
    # startapp link with no event → opens the Mini App home ("вся афиша" button).
    return f"https://t.me/{_BOT_USERNAME}?startapp=weekend"


def _week_start_utc(now: datetime) -> datetime:
    """Monday 00:00 UTC of the current ISO week — the idempotency boundary. A digest sent at or
    after this instant counts as 'already sent this week'; an earlier stamp lets the user through."""
    midnight = now.astimezone(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    return midnight - timedelta(days=midnight.weekday())


async def _view_counts() -> dict:
    """rec:views as {event_id: int} — the LIVE popularity signal that ranks the weekend list.
    Loaded ONCE per sweep (one HGETALL), best-effort: {} on any failure so the digest still sends."""
    client = get_redis(decode=True)
    if client is None:
        return {}
    try:
        raw = await client.hgetall("rec:views")
        return {k: int(v) for k, v in raw.items() if str(v).lstrip("-").isdigit()}
    except Exception:  # pragma: no cover - cache is best-effort
        return {}


async def _send_digest_impl() -> int:
    token = get_settings().telegram_bot_token
    if not token:
        return 0
    base = f"https://api.telegram.org/bot{token}"
    now = datetime.now(timezone.utc)
    since = _week_start_utc(now)
    sent = 0
    async with WorkerAsyncSessionLocal() as db:
        users = await opted_in_users(db, since)
        if not users:
            return 0
        sat, sun, _, _ = weekend_window(now)
        label = weekend_label(sat, sun)
        markup = {"inline_keyboard": [[{"text": "вся афиша →", "url": _app_url()}]]}
        # Fetch the heavy shared inputs ONCE, not per user: the rec:views hash, and the weekend
        # pool per DISTINCT city among the opted-in users (a small dict cache). Per user we then
        # only run the personal followed-venues query + an in-memory rank.
        view_counts = await _view_counts()
        pools: dict[str | None, list[dict]] = {}
        # Users Telegram answered for (ok OR a permanent failure) — stamped once at the end so a
        # re-run this week skips them. A thrown (transient) send leaves the user out of this list.
        responded: list[int] = []
        async with httpx.AsyncClient(timeout=15) as client:
            for u in users:
                city = u.get("city_slug")
                if city not in pools:
                    pools[city] = await weekend_pool(db, city, now)
                venue_items = await new_at_followed_venues(db, u["user_id"], now)
                weekend_items = rank_weekend(
                    pools[city],
                    u.get("interests") or [],
                    [e["event_id"] for e in venue_items],
                    view_counts,
                )
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
                except Exception:  # transient network/infra → leave unstamped, retry next run
                    continue
                # Telegram answered (delivered, OR a permanent 403/400 like blocked/never-started)
                # → record the user so we stamp them and don't re-send this week.
                responded.append(u["user_id"])
                if resp.json().get("ok"):
                    sent += 1
        await mark_digest_sent(db, responded)
        await db.commit()
    if sent:
        log.info("sent %s digests", sent)
    return sent
