from html import escape

from aiogram import Router
from aiogram.types import Message
from sqlalchemy import text

from core.render.formatting import ce
from apps.bot.keyboards.main import webapp_keyboard
from core.config.settings import get_settings
from core.db.session import AsyncSessionLocal

router = Router()
_BOT = "okrestmap_bot"


async def _search_events(q: str, limit: int = 3):
    """События с БУДУЩЕЙ сессией, чьё название похоже на запрос (trgm-индекс по canonical_title), soonest-first."""
    async with AsyncSessionLocal() as db:
        return (await db.execute(text(
            "SELECT e.event_id::text, e.canonical_title, min(o.date_start) AS soon "
            "FROM events.events e JOIN events.event_occurrences o ON o.event_id = e.event_id "
            "WHERE o.date_start >= now() AND e.canonical_title ILIKE :q "
            "GROUP BY e.event_id, e.canonical_title ORDER BY soon LIMIT :n"
        ), {"q": f"%{q}%", "n": limit})).all()


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
