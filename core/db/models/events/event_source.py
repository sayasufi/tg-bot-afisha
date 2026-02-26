from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from core.db.base import Base


class EventSource(Base):
    __tablename__ = "event_sources"
    __table_args__ = (UniqueConstraint("raw_id", name="uq_event_sources_raw_id"), {"schema": "events"})

    id: Mapped[int] = mapped_column(primary_key=True)
    event_id: Mapped[str] = mapped_column(ForeignKey("events.events.event_id", ondelete="CASCADE"), nullable=False)
    source_id: Mapped[int] = mapped_column(ForeignKey("ref.sources.source_id", ondelete="CASCADE"), nullable=False)
    raw_id: Mapped[int] = mapped_column(ForeignKey("events.raw_events.raw_id", ondelete="CASCADE"), nullable=False)
    source_event_url: Mapped[str] = mapped_column(Text, default="", nullable=False)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    event = relationship("Event", back_populates="sources")
