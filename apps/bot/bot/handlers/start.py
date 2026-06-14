from aiogram import F, Router
from aiogram.filters import Command, CommandStart
from aiogram.types import CallbackQuery, Message

from apps.bot.bot.keyboards.main import city_keyboard, main_keyboard, webapp_keyboard
from core.config.settings import get_settings
from core.db.repositories.users import get_or_create_city, upsert_user, upsert_user_city
from core.db.session import SessionLocal

router = Router()

WELCOME = (
    "📍 <b>Окрест</b> — события рядом на карте\n\n"
    "Концерты, выставки, спектакли, фестивали и стендап рядом с тобой. "
    "Открой интерактивную карту, фильтруй по категории и находи, куда сходить сегодня.\n\n"
    "👇 Нажми <b>«Открыть карту»</b> или выбери свой город."
)

HELP = (
    "<b>Что я умею</b>\n\n"
    "🗺 <b>Открыть карту</b> — события на карте города с фильтрами, метро и парками\n"
    "🔎 <code>/search запрос</code> — найти событие по названию, например <code>/search джаз</code>\n"
    "🏙 <code>/city</code> — выбрать город\n"
    "ℹ️ <code>/help</code> — это сообщение\n\n"
    "События собираются из открытых источников и обновляются автоматически."
)


def _save_user(message: Message) -> None:
    user = message.from_user
    if not user:
        return
    db = SessionLocal()
    try:
        upsert_user(db, user.id, username=user.username, first_name=user.first_name)
    finally:
        db.close()


@router.message(CommandStart())
async def start_handler(message: Message) -> None:
    _save_user(message)
    settings = get_settings()
    await message.answer(WELCOME, reply_markup=main_keyboard(settings.telegram_webapp_url))


@router.message(Command("help"))
async def help_handler(message: Message) -> None:
    _save_user(message)
    await message.answer(HELP)


@router.message(Command("city"))
async def city_handler(message: Message) -> None:
    _save_user(message)
    await message.answer("🏙 Выбери город:", reply_markup=city_keyboard())


@router.callback_query(F.data.startswith("city:"))
async def city_callback(callback: CallbackQuery) -> None:
    city_name = callback.data.split(":", 1)[1]
    user = callback.from_user
    db = SessionLocal()
    try:
        if user:
            upsert_user(db, user.id, username=user.username, first_name=user.first_name)
        city = get_or_create_city(db, city_name)
        if user:
            upsert_user_city(db, user.id, city)
    finally:
        db.close()

    settings = get_settings()
    await callback.answer(f"Город: {city_name}")
    if callback.message:
        await callback.message.answer(
            f"🏙 Город сохранён: <b>{city_name}</b>\nОткрывай карту — события уже ждут.",
            reply_markup=webapp_keyboard(settings.telegram_webapp_url),
        )
