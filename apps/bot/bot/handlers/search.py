from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

from apps.bot.bot.services.api_client import ApiClient

router = Router()


@router.message(Command("search"))
async def search_handler(message: Message):
    query = (message.text or "").replace("/search", "", 1).strip()
    if not query:
        await message.answer("Usage: /search <query>")
        return

    client = ApiClient("http://api:8000")
    try:
        items = await client.search(query, limit=5)
    except Exception:
        await message.answer("Search is temporarily unavailable")
        return

    if not items:
        await message.answer("No events found")
        return

    lines = [f"- {item['title']} (score={item['score']:.2f})" for item in items]
    await message.answer("\n".join(lines))
