from datetime import datetime

from sqlalchemy import ARRAY, BigInteger, Boolean, DateTime, Integer, String, func, text
from sqlalchemy.orm import Mapped, mapped_column

from core.db.base import Base


class User(Base):
    __tablename__ = "users"
    __table_args__ = {"schema": "ref"}

    telegram_user_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    # Веб-аккаунт (email+scrypt-пароль) поверх той же строки: TG-юзер может задать их из миниаппа
    # («вход на сайте»), а чистый веб-юзер живёт на СИНТЕТИЧЕСКОМ id ≥ 10^15 (ref.web_user_id_seq)
    # до связки с Telegram (0063). NULL = входа по email нет.
    email: Mapped[str | None] = mapped_column(String(320), nullable=True)
    password_hash: Mapped[str | None] = mapped_column(String(256), nullable=True)
    username: Mapped[str | None] = mapped_column(String(64), nullable=True)
    first_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    # The account's Telegram avatar (captured from initData) — for the friend social-proof faces.
    photo_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    # Account-scoped app settings — explicit columns (synced across the user's devices
    # instead of living per-device in the Mini App's localStorage). The user's city is a
    # single source of truth: city_slug (was a dead city_id FK alongside it — dropped 0018).
    theme: Mapped[str | None] = mapped_column(String(8), nullable=True)  # 'light' / 'dark' / NULL
    city_slug: Mapped[str | None] = mapped_column(String(64), nullable=True)  # home/picked city
    onboarded: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    coach: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    swipe_seen: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    # Categories the user picked at first-run onboarding — warms "Для тебя" from cold so a
    # brand-new account gets a real personalised feed instead of popularity mislabelled.
    interests: Mapped[list[str]] = mapped_column(ARRAY(String), nullable=False, server_default=text("'{}'"))
    # True once the account has merged a device's local favourites (the one-time
    # localStorage migration). After that, a stale never-synced device's `add` list is
    # ignored, so it can't resurrect favourites removed on another device.
    favorites_merged: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    # Notification opt-in. Reminders default ON (the per-event "Напомнить" tap is the
    # consent; this is a global mute). The weekly digest is strictly opt-in (default off).
    notify_reminders: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    notify_digest: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    # Opt-out для кастомных рассылок (≠ дайджест). DEFAULT true; resolver рассылок уважает его (см. broadcasts.py).
    notify_broadcasts: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    # Friend notifications (the «X добавил тебя» DM + the digest's friends section) and @username search are
    # now ALWAYS ON — their opt-in columns (notify_friends / is_searchable) were dropped in migration 0031.
    # Friends kill-switch: when true, NONE of my favourites are shown to any friend (the blunt opt-out
    # next to the per-item hidden_from_friends). Default off — the friend edge itself is the consent.
    friends_private: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    # Per-account version mixed into the «add me» friend-link HMAC. The first successful add via a link
    # bumps it, which invalidates that link (and any copies) — making the friend-link SINGLE-USE: no
    # broadcast, no manual reset. Doesn't touch anyone else's link or any event-invite sig. 0 = the legacy
    # payload, so links minted before versioning existed stay valid until first used.
    friend_link_ver: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    # Per-send ledger for the weekly digest — the instant we last DM'd this user a digest.
    # opted_in_users() filters on it (NULL or < this week's start) so a redeploy/manual re-run/
    # missed-run catchup in the same ISO week never double-sends; only a delivered (or permanently
    # failed) send stamps it. NULL = never sent.
    last_digest_sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # The account that first invited me (a «Пойдём?» share deep-link), set once on the first invite
    # open. WARMS a brand-new account's feed from the inviter's taste (referral cold-start cure) +
    # attribution. Plain BigInteger (no FK), like event_going.inviter_id. NULL = organic.
    invited_by: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    # Per-account version mixed into the admin-session HMAC (admin.okrestmap.ru). Bump = revoke all of the
    # owner's admin sessions instantly ("log out everywhere"), same trick as friend_link_ver. 0 = none issued.
    admin_session_ver: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    last_active_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    # Источник привлечения (first-touch): что после `src_` в deep-link (обычно username рекл. канала).
    acq_source: Mapped[str | None] = mapped_column(String(64), nullable=True)
    acq_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
