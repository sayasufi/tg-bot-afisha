import uuid

from sqlalchemy import Float, Index, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from core.db.base import Base
from core.db.models.mixins import TimestampMixin


class Event(Base, TimestampMixin):
    __tablename__ = "events"
    __table_args__ = (
        Index("ix_events_title_trgm", "canonical_title", postgresql_using="gin", postgresql_ops={"canonical_title": "gin_trgm_ops"}),
        Index(
            "ix_events_desc_trgm",
            "canonical_description",
            postgresql_using="gin",
            postgresql_ops={"canonical_description": "gin_trgm_ops"},
        ),
    )

    event_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    canonical_title: Mapped[str] = mapped_column(String(500), nullable=False)
    canonical_description: Mapped[str] = mapped_column(Text, default="", nullable=False)
    category: Mapped[str] = mapped_column(String(64), default="other", nullable=False)
    subcategory: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    age_limit: Mapped[str] = mapped_column(String(32), default="", nullable=False)
    popularity_score: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    rating_score: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    primary_image_url: Mapped[str] = mapped_column(Text, default="", nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="active", nullable=False)

    occurrences = relationship("EventOccurrence", back_populates="event")
    sources = relationship("EventSource", back_populates="event")
