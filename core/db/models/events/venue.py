from geoalchemy2 import Geography
from sqlalchemy import Index, String, UniqueConstraint
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
    geom = mapped_column(Geography(geometry_type="POINT", srid=4326), nullable=True)
    geocode_provider: Mapped[str] = mapped_column(String(32), default="", nullable=False)
    geocode_confidence: Mapped[float] = mapped_column(nullable=False, default=0.0)

    occurrences = relationship("EventOccurrence", back_populates="venue")
