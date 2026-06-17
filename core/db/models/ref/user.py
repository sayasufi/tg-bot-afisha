from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, String, func, text
from sqlalchemy.orm import Mapped, mapped_column

from core.db.base import Base


class User(Base):
    __tablename__ = "users"
    __table_args__ = {"schema": "ref"}

    telegram_user_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    username: Mapped[str | None] = mapped_column(String(64), nullable=True)
    first_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    city_id: Mapped[int | None] = mapped_column(ForeignKey("ref.cities.city_id", ondelete="SET NULL"), nullable=True)
    # Account-scoped app settings — explicit columns (synced across the user's devices
    # instead of living per-device in the Mini App's localStorage).
    theme: Mapped[str | None] = mapped_column(String(8), nullable=True)  # 'light' / 'dark' / NULL
    city_slug: Mapped[str | None] = mapped_column(String(64), nullable=True)  # explicitly picked city
    onboarded: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    coach: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    swipe_seen: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    last_active_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
