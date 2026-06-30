import json
import re

from aiogram import F, Router
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.types import CallbackQuery, Message
from sqlalchemy import text

from core.render.formatting import ce
from apps.bot.keyboards.main import city_picker_keyboard, webapp_keyboard
from core.config.settings import get_settings
from core.db.repositories.users import update_settings, upsert_user_async
from core.db.session import AsyncSessionLocal
from core.domain.cities import active_cities
from core.infra.redis import get_redis

router = Router()

WELCOME = (
    f"{ce('📍')} <b>Окрест</b> — карта культурных событий вокруг тебя.\n\n"
    "Концерты, выставки, спектакли, фестивали, стендап и лекции — всё, что "
    "происходит рядом, на одной карте. Открывай, смотри, что вокруг, и иди.\n\n"
    f"{ce('➡️')} Жми <b>«Открыть карту»</b> — где ты, спросим уже в самой карте, "
    "чтобы показать события поблизости."
)
# Для нового бот-юзера без города: сначала спрашиваем город — иначе карта/дайджест/выдача мисс-таргетятся
# на Москву (дефолт) для жителей 14 из 16 городов. Город захватываем ДО открытия карты.
WELCOME_CITY = (
    f"{ce('📍')} <b>Окрест</b> — карта культурных событий твоего города.\n\n"
    "Концерты, выставки, спектакли, фестивали, стендап и лекции на одной карте.\n\n"
    f"{ce('➡️')} В каком ты городе?"
)
_CITY_NAMES = {c.slug: c.name for c in active_cities()}

HELP = (
    "<b>Как устроен Окрест</b>\n\n"
    f"{ce('📍')} <b>Открыть карту</b> — все события города пинами на карте. Разреши "
    "геолокацию прямо в карте — покажем, что происходит вокруг тебя.\n"
    f"{ce('🎛')} <b>Фильтры</b> — категория, дата, цена: оставь только то, что интересно.\n"
    f"{ce('❤️')} <b>Избранное</b> — сохраняй события, чтобы не потерять.\n"
    f"{ce('🔔')} <b>Напоминание</b> — сохрани событие в избранное, и я напомню за 2 часа до начала.\n"
    f"{ce('🔔')} <b>Афиша на выходные</b> — еженедельная подборка в личку, включена по умолчанию. "
    "Выключить — команда /digest или в приложении <b>Профиль → «Афиша на выходные»</b>.\n\n"
    "События собираем из открытых источников и обновляем автоматически."
)

DIGEST_ON_MSG = (
    f"{ce('🔔')} <b>Афиша на выходные</b> включена — жди подборку раз в неделю. "
    "Выключить — снова /digest или в приложении: <b>Профиль</b>."
)
DIGEST_OFF_MSG = (
    f"{ce('🔔')} <b>Афиша на выходные</b> выключена — недельную подборку больше не пришлю. "
    "Включить обратно — снова /digest."
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


_SRC_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


async def _save_acq_source(user_id: int, raw: str) -> None:
    """First-touch источник привлечения из /start src_<x>. Ставим один раз (не перезаписываем)."""
    from sqlalchemy import text

    s = raw.strip()
    if not (s and _SRC_RE.match(s)):
        return
    s = s.lower()  # M10: lowercase — джойн аттрибуции с adstat.channels.username (всегда lowercase) точный
    async with AsyncSessionLocal() as db:
        await db.execute(text(
            "UPDATE ref.users SET acq_source=:s, acq_at=now() WHERE telegram_user_id=:uid AND acq_source IS NULL"
        ), {"s": s, "uid": user_id})
        await db.commit()


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


async def _city_slug(user_id: int) -> str | None:
    """Текущий город юзера (явный read, чтобы не дёргать detached-атрибут после commit)."""
    async with AsyncSessionLocal() as db:
        return (await db.execute(
            text("SELECT city_slug FROM ref.users WHERE telegram_user_id = :u"), {"u": user_id}
        )).scalar()


@router.message(CommandStart())
async def start_handler(message: Message, command: CommandObject) -> None:
    await _save_user(message)
    arg = (command.args or "").strip()
    if arg.startswith("src_") and message.from_user:  # рекламный deep-link → first-touch источник
        await _save_acq_source(message.from_user.id, arg[len("src_"):])
    if arg.startswith("report_"):  # «сообщить о неточности» from an event sheet
        await _handle_report(message, arg[len("report_"):])
        return
    # Нет города → сначала спрашиваем его (фикс мисс-таргета на Москву). Иначе — сразу кнопка карты.
    if message.from_user and not await _city_slug(message.from_user.id):
        await message.answer(WELCOME_CITY, reply_markup=city_picker_keyboard())
        return
    # A prominent inline «Открыть карту» button right in the welcome — the key conversion moment for a
    # new user. (The persistent menu button next to the input is easy to miss on first run.)
    await message.answer(WELCOME, reply_markup=webapp_keyboard(get_settings().telegram_webapp_url))


@router.callback_query(F.data.startswith("city:"))
async def pick_city_handler(cq: CallbackQuery) -> None:
    """Юзер выбрал город в /start-пикере → пишем city_slug и зовём в карту (уже правильного города)."""
    slug = (cq.data or "").split(":", 1)[1]
    name = _CITY_NAMES.get(slug)
    if not name or not cq.from_user:
        await cq.answer()
        return
    async with AsyncSessionLocal() as db:
        await upsert_user_async(db, cq.from_user.id, username=cq.from_user.username, first_name=cq.from_user.first_name)
        await update_settings(db, cq.from_user.id, city=slug)
        await db.commit()
    kb = webapp_keyboard(get_settings().telegram_webapp_url)
    done = f"{ce('📍')} <b>{name}</b> — отлично! Открывай карту: события рядом уже ждут."
    if cq.message is not None:
        try:
            await cq.message.edit_text(done, reply_markup=kb)
        except Exception:
            await cq.message.answer(done, reply_markup=kb)
    await cq.answer(f"Город: {name}")


@router.message(Command("help"))
async def help_handler(message: Message) -> None:
    await _save_user(message)
    url = get_settings().telegram_webapp_url
    await message.answer(HELP, reply_markup=webapp_keyboard(url))


@router.message(Command("digest"))
async def digest_handler(message: Message) -> None:
    """Toggle the weekly digest — it's ON by default now, so the bot is an opt-out path too."""
    user = message.from_user
    if not user:
        return
    async with AsyncSessionLocal() as db:
        u = await upsert_user_async(db, user.id, username=user.username, first_name=user.first_name)
        now_on = not bool(getattr(u, "notify_digest", True))  # flip
        await update_settings(db, user.id, notify_digest=now_on)
        await db.commit()
    await message.answer(DIGEST_ON_MSG if now_on else DIGEST_OFF_MSG)
