from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Numeric, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from core.db.base import Base


class EventOccurrence(Base):
    __tablename__ = "event_occurrences"
    __table_args__ = (
        Index("ix_occurrences_date_start", "date_start"),
        Index("ix_occurrences_event", "event_id"),
    )

    occurrence_id: Mapped[int] = mapped_column(primary_key=True)
    event_id: Mapped[str] = mapped_column(ForeignKey("events.event_id", ondelete="CASCADE"), nullable=False)
    venue_id: Mapped[int | None] = mapped_column(ForeignKey("venues.venue_id", ondelete="SET NULL"), nullable=True)
    date_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    date_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    price_min: Mapped[float | None] = mapped_column(Numeric(12, 2), nullable=True)
    price_max: Mapped[float | None] = mapped_column(Numeric(12, 2), nullable=True)
    currency: Mapped[str] = mapped_column(String(8), default="RUB", nullable=False)
    source_best_url: Mapped[str] = mapped_column(Text, default="", nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    event = relationship("Event", back_populates="occurrences")
    venue = relationship("Venue", back_populates="occurrences")
