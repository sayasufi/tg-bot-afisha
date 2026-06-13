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
    features = [
        {
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [row["lon"], row["lat"]]},
            "properties": {
                "name": row["name"],
                "color": row["color"],
                "kind": kind,
                "minzoom": _meta(row.get("meta_json")).get("minzoom", 13),
            },
        }
        for row in rows
        if row["lat"] is not None and row["lon"] is not None
    ]
    return {"type": "FeatureCollection", "features": features}
