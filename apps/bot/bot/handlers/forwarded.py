from aiogram import Router
from aiogram.types import Message

from core.db.repositories.users import save_forward_message
from core.db.session import AsyncSessionLocal

router = Router()


@router.message(lambda msg: msg.forward_from_chat is not None or msg.forward_origin is not None)
async def forwarded_handler(message: Message):
    payload = message.model_dump(mode="json")
    async with AsyncSessionLocal() as db:
        await save_forward_message(db, message.message_id, message.chat.id, payload)
    await message.answer("Принял анонс — разберу и добавлю на карту, если это событие 🗺")
