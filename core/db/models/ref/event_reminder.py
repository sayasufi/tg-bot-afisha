import uuid
from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from core.db.base import Base


class EventReminder(Base):
    """A user asked to be reminded before a saved event starts. The reminder sweep
    (Prefect) DMs them via the bot at fire_at and stamps sent_at (idempotent — a row fires
    once). FK CASCADE on both sides: if the user or the event goes away, so does the row."""

    __tablename__ = "event_reminders"
    __table_args__ = {"schema": "ref"}

    telegram_user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("ref.users.telegram_user_id", ondelete="CASCADE"), primary_key=True
    )
    event_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("events.events.event_id", ondelete="CASCADE"), primary_key=True
    )
    fire_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
