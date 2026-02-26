from sqlalchemy import Boolean, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from core.db.base import Base
from core.db.models.mixins import TimestampMixin


class TelegramChannel(Base, TimestampMixin):
    __tablename__ = "telegram_channels"
    __table_args__ = {"schema": "ref"}

    channel_id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    city_id: Mapped[int] = mapped_column(ForeignKey("ref.cities.city_id", ondelete="RESTRICT"), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    city = relationship("City")
