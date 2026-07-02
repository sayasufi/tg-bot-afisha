"""Веб-аккаунты: регистрация/логин по email и СЛИЯНИЕ веб-аккаунта в Telegram-аккаунт.

Слияние — сердце связки: чистый веб-юзер живёт на синтетическом id (≥10^15); когда он привязывает
Telegram, всё нажитое (избранное/напоминания/подписки на площадки/друзья/мьюты/заявки + email и
пароль) переезжает НА НАСТОЯЩИЙ telegram_user_id, и логин по email с этого момента ведёт в
TG-аккаунт. Копируем под tg-id (ON CONFLICT DO NOTHING — у TG-строки данные приоритетнее),
затем удаляем веб-строку — FK ON DELETE CASCADE подчищает оригиналы. Всё в одной транзакции.
"""
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


async def create_web_user(db: AsyncSession, email: str, password_hash: str) -> int | None:
    """Новый чисто-веб аккаунт на синтетическом id. None — email уже занят (без утечки, какой именно
    строкой). Гонку двух одновременных регистраций ловит уникальный индекс lower(email)."""
    taken = (await db.execute(
        text("SELECT 1 FROM ref.users WHERE lower(email) = lower(:e) LIMIT 1"), {"e": email}
    )).scalar()
    if taken:
        return None
    return (await db.execute(text(
        "INSERT INTO ref.users (telegram_user_id, email, password_hash, notify_digest) "
        "VALUES (nextval('ref.web_user_id_seq'), :e, :ph, false) "  # веб-юзеру некуда слать DM → дайджест off до связки
        "RETURNING telegram_user_id"
    ), {"e": email, "ph": password_hash})).scalar()


async def find_by_email(db: AsyncSession, email: str):
    return (await db.execute(text(
        "SELECT telegram_user_id, password_hash FROM ref.users WHERE lower(email) = lower(:e)"
    ), {"e": email})).first()


async def set_credentials(db: AsyncSession, uid: int, email: str, password_hash: str) -> bool:
    """Email+пароль на СУЩЕСТВУЮЩИЙ (обычно TG) аккаунт — «вход на сайте» из миниаппа.
    False — email занят другим аккаунтом."""
    taken = (await db.execute(text(
        "SELECT 1 FROM ref.users WHERE lower(email) = lower(:e) AND telegram_user_id <> :u LIMIT 1"
    ), {"e": email, "u": uid})).scalar()
    if taken:
        return False
    await db.execute(text(
        "UPDATE ref.users SET email = :e, password_hash = :ph WHERE telegram_user_id = :u"
    ), {"e": email, "ph": password_hash, "u": uid})
    return True


# Таблицы-спутники: (таблица, колонка юзера, остальные колонки строки) — копия под tg-id.
_MERGE_TABLES = [
    ("ref.user_favorites", "telegram_user_id", ["event_id", "hidden_from_friends", "created_at"]),
    ("ref.event_reminders", "telegram_user_id", ["event_id", "fire_at", "sent_at"]),
    ("ref.user_venue_follows", "telegram_user_id", ["venue_id", "created_at"]),
    ("ref.user_friends", "user_id", ["friend_id", "status", "src_event_id", "created_at"]),
    ("ref.user_friends", "friend_id", ["user_id", "status", "src_event_id", "created_at"]),
    ("ref.user_mutes", "user_id", ["muted_user_id", "created_at"]),
    ("ref.user_mutes", "muted_user_id", ["user_id", "created_at"]),
]


async def merge_web_into_telegram(db: AsyncSession, web_uid: int, tg_uid: int) -> bool:
    """Слить синтетический веб-аккаунт в TG-аккаунт. Возвращает False, если веб-строки нет
    (протухший/повторный код) или у TG-строки УЖЕ есть свой email (не перетираем чужой вход).
    Коммитит вызывающий."""
    web = (await db.execute(text(
        "SELECT email, password_hash, theme, city_slug, interests FROM ref.users "
        "WHERE telegram_user_id = :u"), {"u": web_uid})).first()
    if web is None or web_uid == tg_uid:
        return False
    tg = (await db.execute(text(
        "SELECT email FROM ref.users WHERE telegram_user_id = :u"), {"u": tg_uid})).first()
    if tg is None or (tg[0] or "").strip():
        return False

    for table, ucol, cols in _MERGE_TABLES:
        col_list = ", ".join(cols)
        await db.execute(text(
            f"INSERT INTO {table} ({ucol}, {col_list}) "
            f"SELECT :tg, {col_list} FROM {table} WHERE {ucol} = :web "
            f"ON CONFLICT DO NOTHING"
        ), {"tg": tg_uid, "web": web_uid})
    # Заявки на модерацию: plain-BIGINT автор, просто переписываем.
    await db.execute(text(
        "UPDATE ref.pending_submissions SET submitted_by = :tg WHERE submitted_by = :web"
    ), {"tg": tg_uid, "web": web_uid})
    # Вход по email теперь ведёт в TG-аккаунт; вкус/город переносим только в пустоту (TG приоритетнее).
    await db.execute(text(
        "UPDATE ref.users SET email = :e, password_hash = :ph, "
        "  theme = COALESCE(theme, :theme), city_slug = COALESCE(NULLIF(city_slug, ''), :city), "
        "  interests = CASE WHEN COALESCE(array_length(interests, 1), 0) = 0 THEN COALESCE(:ints, interests) ELSE interests END "
        "WHERE telegram_user_id = :tg"
    ), {"e": web[0], "ph": web[1], "theme": web[2], "city": web[3], "ints": web[4], "tg": tg_uid})
    await db.execute(text("DELETE FROM ref.users WHERE telegram_user_id = :u"), {"u": web_uid})  # каскад чистит спутники
    return True
