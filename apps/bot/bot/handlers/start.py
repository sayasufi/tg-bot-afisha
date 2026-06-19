import json

from aiogram import Router
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.types import Message

from apps.bot.bot.formatting import ce
from apps.bot.bot.keyboards.main import map_reply_keyboard, webapp_keyboard
from core.config.settings import get_settings
from core.db.repositories.users import upsert_user
from core.db.session import SessionLocal
from core.redis import get_redis

router = Router()

WELCOME = (
    f"{ce('📍')} <b>Окрест</b> — карта культурных событий вокруг тебя.\n\n"
    "Концерты, выставки, спектакли, фестивали, стендап и лекции — всё, что "
    "происходит рядом, на одной карте. Открывай, смотри, что вокруг, и иди.\n\n"
    f"{ce('➡️')} Жми <b>«Открыть карту»</b> — где ты, спросим уже в самой карте, "
    "чтобы показать события поблизости.\n\n"
    f"{ce('🔔')} Хочешь подборку на выходные раз в неделю? Включается в приложении: "
    "<b>Профиль → «Афиша на выходные»</b>."
)

HELP = (
    "<b>Как устроен Окрест</b>\n\n"
    f"{ce('📍')} <b>Открыть карту</b> — все события города пинами на карте. Разреши "
    "геолокацию прямо в карте — покажем, что происходит вокруг тебя.\n"
    "🎛 <b>Фильтры</b> — категория, дата, цена: оставь только то, что интересно.\n"
    "❤️ <b>Избранное</b> — сохраняй события, чтобы не потерять.\n"
    f"{ce('🔔')} <b>Напоминание</b> — жми колокол на событии, и я напишу перед началом.\n"
    f"{ce('🔔')} <b>Афиша на выходные</b> — еженедельная подборка в личку. Включить: "
    "в приложении <b>Профиль → «Афиша на выходные»</b>.\n\n"
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


async def _handle_report(message: Message, event_id: str) -> None:
    """A user tapped «сообщить о неточности» on an event (deep link ?start=report_<id>).
    Record the flag — event + who — so the team can check the data, and acknowledge so the
    feedback loop visibly closes. Best-effort store (a Redis list the team reads)."""
    user = message.from_user
    try:
        client = get_redis(decode=True)
        if client is not None:
            await client.lpush(
                "reports:inaccuracy",
                json.dumps({
                    "event_id": event_id[:64],
                    "user_id": user.id if user else None,
                    "username": user.username if user else None,
                }),
            )
            await client.ltrim("reports:inaccuracy", 0, 999)  # keep the last 1000
    except Exception:
        pass  # the acknowledgement matters more than the store
    await message.answer(f"{ce('🔔')} Спасибо! Отметили неточность — проверим данные по этому событию.")


@router.message(CommandStart())
async def start_handler(message: Message, command: CommandObject) -> None:
    _save_user(message)
    arg = (command.args or "").strip()
    if arg.startswith("report_"):  # «сообщить о неточности» from an event sheet
        await _handle_report(message, arg[len("report_"):])
        return
    url = get_settings().telegram_webapp_url
    await message.answer(WELCOME, reply_markup=_map_markup(url))


@router.message(Command("help"))
async def help_handler(message: Message) -> None:
    _save_user(message)
    url = get_settings().telegram_webapp_url
    await message.answer(HELP, reply_markup=webapp_keyboard(url))
