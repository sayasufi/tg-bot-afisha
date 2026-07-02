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
from core.db.repositories.digest import _city_offset, rank_weekend, weekend_pool, weekend_window
from core.db.session import WorkerAsyncSessionLocal
from core.infra.http_safety import is_public_http_url
from core.render.card import render_digest_poster
from core.render.formatting import ce, event_deeplink, glyph, weekend_day_label, weekend_label, when_phrase

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


def _compose(items, now, offset_hours: int = 3) -> str:
    """Подпись/текст: как в дайджесте — КАЖДОЕ название кликабельный deep-link на своё событие (глиф
    категории + жирная ссылка + когда). Постер несёт фото, подпись — ссылки. Кастом-эмодзи в шапке/подвале."""
    lines = [f"{ce('📍')} <b>Окрест</b> — вот что рядом на этой неделе:\n"]
    for it in items:
        title = _esc(str(it.get("title") or "Событие")[:80])
        link = f'<a href="{event_deeplink(it["event_id"])}"><b>{title}</b></a>'
        when = when_phrase(it.get("date_start"), it.get("date_end"), now, offset_hours)
        lines.append(f"{glyph(it.get('category'))} {link}" + (f" · {when}" if when else ""))
    lines.append(f"\n{ce('❤️')} Сохраняй сердечком — напомню за 2 часа до начала.")
    return "\n".join(lines)


async def _build_and_send(client, base, user_id, city, interests, pools, covers, now, label) -> str:
    # No DB session here (B9): the weekend pool for `city` is resolved by the caller into `pools` in a
    # short session, so this holds NO Postgres connection across the cover fetches / poster send below.
    off = _city_offset(city)  # render times in the user's own city tz (multi-city)
    items = rank_weekend(pools.get(city) or [], list(interests or []), [], {})[:4]
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
        {**it, "when": when_phrase(it.get("date_start"), it.get("date_end"), now, off),
         "day": weekend_day_label(it.get("date_start"), it.get("date_end"), off),
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
    msg = _compose(items, now, off)  # кликабельные названия событий (как в дайджесте)
    return await _send_digest_one(client, base, user_id, poster, msg, msg, markup)


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
    # B9: read the due set in a SHORT session and release the connection; per user, resolve the weekend
    # pool in its own short session, then do the network fan-out (covers + poster send + PACE sleep) with
    # NO connection held, then stamp in another short session. On NullPool a held session pins a scarce
    # worker connection for the whole paced loop otherwise.
    async with WorkerAsyncSessionLocal() as db:
        due = await _due(db)
    if not due:
        return 0
    pools: dict[str, list] = {}
    covers: dict[str, bytes | None] = {}
    async with httpx.AsyncClient(timeout=15) as client:
        for user_id, city, interests in due:
            if city not in pools:  # DB read phase — short session, released before the network send
                async with WorkerAsyncSessionLocal() as db:
                    pools[city] = await weekend_pool(db, city, now)
            result = await _build_and_send(client, base, user_id, city, interests, pools, covers, now, label)
            if result == "empty":
                # НЕ штампуем: пустота часто транзиентна (строгий interest-фильтр, межсезонье). Юзер
                # остаётся в очереди и выпадает сам по верхней границе окна (60ч) — вечного молчания
                # с первой попытки больше нет, и зацикливания тоже (окно конечное).
                continue
            if result == "retry":
                continue  # transient → не штампуем, следующий проход повторит
            async with WorkerAsyncSessionLocal() as db:
                await _stamp(db, user_id)  # доставлено ИЛИ перманентно-недоставимо → ровно один раз
            if result == "ok":
                sent += 1
            await asyncio.sleep(PACE)
    if sent:
        log.info("sent %s welcome nudges", sent)
    return sent


async def _due_d4(db) -> list:
    """Юзеры в окне D4-D5: открыли апп 96–120ч назад и с тех пор тихо (last_app_open_at и есть та
    самая последняя активность), НИЧЕГО не сохранили, welcome уже получали (или окно D1 пропущено),
    d4-нудж ещё не слали. Жёсткий кап касаний: welcome (D1) + этот = максимум два, дальше только
    opt-in дайджест."""
    return (await db.execute(text(
        "SELECT u.telegram_user_id, u.city_slug, u.interests FROM ref.users u "
        "WHERE u.d4_nudge_at IS NULL "
        "  AND u.city_slug IS NOT NULL AND u.city_slug <> '' "
        "  AND u.last_app_open_at IS NOT NULL "
        "  AND u.last_app_open_at < now() - interval '96 hours' "
        "  AND u.last_app_open_at > now() - interval '120 hours' "
        "  AND COALESCE(u.notify_digest, true) "
        "  AND NOT EXISTS (SELECT 1 FROM ref.user_favorites f WHERE f.telegram_user_id = u.telegram_user_id) "
        "ORDER BY u.last_app_open_at LIMIT 200"
    ))).all()


async def _stamp_d4(db, user_id) -> None:
    await db.execute(text("UPDATE ref.users SET d4_nudge_at = now() WHERE telegram_user_id = :u"), {"u": user_id})
    await db.commit()


async def _send_d4_nudges_impl() -> int:
    """D4-D5 нудж не-сохранившим — закрывает «мёртвую зону» D2-D6 (после welcome и до пятничного
    дайджеста ноль касаний). Тот же постер/письмо, что welcome (шаблон уже конвертит), другой штамп."""
    token = get_settings().telegram_bot_token
    if not token:
        return 0
    base = f"https://api.telegram.org/bot{token}"
    now = datetime.now(timezone.utc)
    sat, sun, _, _ = weekend_window(now)
    label = weekend_label(sat, sun)
    sent = 0
    async with WorkerAsyncSessionLocal() as db:
        due = await _due_d4(db)
    if not due:
        return 0
    pools: dict[str, list] = {}
    covers: dict[str, bytes | None] = {}
    async with httpx.AsyncClient(timeout=15) as client:
        for user_id, city, interests in due:
            if city not in pools:
                async with WorkerAsyncSessionLocal() as db:
                    pools[city] = await weekend_pool(db, city, now)
            result = await _build_and_send(client, base, user_id, city, interests, pools, covers, now, label)
            if result == "empty":
                continue  # транзиентная пустота — юзер выпадет из окна сам (120ч)
            if result == "retry":
                continue
            async with WorkerAsyncSessionLocal() as db:
                await _stamp_d4(db, user_id)
            if result == "ok":
                sent += 1
            await asyncio.sleep(PACE)
    if sent:
        log.info("sent %s d4 nudges", sent)
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
        pools = {city: await weekend_pool(db, city, now)}  # resolve pool while the session is open (B9)
    async with httpx.AsyncClient(timeout=15) as client:
        result = await _build_and_send(client, base, int(only_user_id), city, interests, pools, {}, now, label)
    return 1 if result == "ok" else 0
