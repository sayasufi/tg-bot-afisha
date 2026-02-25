from sqlalchemy import Index, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from geoalchemy2 import Geography

from core.db.base import Base


class City(Base):
    __tablename__ = "cities"
    __table_args__ = (
        UniqueConstraint("name", "country", name="uq_city_name_country"),
        Index("ix_cities_center", "center", postgresql_using="gist"),
    )

    city_id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    country: Mapped[str] = mapped_column(String(8), nullable=False)
    timezone: Mapped[str] = mapped_column(String(64), default="UTC", nullable=False)
    center = mapped_column(Geography(geometry_type="POINT", srid=4326), nullable=True)
