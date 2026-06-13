import asyncio
import logging
import sys

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from apps.bot.bot.handlers import forwarded, search, start
from core.config.settings import get_settings
from core.logging.setup import setup_logging


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

    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
