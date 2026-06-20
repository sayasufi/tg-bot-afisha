from datetime import datetime

from geoalchemy2 import Geography
from sqlalchemy import DateTime, Index, JSON, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from core.db.base import Base
from core.db.models.mixins import TimestampMixin


class Venue(Base, TimestampMixin):
    __tablename__ = "venues"
    __table_args__ = (
        UniqueConstraint("name", "address", name="uq_venue_name_address"),
        Index("ix_venues_geom", "geom", postgresql_using="gist"),
        {"schema": "events"},
    )

    venue_id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    address: Mapped[str] = mapped_column(String(500), default="", nullable=False)
    city: Mapped[str] = mapped_column(String(120), default="", nullable=False)
    country: Mapped[str] = mapped_column(String(8), default="", nullable=False)
    # spatial_index=False: the gist index is declared explicitly above (ix_venues_geom). Without this,
    # GeoAlchemy ALSO auto-creates idx_venues_geom — a duplicate gist(geom) (see migration 0025).
    geom = mapped_column(Geography(geometry_type="POINT", srid=4326, spatial_index=False), nullable=True)
    geocode_provider: Mapped[str] = mapped_column(String(32), default="", nullable=False)
    geocode_confidence: Mapped[float] = mapped_column(nullable=False, default=0.0)
    # Opening hours, source-agnostic (resolved via Yandex Maps by name+coords):
    # {"text": "пн-чт 09:00–18:00; …", "week": [day0..day6]} where day = list of
    # ["HH:MM","HH:MM"] ranges or null (closed); index 0=Sunday (JS getDay).
    hours_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    # When hours were last resolved (real or empty). Lets the flow re-check stale
    # empty results, so resolver improvements / transient failures self-heal.
    hours_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    occurrences = relationship("EventOccurrence", back_populates="venue")
