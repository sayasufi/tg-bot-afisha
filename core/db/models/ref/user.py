from datetime import datetime

from sqlalchemy import ARRAY, BigInteger, Boolean, DateTime, String, func, text
from sqlalchemy.orm import Mapped, mapped_column

from core.db.base import Base


class User(Base):
    __tablename__ = "users"
    __table_args__ = {"schema": "ref"}

    telegram_user_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
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
    notify_digest: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    # Friends kill-switch: when true, NONE of my favourites are shown to any friend (the blunt opt-out
    # next to the per-item hidden_from_friends). Default off — the friend edge itself is the consent.
    friends_private: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    # Per-send ledger for the weekly digest — the instant we last DM'd this user a digest.
    # opted_in_users() filters on it (NULL or < this week's start) so a redeploy/manual re-run/
    # missed-run catchup in the same ISO week never double-sends; only a delivered (or permanently
    # failed) send stamps it. NULL = never sent.
    last_digest_sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # The account that first invited me (a «Пойдём?» share deep-link), set once on the first invite
    # open. WARMS a brand-new account's feed from the inviter's taste (referral cold-start cure) +
    # attribution. Plain BigInteger (no FK), like event_going.inviter_id. NULL = organic.
    invited_by: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    last_active_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
