"""Weekly digest sweep — the second OUTBOUND re-engagement loop.

Once a week, DMs each opted-in user one bundled roundup: what's newly listed at the venues
they follow + the best of the coming weekend in their city. Strictly opt-in (notify_digest),
sent over the raw Telegram HTTP API like the reminder sweep. Idempotent within a week via a
per-user ledger (ref.users.last_digest_sent_at) so a redeploy / manual re-run / missed-run
catchup never double-sends; only a thrown (transient) send leaves a user unstamped.
"""
import asyncio
import json
import logging
from datetime import datetime, timedelta, timezone

import httpx

from core.render.card import render_digest_poster
from core.render.formatting import digest_caption, digest_message, weekend_day_label, weekend_label, when_phrase
from apps.worker.tasks.tg_send import PACE, classify, retry_after
from core.config.settings import get_settings
from core.db.repositories.digest import (
    friends_saved,
    mark_digest_sent,
    new_at_followed_venues,
    opted_in_users,
    rank_weekend,
    weekend_pool,
    weekend_window,
)
from core.db.session import WorkerAsyncSessionLocal
from core.infra.http_safety import is_public_http_url
from core.infra.redis import get_redis

log = logging.getLogger(__name__)
_BOT_USERNAME = "okrestmap_bot"
# Full-screen message effect on arrival (free, DM-only) — a small delight when the weekend roundup lands.
_DIGEST_EFFECT = "5104841245755180586"


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


async def _send_digest_one(client, base, user_id, poster, caption_html, text_html, markup) -> str:
    """Send one digest (poster photo with a text fallback), with a single 429/5xx wait+retry.
    Returns 'ok' | 'permanent' (stamp, no retry) | 'retry' (transient → do NOT stamp)."""
    for attempt in range(2):
        try:
            if poster:
                resp = await client.post(
                    f"{base}/sendPhoto",
                    data={"chat_id": str(user_id), "caption": caption_html, "parse_mode": "HTML",
                          "reply_markup": json.dumps(markup), "message_effect_id": _DIGEST_EFFECT},
                    files={"photo": ("digest.jpg", poster, "image/jpeg")},
                )
                data = resp.json()
                if classify(data) == "permanent":  # poster rejected → the text roundup still lands
                    resp = await client.post(
                        f"{base}/sendMessage",
                        json={"chat_id": user_id, "parse_mode": "HTML", "reply_markup": markup, "text": text_html,
                              "disable_web_page_preview": True, "message_effect_id": _DIGEST_EFFECT},
                    )
                    data = resp.json()
            else:
                resp = await client.post(
                    f"{base}/sendMessage",
                    json={"chat_id": user_id, "parse_mode": "HTML", "reply_markup": markup,
                          "text": text_html, "disable_web_page_preview": True},
                )
                data = resp.json()
        except Exception:
            return "retry"  # transient network/infra
        verdict = classify(data)
        if verdict != "retry":
            return verdict
        if attempt == 0:
            await asyncio.sleep(retry_after(data))  # flood-wait → wait once, then retry
    return "retry"


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
        covers: dict[str, bytes | None] = {}  # url -> bytes; weekend covers repeat across users
        async with httpx.AsyncClient(timeout=15) as client:

            async def cover(url: str | None) -> bytes | None:
                """Cover bytes for a poster tile — SSRF-guarded, no redirects, cached per sweep."""
                if not url or not is_public_http_url(url):
                    return None
                if url not in covers:
                    try:
                        r = await client.get(url, timeout=8, follow_redirects=False,
                                             headers={"User-Agent": "okrest-card/1.0"})
                        r.raise_for_status()
                        covers[url] = r.content
                    except Exception:
                        covers[url] = None
                return covers[url]

            for u in users:
                city = u.get("city_slug")
                if city not in pools:
                    pools[city] = await weekend_pool(db, city, now)
                venue_items = await new_at_followed_venues(db, u["user_id"], now)
                # «Что сохранили друзья» — always on now (the «О друзьях» opt-out was removed), deduped
                # against the followed-venue block. Sits between «новое на площадках» and «на выходных».
                seen = {e["event_id"] for e in venue_items}
                friend_items = await friends_saved(db, u["user_id"], now)
                friend_items = [it for it in friend_items if it["event_id"] not in seen]
                seen |= {it["event_id"] for it in friend_items}
                weekend_items = rank_weekend(
                    pools[city],
                    u.get("interests") or [],
                    list(seen),  # don't repeat venue OR friend items in the weekend block
                    view_counts,
                )
                if not venue_items and not friend_items and not weekend_items:
                    continue  # nothing fresh for this user this week — stay quiet
                # Build the poster: followed-venue → friends → weekend; covers fetched (cached), a
                # when-phrase per tile. Render off the event loop (PIL is CPU-bound).
                poster_items = [
                    {**it, "when": when_phrase(it.get("date_start"), it.get("date_end"), now),
                     "day": weekend_day_label(it.get("date_start"), it.get("date_end")),
                     "photo": await cover(it.get("image"))}
                    for it in (venue_items + friend_items + weekend_items)[:6]
                ]
                poster: bytes | None = None
                try:
                    poster = await asyncio.to_thread(render_digest_poster, poster_items, label)
                except Exception:
                    poster = None
                # Poster as a photo + a light caption (tappable titles); the poster already carries
                # code · when · venue, so the caption stays short. Text roundup is the fallback.
                result = await _send_digest_one(
                    client, base, u["user_id"], poster,
                    digest_caption(venue_items, friend_items, weekend_items, label),
                    digest_message(venue_items, friend_items, weekend_items, label, now),
                    markup,
                )
                if result == "retry":
                    continue  # 429 / transient → leave unstamped; the next run retries it
                # Delivered OR permanently undeliverable → stamp NOW and commit, so a flow retry or a
                # mid-sweep crash can't re-send this week's roundup to anyone already done.
                await mark_digest_sent(db, [u["user_id"]])
                await db.commit()
                if result == "ok":
                    sent += 1
                await asyncio.sleep(PACE)  # stay under Telegram's flood threshold
    if sent:
        log.info("sent %s digests", sent)
    return sent
