from aiogram import Router
from aiogram.types import Message

from core.render.formatting import ce
from apps.bot.keyboards.main import webapp_keyboard
from core.config.settings import get_settings
from core.db.repositories.users import save_forward_message
from core.db.session import AsyncSessionLocal

router = Router()


@router.message(lambda msg: msg.forward_from_chat is not None or msg.forward_origin is not None)
async def forwarded_handler(message: Message):
    payload = message.model_dump(mode="json")
    async with AsyncSessionLocal() as db:
        await save_forward_message(db, message.message_id, message.chat.id, payload)
    # Пересылки складываем для ручного ревью — авто-обработки в событие пока нет, поэтому НЕ обещаем
    # «добавлю на карту» (это было бы ложно). Честно благодарим и сразу даём next-step — открыть карту.
    await message.answer(
        f"{ce('🗺')} Спасибо, анонс сохранил — посмотрю.\n\n"
        "А пока загляни на карту: там уже много событий рядом.",
        reply_markup=webapp_keyboard(get_settings().telegram_webapp_url),
    )
