from aiogram import F, Router
from aiogram.filters import Command, CommandStart
from aiogram.types import CallbackQuery, Message

from apps.bot.bot.keyboards.main import main_keyboard, webapp_keyboard
from core.config.settings import get_settings
from core.db.repositories.users import get_or_create_city, upsert_user_city
from core.db.session import SessionLocal

router = Router()

WELCOME = (
    "🎭 <b>Афиша</b> — события Москвы на карте\n\n"
    "Концерты, выставки, спектакли, фестивали и стендап рядом с тобой. "
    "Открой интерактивную карту, фильтруй по категории и находи, куда сходить сегодня.\n\n"
    "👇 Нажми <b>«Открыть карту»</b> или выбери свой город."
)

HELP = (
    "<b>Что я умею</b>\n\n"
    "🗺 <b>Открыть карту</b> — события на карте города с фильтрами и поиском\n"
    "🔎 <code>/search запрос</code> — найти событие по названию, например <code>/search джаз</code>\n"
    "🏙 <code>/start</code> — выбрать город и открыть карту\n\n"
    "Все события собираются из открытых источников и обновляются автоматически."
)


@router.message(CommandStart())
async def start_handler(message: Message) -> None:
    settings = get_settings()
    await message.answer(WELCOME, reply_markup=main_keyboard(settings.telegram_webapp_url))


@router.message(Command("help"))
async def help_handler(message: Message) -> None:
    await message.answer(HELP)


@router.callback_query(F.data.startswith("city:"))
async def city_callback(callback: CallbackQuery) -> None:
    city_name = callback.data.split(":", 1)[1]
    db = SessionLocal()
    try:
        city = get_or_create_city(db, city_name)
        if callback.from_user:
            upsert_user_city(db, callback.from_user.id, city)
    finally:
        db.close()

    settings = get_settings()
    await callback.answer(f"Город: {city_name}")
    if callback.message:
        await callback.message.answer(
            f"🏙 Город сохранён: <b>{city_name}</b>\nОткрывай карту — события уже ждут.",
            reply_markup=webapp_keyboard(settings.telegram_webapp_url),
        )
