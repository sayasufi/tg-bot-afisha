from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, Integer, func
from sqlalchemy.orm import Mapped, mapped_column

from core.db.base import Base


class UserVenueFollow(Base):
    """A followed venue, kept per Telegram user so it syncs across devices. Gives the
    product a "new at this place" trigger and a personal venue list. Mirrors UserFavorite."""

    __tablename__ = "user_venue_follows"
    __table_args__ = {"schema": "ref"}

    telegram_user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("ref.users.telegram_user_id", ondelete="CASCADE"), primary_key=True
    )
    venue_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("events.venues.venue_id", ondelete="CASCADE"), primary_key=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
