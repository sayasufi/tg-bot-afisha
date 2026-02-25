from datetime import datetime

from sqlalchemy import JSON, DateTime, ForeignKey, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from core.db.base import Base


class EventCandidate(Base):
    __tablename__ = "event_candidates"

    candidate_id: Mapped[int] = mapped_column(primary_key=True)
    raw_id: Mapped[int] = mapped_column(ForeignKey("raw_events.raw_id", ondelete="CASCADE"), nullable=False)

    title: Mapped[str] = mapped_column(String(500), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="", nullable=False)
    date_start: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    date_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    venue: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    address: Mapped[str] = mapped_column(String(500), default="", nullable=False)
    price_min: Mapped[float | None] = mapped_column(Numeric(12, 2), nullable=True)
    price_max: Mapped[float | None] = mapped_column(Numeric(12, 2), nullable=True)
    currency: Mapped[str] = mapped_column(String(8), default="RUB", nullable=False)
    age_limit: Mapped[str] = mapped_column(String(32), default="", nullable=False)
    tags_json: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    images_json: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    source_url: Mapped[str] = mapped_column(Text, default="", nullable=False)
    parse_confidence: Mapped[float] = mapped_column(Numeric(4, 2), default=0.5, nullable=False)

    raw_event = relationship("RawEvent", back_populates="candidates")
