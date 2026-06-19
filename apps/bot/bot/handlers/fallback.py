from aiogram import Router
from aiogram.types import Message

from apps.bot.bot.keyboards.main import webapp_keyboard
from core.config.settings import get_settings

router = Router()


# Registered LAST: anything not handled by start/forwarded lands here, so the bot
# always points the user back to the map instead of staying silent.
@router.message()
async def fallback_handler(message: Message) -> None:
    url = get_settings().telegram_webapp_url
    await message.answer(
        "Я показываю культурные события на карте 🗺\n\n"
        "Жми <b>«Открыть карту»</b> — посмотри, что происходит рядом сегодня.",
        reply_markup=webapp_keyboard(url),
    )
