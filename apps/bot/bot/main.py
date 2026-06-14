import asyncio
import logging
import sys

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.types import BotCommand, MenuButtonWebApp, WebAppInfo

from apps.bot.bot.handlers import fallback, forwarded, search, start
from core.config.settings import get_settings
from core.logging.setup import setup_logging

COMMANDS = [
    BotCommand(command="start", description="Открыть карту"),
    BotCommand(command="search", description="Поиск события по названию"),
    BotCommand(command="help", description="Как это работает"),
]

DESCRIPTION = (
    "Окрест — карта культурных событий вокруг тебя: концерты, выставки, спектакли, "
    "фестивали, стендап. Открой карту и посмотри, что происходит рядом сегодня."
)
SHORT_DESCRIPTION = "Карта культурных событий вокруг тебя. Что рядом сегодня."


async def _setup_bot(bot: Bot, webapp_url: str) -> None:
    """Brand config lives in code so it is consistent across redeploys."""
    await bot.set_my_commands(COMMANDS)
    try:
        await bot.set_my_description(DESCRIPTION)
        await bot.set_my_short_description(SHORT_DESCRIPTION)
    except Exception:
        logging.getLogger(__name__).warning("could not set bot description", exc_info=True)
    # Persistent menu button (next to the input) opens the Mini App — needs HTTPS.
    if webapp_url.startswith("https://"):
        await bot.set_chat_menu_button(
            menu_button=MenuButtonWebApp(text="Открыть карту", web_app=WebAppInfo(url=webapp_url))
        )


async def main() -> None:
    settings = get_settings()
    setup_logging(settings.log_level)

    if not settings.telegram_bot_token:
        logging.getLogger(__name__).warning("TELEGRAM_BOT_TOKEN is not set; bot is disabled")
        sys.exit(0)

    bot = Bot(token=settings.telegram_bot_token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher()
    dp.include_router(start.router)
    dp.include_router(search.router)
    dp.include_router(forwarded.router)
    dp.include_router(fallback.router)  # catch-all — must stay last

    await _setup_bot(bot, settings.telegram_webapp_url)
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
