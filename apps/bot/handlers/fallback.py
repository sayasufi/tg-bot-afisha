from html import escape

from aiogram import Router
from aiogram.types import Message
from sqlalchemy import text

from core.render.formatting import ce
from apps.bot.keyboards.main import webapp_keyboard
from core.config.settings import get_settings
from core.db.session import AsyncSessionLocal
from core.search.meili import MeiliClient

router = Router()
_BOT = "okrestmap_bot"

# Same future-session predicate for both paths; only the id/name filter differs (Meili ids vs trgm ILIKE).
_FUTURE_BY_IDS = (
    "SELECT e.event_id::text, e.canonical_title, min(o.date_start) AS soon "
    "FROM events.events e JOIN events.event_occurrences o ON o.event_id = e.event_id "
    "WHERE e.event_id::text = ANY(:ids) AND o.date_start >= now() "
    "GROUP BY e.event_id, e.canonical_title ORDER BY array_position(:ids, e.event_id::text) LIMIT :n"
)
_FUTURE_TRGM = (
    "SELECT e.event_id::text, e.canonical_title, min(o.date_start) AS soon "
    "FROM events.events e JOIN events.event_occurrences o ON o.event_id = e.event_id "
    "WHERE o.date_start >= now() AND e.canonical_title ILIKE :q "
    "GROUP BY e.event_id, e.canonical_title ORDER BY soon LIMIT :n"
)


async def _search_events(q: str, limit: int = 3):
    """События с БУДУЩЕЙ сессией по запросу. Сначала Meilisearch (typo-tolerant + свёртка диакритики:
    «концетр»→«концерт», «omanko»→«Ömankö») — сохраняем его порядок релевантности, оставляя только те, у
    кого есть будущая сессия. Если Meili выключен/пуст/сбой — фолбэк на trgm-ILIKE по canonical_title."""
    ids: list[str] = []
    if get_settings().meili_search_enabled:
        try:
            hits = await MeiliClient().search(q, limit=20)
            ids = [str(h["event_id"]) for h in hits if h.get("event_id")]
        except Exception:
            ids = []
    async with AsyncSessionLocal() as db:
        if ids:
            rows = (await db.execute(text(_FUTURE_BY_IDS), {"ids": ids, "n": limit})).all()
            if rows:
                return rows
        return (await db.execute(text(_FUTURE_TRGM), {"q": f"%{q}%", "n": limit})).all()


# Registered LAST: anything not handled by start/forwarded lands here. Instead of staying «silent»
# (the prior diagnosis), we treat free text as a SEARCH — turn intent into 1-3 tappable events; only
# if nothing matches do we point back to the map.
@router.message()
async def fallback_handler(message: Message) -> None:
    url = get_settings().telegram_webapp_url
    q = (message.text or "").strip()
    if 2 <= len(q) <= 60 and not q.startswith("/"):
        try:
            rows = await _search_events(q)
        except Exception:
            rows = []
        if rows:
            lines = [f"{ce('📍')} <b>Нашёл по запросу «{escape(q[:40])}»:</b>\n"]
            for eid, title, _ in rows:
                link = f'<a href="https://t.me/{_BOT}?startapp={eid}"><b>{escape(str(title)[:80])}</b></a>'
                lines.append(f"• {link}")
            lines.append("\nОткрой карту — там фильтры по дате, цене и места рядом.")
            await message.answer("\n".join(lines), reply_markup=webapp_keyboard(url))
            return
    await message.answer(
        f"Я показываю культурные события на карте {ce('🗺')}\n\n"
        "Жми <b>«Открыть карту»</b> — посмотри, что происходит рядом сегодня.",
        reply_markup=webapp_keyboard(url),
    )
