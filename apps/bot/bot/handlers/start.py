from aiogram import Router
from aiogram.filters import Command, CommandStart
from aiogram.types import Message

from apps.bot.bot.keyboards.main import map_reply_keyboard, webapp_keyboard
from core.config.settings import get_settings
from core.db.repositories.users import upsert_user
from core.db.session import SessionLocal

router = Router()

WELCOME = (
    "📍 <b>Окрест</b> — карта культурных событий вокруг тебя.\n\n"
    "Концерты, выставки, спектакли, фестивали, стендап и лекции — всё, что "
    "происходит рядом, на одной карте. Открывай, смотри, что вокруг, и иди.\n\n"
    "👇 Жми <b>«Открыть карту»</b> — где ты, спросим уже в самой карте, "
    "чтобы показать события поблизости."
)

HELP = (
    "<b>Как устроен Окрест</b>\n\n"
    "🗺 <b>Открыть карту</b> — все события города пинами на карте. Разреши "
    "геолокацию прямо в карте — покажем, что происходит вокруг тебя.\n"
    "🎛 <b>Фильтры</b> — категория, дата, цена: оставь только то, что интересно.\n"
    "❤️ <b>Избранное</b> — сохраняй события, чтобы не потерять.\n"
    "🔎 <code>/search запрос</code> — быстрый поиск по названию, "
    "например <code>/search джаз</code>.\n\n"
    "События собираем из открытых источников и обновляем автоматически."
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


def _map_markup(url: str):
    # Persistent bottom button on prod (HTTPS); inline fallback on local http.
    return map_reply_keyboard(url) or webapp_keyboard(url)


@router.message(CommandStart())
async def start_handler(message: Message) -> None:
    _save_user(message)
    url = get_settings().telegram_webapp_url
    await message.answer(WELCOME, reply_markup=_map_markup(url))


@router.message(Command("help"))
async def help_handler(message: Message) -> None:
    _save_user(message)
    url = get_settings().telegram_webapp_url
    await message.answer(HELP, reply_markup=webapp_keyboard(url))
