import uuid

from sqlalchemy import BigInteger, Float, Index, String, Text, text
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
        Index("ix_events_status_category", "status", "category"),
        {"schema": "events"},
    )

    event_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    # Stable public number behind the "MSK-04PN" code (see core/codes.py). Assigned
    # once from a DB sequence (migration 0009) and never reused — unique by design.
    display_no: Mapped[int | None] = mapped_column(
        BigInteger, server_default=text("nextval('events.events_display_no_seq')"), unique=True, nullable=True
    )
    canonical_title: Mapped[str] = mapped_column(String(500), nullable=False)
    canonical_description: Mapped[str] = mapped_column(Text, default="", nullable=False)
    category: Mapped[str] = mapped_column(String(64), default="other", nullable=False)
    subcategory: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    age_limit: Mapped[str] = mapped_column(String(32), default="", nullable=False)
    popularity_score: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    rating_score: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    primary_image_url: Mapped[str] = mapped_column(Text, default="", nullable=False)
    # URL of our own cached/resized copy (MinIO via /v1/media); null until cached.
    cached_image_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="active", nullable=False)

    occurrences = relationship("EventOccurrence", back_populates="event")
    sources = relationship("EventSource", back_populates="event")
