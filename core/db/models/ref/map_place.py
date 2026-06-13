from geoalchemy2 import Geography
from sqlalchemy import JSON, Index, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from core.db.base import Base
from core.db.models.mixins import TimestampMixin


class MapPlace(Base, TimestampMixin):
    """Curated map reference points (metro stations, parks, future landmarks).

    A single typed table so any city / any kind of overlay point lives in one place
    instead of static JSON files. `kind` discriminates ('metro', 'park', ...),
    `color` carries the metro line colour (null otherwise), `meta_json` holds extras.
    """

    __tablename__ = "map_places"
    __table_args__ = (
        UniqueConstraint("kind", "city_id", "name", name="uq_map_place_kind_city_name"),
        Index("ix_map_places_kind_city", "kind", "city_id"),
        Index("ix_map_places_geom", "geom", postgresql_using="gist"),
        {"schema": "ref"},
    )

    place_id: Mapped[int] = mapped_column(primary_key=True)
    city_id: Mapped[int | None] = mapped_column(nullable=True)
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    geom = mapped_column(Geography(geometry_type="POINT", srid=4326, spatial_index=False), nullable=False)
    color: Mapped[str | None] = mapped_column(String(16), nullable=True)
    source: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    meta_json: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
