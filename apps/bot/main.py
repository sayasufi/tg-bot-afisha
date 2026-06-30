import asyncio
import logging
import sys

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.types import BotCommand, MenuButtonWebApp, WebAppInfo

from apps.bot.handlers import fallback, forwarded, start
from apps.bot.middlewares.throttle import ThrottleMiddleware
from core.config.settings import get_settings
from core.logging.setup import setup_logging

COMMANDS = [
    BotCommand(command="start", description="Открыть карту"),
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
    from core.observability.sentry import init_sentry
    init_sentry("bot")  # тихие падения хендлеров/рассылок попадают в Sentry, а не только в логи

    if not settings.telegram_bot_token:
        logging.getLogger(__name__).warning("TELEGRAM_BOT_TOKEN is not set; bot is disabled")
        sys.exit(0)

    bot = Bot(token=settings.telegram_bot_token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher()
    # Outer so it runs before any handler/router filter — protects the unauthenticated
    # forward path (forwarded.py → ingestion/LLM) from a single chat flooding it.
    dp.message.outer_middleware(ThrottleMiddleware())
    dp.include_router(start.router)
    dp.include_router(forwarded.router)
    dp.include_router(fallback.router)  # catch-all — must stay last

    await _setup_bot(bot, settings.telegram_webapp_url)

    # Self-heal from transient Telegram/network faults: a bare start_polling that
    # raises would exit the process and take the bot offline until Docker restarts
    # it. Retry with capped exponential backoff instead.
    log = logging.getLogger(__name__)
    backoff = 2
    while True:
        try:
            await dp.start_polling(bot)
            break  # clean shutdown (signal) — don't loop
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("polling crashed; restarting in %ss", backoff)
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 60)


if __name__ == "__main__":
    asyncio.run(main())
