"""Welcome / D1 nudge — первый возвратный триггер для тех, кто ОТКРЫЛ апп, но ничего не сохранил.

Без него такой юзер молчит до пятничного дайджеста (а напоминания требуют сохранения, которого у него нет) —
самое хрупкое окно платного трафика. Через ~1 день после ПЕРВОГО открытия (last_app_open_at) шлём один
персональный DM «события рядом на этой неделе» по его городу + кнопку в апп. Идемпотентно (welcome_nudge_at),
гейт по городу/без-избранного/opt-in дайджеста.
"""
import asyncio
import logging
from datetime import datetime, timezone
from html import escape as _esc

import httpx
from sqlalchemy import text

from apps.worker.tasks.tg_send import PACE, classify, retry_after
from core.config.settings import get_settings
from core.db.repositories.digest import rank_weekend, weekend_pool
from core.db.session import WorkerAsyncSessionLocal
from core.render.formatting import when_phrase

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


def _message(items, now) -> str:
    lines = [f"• <b>{_esc(str(it.get('title') or 'Событие'))}</b> — {when_phrase(it.get('date_start'), it.get('date_end'), now)}"
             for it in items]
    return (
        "📍 <b>Окрест</b> — вот что рядом на этой неделе:\n\n"
        + "\n".join(lines)
        + "\n\nОткрой карту — там ещё больше вокруг тебя. Сохраняй сердечком — напомню за 2 часа до начала."
    )


async def _send_one(client, base, user_id, text_html, markup) -> str:
    payload = {"chat_id": user_id, "text": text_html, "parse_mode": "HTML",
               "reply_markup": markup, "disable_web_page_preview": True}
    for attempt in range(2):
        try:
            resp = await client.post(f"{base}/sendMessage", json=payload)
            data = resp.json()
        except Exception:
            return "retry"
        verdict = classify(data)
        if verdict != "retry":
            return verdict
        if attempt == 0:
            await asyncio.sleep(retry_after(data))
    return "retry"


async def _stamp(db, user_id) -> None:
    await db.execute(text("UPDATE ref.users SET welcome_nudge_at = now() WHERE telegram_user_id = :u"), {"u": user_id})
    await db.commit()


async def _send_welcome_nudges_impl() -> int:
    token = get_settings().telegram_bot_token
    if not token:
        return 0
    base = f"https://api.telegram.org/bot{token}"
    now = datetime.now(timezone.utc)
    sent = 0
    async with WorkerAsyncSessionLocal() as db:
        due = await _due(db)
        if not due:
            return 0
        pools: dict[str, list] = {}
        async with httpx.AsyncClient(timeout=20) as client:
            for user_id, city, interests in due:
                if city not in pools:
                    pools[city] = await weekend_pool(db, city, now)
                items = rank_weekend(pools[city], list(interests or []), [], {})[:3]
                if not items:
                    await _stamp(db, user_id)  # нет событий в городе — штампуем, чтобы не зацикливаться, без пустого DM
                    continue
                first = items[0].get("event_id")
                url = f"https://t.me/{_BOT}?startapp={first}" if first else f"https://t.me/{_BOT}?startapp=weekend"
                markup = {"inline_keyboard": [[{"text": "Открыть афишу →", "url": url}]]}
                result = await _send_one(client, base, user_id, _message(items, now), markup)
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
    async with WorkerAsyncSessionLocal() as db:
        row = (await db.execute(text(
            "SELECT city_slug, interests FROM ref.users WHERE telegram_user_id = :u"), {"u": only_user_id})).first()
        city = (row[0] if row else None) or "moscow"
        interests = list((row[1] if row else None) or [])
        items = rank_weekend(await weekend_pool(db, city, now), interests, [], {})[:3]
    if not items:
        return 0
    first = items[0].get("event_id")
    url = f"https://t.me/{_BOT}?startapp={first}" if first else f"https://t.me/{_BOT}?startapp=weekend"
    markup = {"inline_keyboard": [[{"text": "Открыть афишу →", "url": url}]]}
    async with httpx.AsyncClient(timeout=20) as client:
        result = await _send_one(client, base, int(only_user_id), _message(items, now), markup)
    return 1 if result == "ok" else 0
