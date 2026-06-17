import uuid
from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, func
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
    # No FK to events.events — a pruned event just leaves a harmless stale row (the app
    # filters favourites against currently-loaded events), and this keeps the table
    # decoupled from the events schema's lifecycle.
    event_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
