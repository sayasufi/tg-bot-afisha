from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from core.db.base import Base


class AdTgAccount(Base):
    """Пул Telethon-аккаунтов для крауля (round-robin/параллельно, обход FloodWait одного аккаунта)."""

    __tablename__ = "tg_accounts"
    __table_args__ = {"schema": "adstat"}

    account_id: Mapped[int] = mapped_column(primary_key=True)
    label: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    api_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    api_hash: Mapped[str | None] = mapped_column(Text, nullable=True)
    session: Mapped[str] = mapped_column(Text, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    flood_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
