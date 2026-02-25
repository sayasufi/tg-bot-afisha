from aiogram import Router
from aiogram.filters import CommandStart
from aiogram.types import Message

from apps.bot.bot.keyboards.main import city_keyboard, webapp_keyboard
from core.config.settings import get_settings
from core.db.repositories.users import get_or_create_city, upsert_user_city
from core.db.session import SessionLocal

router = Router()

ALLOWED_CITIES = {"Moscow", "Saint Petersburg", "Kazan", "Yekaterinburg"}


@router.message(CommandStart())
async def start_handler(message: Message):
    await message.answer("Welcome! Choose a city.", reply_markup=city_keyboard())


@router.message(lambda msg: (msg.text or "") in ALLOWED_CITIES)
async def city_handler(message: Message):
    db = SessionLocal()
    try:
        city = get_or_create_city(db, message.text or "Moscow")
        upsert_user_city(db, message.from_user.id, city)
    finally:
        db.close()

    settings = get_settings()
    await message.answer(
        f"City set: {message.text}. Open the Mini App map.",
        reply_markup=webapp_keyboard(settings.telegram_webapp_url),
    )
