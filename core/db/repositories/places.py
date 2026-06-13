from sqlalchemy import and_, func, select, text
from sqlalchemy.orm import Session

from core.db.models import MapPlace


def upsert_map_place(
    db: Session,
    *,
    kind: str,
    city_id: int | None,
    name: str,
    lat: float,
    lon: float,
    color: str | None = None,
    source: str = "",
    meta: dict | None = None,
) -> MapPlace:
    geom = func.ST_SetSRID(func.ST_MakePoint(lon, lat), 4326)
    existing = db.execute(
        select(MapPlace).where(and_(MapPlace.kind == kind, MapPlace.city_id == city_id, MapPlace.name == name))
    ).scalar_one_or_none()
    if existing:
        existing.geom = geom
        existing.color = color or None
        existing.source = source
        existing.meta_json = meta or {}
        db.add(existing)
        db.commit()
        return existing

    place = MapPlace(kind=kind, city_id=city_id, name=name, color=color or None, source=source, meta_json=meta or {})
    place.geom = geom
    db.add(place)
    db.commit()
    db.refresh(place)
    return place


def list_map_places(db: Session, kind: str, city_id: int | None = None) -> list[dict]:
    rows = db.execute(
        text(
            "SELECT name, color, ST_Y(geom::geometry) AS lat, ST_X(geom::geometry) AS lon "
            "FROM ref.map_places WHERE kind = :kind AND (:city_id IS NULL OR city_id = :city_id)"
        ),
        {"kind": kind, "city_id": city_id},
    ).mappings().all()
    return [dict(r) for r in rows]
