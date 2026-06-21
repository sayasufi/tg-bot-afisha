import uuid
from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, String, func, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from core.db.base import Base


class UserFriend(Base):
    """A SYMMETRIC friendship edge — one row per direction (a→b AND b→a). Born when an account
    accepts a signed «Пойдём?» invite (both rows written 'accepted'); the Phase-2 friend deep-link
    writes the same pair. Symmetric storage keeps the hot «friends who favorited X» query a single
    index JOIN on user_id, and makes unfriend/block a two-row delete in one transaction.

    `src_event_id` is the event the friendship was born from — plain UUID (no FK, like
    users.invited_by), so deleting that event never drops the friendship. Attribution / k-factor only.
    """

    __tablename__ = "user_friends"
    __table_args__ = {"schema": "ref"}

    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("ref.users.telegram_user_id", ondelete="CASCADE"), primary_key=True
    )
    friend_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("ref.users.telegram_user_id", ondelete="CASCADE"), primary_key=True
    )
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default=text("'accepted'"))
    src_event_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
