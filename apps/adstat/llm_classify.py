"""LLM-классификация каналов adstat — точнее кейвордов (которые ловят «билеты ПДД» по «билет», «опер»⊂
операция и т.п.). Категорию кэшируем на adstat.channels.llm_category; recompute предпочитает её, кейворд-
_relevance остаётся дешёвым фолбэком и гейтом discovery. Тот же транспорт, что у классификатора событий:
POST {LLM_API_BASE_URL}/api/chat под общим семафором llm_slot.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

import httpx
from sqlalchemy import text

from core.config.settings import get_settings
from core.db.session import SessionLocal
from core.services.llm_limiter import llm_slot
from pipeline.llm.json_utils import parse_llm_json

log = logging.getLogger(__name__)

_CATS = {"афиша", "город", "тема", "мусор"}
# Категория → (множитель релевантности, ярлык как в _relevance). Совпадает с кейворд-шкалой.
LLM_REL = {
    "афиша": (1.0, "афиша"),
    "город": (0.85, "город/локалка"),
    "тема": (0.80, "тема?"),
    "мусор": (0.10, "не тема"),
}

_PROMPT = (
    "Ты классифицируешь Telegram-КАНАЛ для приложения-афиши (события и досуг города: концерты, театр, "
    "выставки, фестивали, куда сходить, экскурсии). Тебе дают название, @username, ОПИСАНИЕ и тексты "
    "ПОСЛЕДНИХ ПОСТОВ. Опирайся прежде всего на ПОСТЫ — они показывают, что канал реально публикует "
    "(имя бывает обманчивым). Определи категорию канала.\n"
    "Категории:\n"
    '- "афиша" — канал-АГРЕГАТОР/ЛИСТИНГ городских событий: «куда пойти/сходить», подборка РАЗНЫХ площадок и '
    "событий города, редакционный гид (Афиша Москвы, Куда СПб). Суть — ПОДБОРКА чужих событий города, "
    "а не один артист/площадка/промоутер.\n"
    '- "город" — городские новости/локальная жизнь конкретного города (новости, происшествия, «типичный '
    "<город>») без явной афиши, но с местной аудиторией.\n"
    '- "тема" — рядом с афишей, но НЕ агрегатор-листинг: канал ОТДЕЛЬНОГО артиста/группы, конкретного '
    "клуба/площадки, промоутера или организатора, который постит ТОЛЬКО СВОИ концерты/туры/вечеринки/билеты "
    "(напр. рэпер, эмо-пати-бренд, один клуб); а также туризм/путешествия, креативные пространства, "
    "лекторий, бизнес-нетворкинг.\n"
    '- "мусор" — НЕ про городские события: билеты ПДД/автошкола, рыбалка/охота, эзотерика/гороскопы/таро, '
    "крипто/ставки/заработок, поздравления/открытки, церковный календарь, манга/аниме/манхва, маникюр/красота, "
    "недвижимость/ремонт, политика, знакомства, рецепты, мемы и любое иное вне городских событий.\n"
    "Определи также город России, если канал явно об одном конкретном городе (каноническое русское имя: "
    "Москва, Санкт-Петербург, Казань, Нижний Новгород…), иначе пустая строка.\n"
    'Верни ТОЛЬКО JSON без пояснений: {"category":"афиша|город|тема|мусор","city":"<город или пусто>"}\n'
    "Примеры:\n"
    'Билеты ПДД 2026 (@biletpdd) → {"category":"мусор","city":""}\n'
    'Афиша Казань | Мероприятия (@kazani_afisha) → {"category":"афиша","city":"Казань"}\n'
    'станция сибуя | переводы манхв (@shibuyastatiion) → {"category":"мусор","city":""}\n'
    'Церковные праздники сегодня (@holyholidays) → {"category":"мусор","city":""}\n'
    'Бесплатные концерты в Москве (@free_concerts) → {"category":"афиша","city":"Москва"}\n'
    'Типичная Пермь | Новости (@perm_news) → {"category":"город","city":"Пермь"}\n'
    'Oxxxymiron — тур 2026, «вчера на концерте было огонь» (@norimyxxxo) → {"category":"тема","city":""}\n'
    'EMOLAND — свои эмо-вечеринки, билеты на свои пати (@emolandparty) → {"category":"тема","city":""}\n'
    'INSPACE — организация СВОИХ концертов, продажи броней (@inspacebitches) → {"category":"тема","city":""}'
)


def _payload(title: str | None, username: str, ctx: str = "") -> dict:
    user = f"Название: {title or '—'}\nUsername: @{username}"
    if ctx:
        user += f"\n{ctx}"
    return {
        "messages": [
            {"role": "system", "content": _PROMPT},
            {"role": "user", "content": user[:1800]},
        ],
        "stream": False, "temperature": 0.0, "max_tokens": 80,
    }


async def _classify_one(client: httpx.AsyncClient, base_url: str, cid, title, username, ctx=""):
    try:
        async with llm_slot():  # один из общесервисных слотов LLM-конкурентности
            r = await client.post(f"{base_url}/api/chat", json=_payload(title, username, ctx))
            r.raise_for_status()
            data = r.json()
        parsed = parse_llm_json(data.get("response") or "{}")
        if not isinstance(parsed, dict):
            return cid, None
        cat = str(parsed.get("category", "")).strip().lower()
        cat = cat if cat in _CATS else None
        city = str(parsed.get("city", "")).strip() or None
        if city and (len(city) > 40 or city.lower() in ("нет", "none", "null", "-", "—")):
            city = None
        return cid, (cat, city)
    except Exception as e:  # noqa: BLE001
        log.debug("llm classify fail @%s: %s", username, e)
        return cid, None


async def _run(quads, base_url, timeout):
    async with httpx.AsyncClient(timeout=timeout) as client:
        res = await asyncio.gather(*[_classify_one(client, base_url, c, t, u, ctx) for c, t, u, ctx in quads])
    return {c: v for c, v in res if v is not None}


def classify_channels_llm(limit: int = 400, restale_days: int = 45) -> dict:
    """Классифицировать каналы LLM-ом и записать llm_category/llm_city. Приоритет — кандидаты к закупке
    (есть цена / прошли кейворд-гейт / ≥3k подписчиков), у кого нет свежей LLM-метки. Инкрементально."""
    settings = get_settings()
    with SessionLocal() as db:
        rows = db.execute(text(
            "SELECT c.channel_id, c.title, c.username FROM adstat.channels c "
            "WHERE c.username <> '' AND NOT c.llm_locked "  # ручную категорию оператора не трогаем
            "AND (c.llm_at IS NULL OR c.llm_at < now() - (:d * interval '1 day')) "
            "AND (c.relevance IS DISTINCT FROM 'не тема' OR c.ad_price > 0 OR EXISTS "
            "     (SELECT 1 FROM adstat.snapshots s WHERE s.channel_id = c.channel_id AND s.subscribers >= 3000)) "
            "ORDER BY (c.ad_price IS NOT NULL) DESC, c.score DESC NULLS LAST LIMIT :n"
        ), {"d": restale_days, "n": limit}).all()
    if not rows:
        return {"classified": 0, "scanned": 0}
    # Контекст (описание + последние посты) тянем параллельно (curl_cffi синхронный) — раскрывает суть канала.
    from concurrent.futures import ThreadPoolExecutor

    from apps.adstat.tme import fetch_channel_context
    with ThreadPoolExecutor(max_workers=12) as ex:
        ctxs = list(ex.map(lambda r: fetch_channel_context(r[2]), rows))
    quads = [(r[0], r[1], r[2], ctx) for r, ctx in zip(rows, ctxs)]
    out = asyncio.run(_run(quads, settings.llm_api_base_url, settings.llm_timeout_seconds))
    now = datetime.now(timezone.utc)
    n = 0
    with SessionLocal() as db:
        for cid, val in out.items():
            cat, city = val
            if cat:
                db.execute(text(
                    "UPDATE adstat.channels SET llm_category=:cat, llm_city=:city, llm_at=:t WHERE channel_id=:c"
                ), {"cat": cat, "city": city, "t": now, "c": cid})
                n += 1
            else:  # ответ был, но без валидной категории → метим время, чтобы не зацикливаться
                db.execute(text("UPDATE adstat.channels SET llm_at=:t WHERE channel_id=:c"), {"t": now, "c": cid})
        db.commit()
    log.info("adstat llm classify: %d/%d каналов классифицировано", n, len(rows))
    return {"classified": n, "scanned": len(rows)}
