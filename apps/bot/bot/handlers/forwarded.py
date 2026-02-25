from aiogram import Router
from aiogram.types import Message

from core.db.repositories.users import save_forward_message
from core.db.session import SessionLocal

router = Router()


@router.message(lambda msg: msg.forward_from_chat is not None or msg.forward_origin is not None)
async def forwarded_handler(message: Message):
    payload = message.model_dump(mode="json")
    db = SessionLocal()
    try:
        save_forward_message(db, message.message_id, message.chat.id, payload)
    finally:
        db.close()
    await message.answer("Announcement accepted to ingestion inbox")
