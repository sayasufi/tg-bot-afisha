from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, func
from sqlalchemy.orm import Mapped, mapped_column

from core.db.base import Base


class UserMute(Base):
    """A muted/blocked account. Hides the muter's named social signals from the muted user and gates
    re-accepting a friend link from them. Kept separate from unfriending so a block survives across
    friend add/remove. Asymmetric by design (I mute you; you aren't told)."""

    __tablename__ = "user_mutes"
    __table_args__ = {"schema": "ref"}

    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("ref.users.telegram_user_id", ondelete="CASCADE"), primary_key=True
    )
    muted_user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("ref.users.telegram_user_id", ondelete="CASCADE"), primary_key=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
