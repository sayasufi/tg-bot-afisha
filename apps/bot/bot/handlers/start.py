import json

from aiogram import F, Router
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from apps.bot.bot.formatting import ce
from apps.bot.bot.keyboards.main import map_reply_keyboard, webapp_keyboard
from core.config.settings import get_settings
from core.db.repositories.users import update_settings, upsert_user_async
from core.db.session import AsyncSessionLocal
from core.redis import get_redis

router = Router()

WELCOME = (
    f"{ce('📍')} <b>Окрест</b> — карта культурных событий вокруг тебя.\n\n"
    "Концерты, выставки, спектакли, фестивали, стендап и лекции — всё, что "
    "происходит рядом, на одной карте. Открывай, смотри, что вокруг, и иди.\n\n"
    f"{ce('➡️')} Жми <b>«Открыть карту»</b> — где ты, спросим уже в самой карте, "
    "чтобы показать события поблизости."
)

HELP = (
    "<b>Как устроен Окрест</b>\n\n"
    f"{ce('📍')} <b>Открыть карту</b> — все события города пинами на карте. Разреши "
    "геолокацию прямо в карте — покажем, что происходит вокруг тебя.\n"
    "🎛 <b>Фильтры</b> — категория, дата, цена: оставь только то, что интересно.\n"
    "❤️ <b>Избранное</b> — сохраняй события, чтобы не потерять.\n"
    f"{ce('🔔')} <b>Напоминание</b> — жми колокол на событии, и я напишу перед началом.\n"
    f"{ce('🔔')} <b>Афиша на выходные</b> — еженедельная подборка в личку. Включить: команда "
    "/digest или в приложении <b>Профиль → «Афиша на выходные»</b>.\n\n"
    "События собираем из открытых источников и обновляем автоматически."
)

DIGEST_PROMPT = (
    f"{ce('🔔')} <b>Афиша на выходные</b> — раз в неделю пришлю подборку лучших событий на "
    "выходные и что нового там, где ты следишь. Включить?"
)
DIGEST_ON_MSG = (
    f"{ce('🔔')} <b>Афиша на выходные</b> включена — жди подборку раз в неделю. "
    "Выключить можно в приложении: <b>Профиль</b>."
)
_DIGEST_KB = InlineKeyboardMarkup(
    inline_keyboard=[[InlineKeyboardButton(text="🔔 Включить", callback_data="digest_on")]]
)


async def _save_user(message: Message):
    """Upsert the bot user on the ASYNC stack — the handler is async, so blocking sync DB I/O
    (the old SessionLocal()) would stall the event loop for every /start. Returns the User or None."""
    user = message.from_user
    if not user:
        return None
    async with AsyncSessionLocal() as db:
        u = await upsert_user_async(db, user.id, username=user.username, first_name=user.first_name)
        await db.commit()
        return u


async def _enable_digest(uid: int, username: str | None = None, first_name: str | None = None) -> None:
    async with AsyncSessionLocal() as db:
        await upsert_user_async(db, uid, username=username, first_name=first_name)  # ensure the row exists
        await update_settings(db, uid, notify_digest=True)
        await db.commit()


async def _maybe_offer_digest(message: Message, user) -> None:
    """One-tap weekly-digest opt-in, offered AT MOST ONCE per account and only if they're not already
    in. The re-engagement loop otherwise stays dark — the toggle is buried in the app's profile and
    almost nobody finds it. A Redis set remembers who's been offered so we never nag."""
    if user is None or getattr(user, "notify_digest", False):
        return
    try:
        client = get_redis(decode=True)
        if client is not None:
            # SADD returns 0 when the id is already present → already offered, stay quiet.
            if not await client.sadd("digest:offered", user.telegram_user_id):
                return
    except Exception:
        pass  # cache down → offer anyway (worst case: one extra gentle nudge later)
    await message.answer(DIGEST_PROMPT, reply_markup=_DIGEST_KB)


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
    user = await _save_user(message)
    arg = (command.args or "").strip()
    if arg.startswith("report_"):  # «сообщить о неточности» from an event sheet
        await _handle_report(message, arg[len("report_"):])
        return
    url = get_settings().telegram_webapp_url
    await message.answer(WELCOME, reply_markup=_map_markup(url))
    await _maybe_offer_digest(message, user)


@router.message(Command("help"))
async def help_handler(message: Message) -> None:
    await _save_user(message)
    url = get_settings().telegram_webapp_url
    await message.answer(HELP, reply_markup=webapp_keyboard(url))


@router.message(Command("digest"))
async def digest_handler(message: Message) -> None:
    user = message.from_user
    if user:
        await _enable_digest(user.id, username=user.username, first_name=user.first_name)
    await message.answer(DIGEST_ON_MSG)


@router.callback_query(F.data == "digest_on")
async def digest_on_callback(cb: CallbackQuery) -> None:
    if cb.from_user:
        await _enable_digest(cb.from_user.id, username=cb.from_user.username, first_name=cb.from_user.first_name)
    await cb.answer("Включено ✓")
    try:
        await cb.message.edit_text(DIGEST_ON_MSG)  # collapse the prompt into the confirmation
    except Exception:
        pass  # message too old to edit — the toast answer already confirmed
