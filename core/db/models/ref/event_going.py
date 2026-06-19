import uuid
from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from core.db.base import Base


class EventGoing(Base):
    """A user said «Я иду» to an event — usually by accepting a shared invite, so inviter_id is
    the sharer who invited them. Powers the «Пойдём?» loop (the inviter gets a DM when someone
    accepts) and a future «N собираются» social-proof count. FK CASCADE on user + event."""

    __tablename__ = "event_going"
    __table_args__ = {"schema": "ref"}

    telegram_user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("ref.users.telegram_user_id", ondelete="CASCADE"), primary_key=True
    )
    event_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("events.events.event_id", ondelete="CASCADE"), primary_key=True
    )
    # The inviter who shared it (their telegram_user_id), or NULL if set without an invite.
    inviter_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
