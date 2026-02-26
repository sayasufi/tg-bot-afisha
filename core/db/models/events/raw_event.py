from datetime import datetime

from sqlalchemy import JSON, DateTime, ForeignKey, Index, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from core.db.base import Base


class RawEvent(Base):
    __tablename__ = "raw_events"
    __table_args__ = (
        UniqueConstraint("source_id", "external_id", name="uq_raw_source_external"),
        Index("ix_raw_content_hash", "content_hash"),
        Index("ix_raw_fetched_at", "fetched_at"),
        {"schema": "events"},
    )

    raw_id: Mapped[int] = mapped_column(primary_key=True)
    source_id: Mapped[int] = mapped_column(ForeignKey("ref.sources.source_id", ondelete="CASCADE"), nullable=False)
    external_id: Mapped[str] = mapped_column(String(255), nullable=False)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    raw_payload_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    raw_text: Mapped[str] = mapped_column(Text, default="", nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)

    source = relationship("Source", back_populates="raw_events")
    candidates = relationship("EventCandidate", back_populates="raw_event")
