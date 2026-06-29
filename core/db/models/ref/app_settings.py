from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from core.db.base import Base


class AppSetting(Base):
    """Live override поверх env-конфига (key→JSONB). Читается через get_effective() с Redis-кэшем,
    чтобы тогл/порог подействовал без рестарта во всех процессах (api/bot/worker)."""

    __tablename__ = "app_settings"
    __table_args__ = {"schema": "ref"}

    key: Mapped[str] = mapped_column(Text, primary_key=True)
    value: Mapped[dict] = mapped_column(JSONB, nullable=False)
    updated_by: Mapped[int | None] = mapped_column(BigInteger, nullable=True)  # telegram_user_id
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
