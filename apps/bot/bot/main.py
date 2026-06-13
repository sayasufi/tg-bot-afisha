import asyncio
import logging
import sys

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.types import BotCommand, MenuButtonWebApp, WebAppInfo

from apps.bot.bot.handlers import forwarded, search, start
from core.config.settings import get_settings
from core.logging.setup import setup_logging

COMMANDS = [
    BotCommand(command="start", description="Открыть карту и выбрать город"),
    BotCommand(command="search", description="Найти событие по названию"),
    BotCommand(command="city", description="Выбрать город"),
    BotCommand(command="help", description="Помощь"),
]


async def _setup_bot(bot: Bot, webapp_url: str) -> None:
    await bot.set_my_commands(COMMANDS)
    # Persistent menu button (next to the input) opens the Mini App — needs HTTPS.
    if webapp_url.startswith("https://"):
        await bot.set_chat_menu_button(menu_button=MenuButtonWebApp(text="Карта", web_app=WebAppInfo(url=webapp_url)))


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

    await _setup_bot(bot, settings.telegram_webapp_url)
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
