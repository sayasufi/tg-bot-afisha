import json

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from core.db.models import City
from core.db.repositories.places import list_map_places
from core.db.session import get_db

router = APIRouter(prefix="/v1", tags=["places"])


def _meta(value) -> dict:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            return json.loads(value)
        except ValueError:
            return {}
    return {}


@router.get("/places")
def places(kind: str, city: str | None = None, db: Session = Depends(get_db)) -> dict:
    """Curated map overlay points (kind=metro|park|…) as a GeoJSON FeatureCollection."""
    city_id = None
    if city:
        city_id = db.execute(select(City.city_id).where(City.name == city)).scalar_one_or_none()

    rows = list_map_places(db, kind=kind, city_id=city_id)

    def _feature(row) -> dict:
        m = _meta(row.get("meta_json"))
        props = {
            "name": row["name"],
            "color": row["color"],
            "kind": kind,
            "minzoom": m.get("minzoom", 13),
        }
        # Metro stations carry their line (for whole-line highlighting).
        if m.get("line"):
            props["line"] = m["line"]
        if m.get("line_id"):
            props["line_id"] = m["line_id"]
        return {
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [row["lon"], row["lat"]]},
            "properties": props,
        }

    features = [_feature(row) for row in rows if row["lat"] is not None and row["lon"] is not None]
    return {"type": "FeatureCollection", "features": features}
