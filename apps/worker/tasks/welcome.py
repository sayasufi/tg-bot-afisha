"""Welcome / D1 nudge — первый возвратный триггер для тех, кто ОТКРЫЛ апп, но ничего не сохранил.

Без него такой юзер молчит до пятничного дайджеста (а напоминания требуют сохранения, которого у него нет) —
самое хрупкое окно платного трафика. Через ~1 день после ПЕРВОГО открытия (last_app_open_at) шлём один
персональный DM с ПОСТЕРОМ событий рядом (как дайджест) + кнопку в апп. Идемпотентно (welcome_nudge_at),
гейт по городу/без-избранного/opt-in дайджеста. Бренд-вид: кастом-эмодзи (ce) + постер-фото.
"""
import asyncio
import logging
from datetime import datetime, timezone
from html import escape as _esc

import httpx
from sqlalchemy import text

from apps.worker.tasks.digest import _send_digest_one
from apps.worker.tasks.tg_send import PACE
from core.config.settings import get_settings
from core.db.repositories.digest import rank_weekend, weekend_pool, weekend_window
from core.db.session import WorkerAsyncSessionLocal
from core.infra.http_safety import is_public_http_url
from core.render.card import render_digest_poster
from core.render.formatting import ce, weekend_day_label, weekend_label, when_phrase

log = logging.getLogger(__name__)
_BOT = "okrestmap_bot"


async def _due(db):
    """Юзеры в окне D1: открыли апп 20–60ч назад, ещё не нуджены, есть город, дайджест не выключен,
    ничего не сохранили (не вошли в петлю избранного)."""
    return (await db.execute(text(
        "SELECT u.telegram_user_id, u.city_slug, u.interests FROM ref.users u "
        "WHERE u.welcome_nudge_at IS NULL "
        "  AND u.city_slug IS NOT NULL AND u.city_slug <> '' "
        "  AND u.last_app_open_at IS NOT NULL "
        "  AND u.last_app_open_at < now() - interval '20 hours' "
        "  AND u.last_app_open_at > now() - interval '60 hours' "
        "  AND COALESCE(u.notify_digest, true) "
        "  AND NOT EXISTS (SELECT 1 FROM ref.user_favorites f WHERE f.telegram_user_id = u.telegram_user_id) "
        "ORDER BY u.last_app_open_at LIMIT 200"
    ))).all()


def _caption() -> str:
    """Короткая бренд-подпись под постером (детали несёт сам постер). Кастом-эмодзи через ce()."""
    return (
        f"{ce('📍')} <b>Окрест</b> — вот что рядом на этой неделе.\n\n"
        f"{ce('❤️')} Сохраняй сердечком — напомню за 2 часа до начала."
    )


def _text_fallback(items, now) -> str:
    """Текстовый вариант, если постер не отрисовался / фото отклонено."""
    lines = [f"• <b>{_esc(str(it.get('title') or 'Событие'))}</b> — "
             f"{when_phrase(it.get('date_start'), it.get('date_end'), now)}" for it in items]
    return (
        f"{ce('📍')} <b>Окрест</b> — вот что рядом на этой неделе:\n\n"
        + "\n".join(lines)
        + f"\n\n{ce('❤️')} Сохраняй сердечком — напомню за 2 часа до начала."
    )


async def _build_and_send(client, base, db, user_id, city, interests, pools, covers, now, label) -> str:
    if city not in pools:
        pools[city] = await weekend_pool(db, city, now)
    items = rank_weekend(pools[city], list(interests or []), [], {})[:4]
    if not items:
        return "empty"

    async def cover(url):
        if not url or not is_public_http_url(url):
            return None
        if url not in covers:
            try:
                r = await client.get(url, timeout=8, follow_redirects=False, headers={"User-Agent": "okrest-card/1.0"})
                r.raise_for_status()
                covers[url] = r.content
            except Exception:
                covers[url] = None
        return covers[url]

    poster_items = [
        {**it, "when": when_phrase(it.get("date_start"), it.get("date_end"), now),
         "day": weekend_day_label(it.get("date_start"), it.get("date_end")),
         "photo": await cover(it.get("image"))}
        for it in items
    ]
    try:
        poster = await asyncio.to_thread(render_digest_poster, poster_items, label)
    except Exception:
        poster = None
    first = items[0].get("event_id")
    url = f"https://t.me/{_BOT}?startapp={first}" if first else f"https://t.me/{_BOT}?startapp=weekend"
    markup = {"inline_keyboard": [[{"text": "Открыть афишу →", "url": url}]]}
    return await _send_digest_one(client, base, user_id, poster, _caption(), _text_fallback(items, now), markup)


async def _stamp(db, user_id) -> None:
    await db.execute(text("UPDATE ref.users SET welcome_nudge_at = now() WHERE telegram_user_id = :u"), {"u": user_id})
    await db.commit()


async def _send_welcome_nudges_impl() -> int:
    token = get_settings().telegram_bot_token
    if not token:
        return 0
    base = f"https://api.telegram.org/bot{token}"
    now = datetime.now(timezone.utc)
    sat, sun, _, _ = weekend_window(now)
    label = weekend_label(sat, sun)
    sent = 0
    async with WorkerAsyncSessionLocal() as db:
        due = await _due(db)
        if not due:
            return 0
        pools: dict[str, list] = {}
        covers: dict[str, bytes | None] = {}
        async with httpx.AsyncClient(timeout=15) as client:
            for user_id, city, interests in due:
                result = await _build_and_send(client, base, db, user_id, city, interests, pools, covers, now, label)
                if result == "empty":
                    await _stamp(db, user_id)  # нет событий в городе — штампуем, чтобы не зацикливаться
                    continue
                if result == "retry":
                    continue  # transient → не штампуем, следующий проход повторит
                await _stamp(db, user_id)  # доставлено ИЛИ перманентно-недоставимо → ровно один раз
                if result == "ok":
                    sent += 1
                await asyncio.sleep(PACE)
    if sent:
        log.info("sent %s welcome nudges", sent)
    return sent


async def send_welcome_nudge_test(only_user_id: int) -> int:
    """ТЕСТ: welcome-нудж ОДНОМУ юзеру (хард-таргет), не трогая welcome_nudge_at. Для проверки на @throlib."""
    token = get_settings().telegram_bot_token
    if not token or not only_user_id:
        return 0
    base = f"https://api.telegram.org/bot{token}"
    now = datetime.now(timezone.utc)
    sat, sun, _, _ = weekend_window(now)
    label = weekend_label(sat, sun)
    async with WorkerAsyncSessionLocal() as db:
        row = (await db.execute(text(
            "SELECT city_slug, interests FROM ref.users WHERE telegram_user_id = :u"), {"u": only_user_id})).first()
        city = (row[0] if row else None) or "moscow"
        interests = list((row[1] if row else None) or [])
        async with httpx.AsyncClient(timeout=15) as client:
            result = await _build_and_send(client, base, db, int(only_user_id), city, interests, {}, {}, now, label)
    return 1 if result == "ok" else 0
