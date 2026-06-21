import uuid
from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, func, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from core.db.base import Base


class UserFavorite(Base):
    """A hearted event, kept per Telegram user so favourites sync across devices
    (they used to live only in the Mini App's localStorage → diverged per device)."""

    __tablename__ = "user_favorites"
    __table_args__ = {"schema": "ref"}

    telegram_user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("ref.users.telegram_user_id", ondelete="CASCADE"), primary_key=True
    )
    # FK to events with ON DELETE CASCADE (migration 0016): when the dedup/lifecycle
    # pipeline deletes an event, its favourites go with it — no dangling rows that would
    # inflate the count. We do NOT delete favourites for merely-past events (that erased
    # the user's history); past favourites stay and simply render as past.
    event_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("events.events.event_id", ondelete="CASCADE"), primary_key=True
    )
    # Per-item privacy: hide THIS favourite from friends (the granular complement to the global
    # users.friends_private). Lets a user keep a sensitive save off the social signal without going dark.
    hidden_from_friends: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
