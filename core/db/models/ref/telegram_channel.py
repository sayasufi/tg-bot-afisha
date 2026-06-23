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
    # OPTIONAL venue binding: set for a venue-specific channel (a club/standup room whose posts are all
    # at one place) → used as an extraction hint + to fill venue/address when the post omits it. Leave
    # NULL for a general channel (no fixed place) — then the LLM resolves the venue from each post.
    venue_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    venue_address: Mapped[str | None] = mapped_column(String(500), nullable=True)

    city = relationship("City")
