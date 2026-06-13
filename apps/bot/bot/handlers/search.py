import logging

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

from apps.bot.bot.formatting import event_card
from apps.bot.bot.keyboards.main import webapp_keyboard
from apps.bot.bot.services.api_client import ApiClient
from core.config.settings import get_settings

router = Router()
logger = logging.getLogger(__name__)


@router.message(Command("search"))
async def search_handler(message: Message) -> None:
    query = (message.text or "").replace("/search", "", 1).strip()
    if not query:
        await message.answer("🔎 Напиши, что ищешь: <code>/search джаз</code>")
        return

    client = ApiClient("http://api:8000")
    try:
        items = await client.search_events(query, limit=6)
    except Exception:
        logger.exception("search failed")
        await message.answer("⚠️ Поиск временно недоступен, попробуй позже.")
        return

    if not items:
        await message.answer(f"😕 По запросу «{query}» ничего не нашлось.\nПопробуй другое слово или открой карту целиком.")
        return

    settings = get_settings()
    cards = "\n\n".join(event_card(item) for item in items)
    text = f"🔎 Нашёл по запросу «<b>{query}</b>»:\n\n{cards}"
    await message.answer(text, reply_markup=webapp_keyboard(settings.telegram_webapp_url))
