import logging
import math
import re

import httpx
from sqlalchemy import text

from core.db.repositories.places import upsert_map_place
from core.db.repositories.users import get_or_create_city
from core.db.session import SessionLocal

from apps.worker.worker.celery_app import celery_app

logger = logging.getLogger(__name__)

_WDQS = "https://query.wikidata.org/sparql"
_OVERPASS = "https://overpass-api.de/api/interpreter"
_HEADERS = {"User-Agent": "tg-bot-afisha/1.0 (map places seeder)"}
_POINT_RE = re.compile(r"Point\(([-0-9.]+) ([-0-9.]+)\)")

# All named green areas in Moscow with full geometry (to size each park).
_PARKS_OVERPASS_QUERY = """[out:json][timeout:180];
area["name"="Москва"]["admin_level"="4"]->.m;
(
  way["leisure"~"^(park|garden|nature_reserve)$"]["name"](area.m);
  relation["leisure"~"^(park|garden|nature_reserve)$"]["name"](area.m);
  way["tourism"="theme_park"]["name"](area.m);
  relation["tourism"="theme_park"]["name"](area.m);
  relation["boundary"="national_park"]["name"](area.m);
);
out geom;"""

# Famous parks OSM tags here as something other than leisure=park (or sit outside the
# admin boundary), so they slip through the query — (name, lat, lon, minzoom).
_MANUAL_PARKS = [
    ("ВДНХ", 55.829722, 37.632222, 11),
    ("Лосиный Остров", 55.8716, 37.7906, 10),
]


def _bbox(element: dict) -> tuple[float, float, float, float] | None:
    bounds = element.get("bounds")
    if bounds:
        return bounds["minlat"], bounds["minlon"], bounds["maxlat"], bounds["maxlon"]
    geometry = element.get("geometry") or []
    lats = [p["lat"] for p in geometry if p]
    lons = [p["lon"] for p in geometry if p]
    if not lats:
        return None
    return min(lats), min(lons), max(lats), max(lons)


def _ring_coords(points: list) -> str | None:
    coords = [(p["lon"], p["lat"]) for p in (points or []) if p and "lat" in p and "lon" in p]
    if len(coords) < 3:
        return None
    if coords[0] != coords[-1]:
        coords.append(coords[0])
    if len(coords) < 4:
        return None
    return ",".join(f"{lon} {lat}" for lon, lat in coords)


def _polygon_wkt(element: dict) -> str | None:
    """WKT polygon/multipolygon for a park, used to derive a point guaranteed inside it."""
    if element.get("type") == "way":
        coords = _ring_coords(element.get("geometry"))
        return f"POLYGON(({coords}))" if coords else None
    if element.get("type") == "relation":
        parts = []
        for member in element.get("members", []):
            if member.get("type") == "way" and member.get("role") in ("outer", ""):
                coords = _ring_coords(member.get("geometry"))
                if coords:
                    parts.append(f"(({coords}))")
        if parts:
            return "MULTIPOLYGON(" + ",".join(parts) + ")"
    return None


def _minzoom_for(bbox: tuple[float, float, float, float]) -> int:
    """Larger parks get a lower minzoom (labelled from farther out); tiny squares
    only appear when you are zoomed right in."""
    minlat, minlon, maxlat, maxlon = bbox
    height = (maxlat - minlat) * 111320
    width = (maxlon - minlon) * 111320 * math.cos(math.radians((minlat + maxlat) / 2))
    size = max(height, width)
    if size >= 3000:
        return 10
    if size >= 1500:
        return 11
    if size >= 800:
        return 12
    if size >= 400:
        return 13
    if size >= 200:
        return 14
    return 15

_METRO_QUERY = """
SELECT ?station ?stationLabel ?coord ?color WHERE {
  ?station wdt:P81 ?line . ?line wdt:P16 wd:Q5499 .
  ?station wdt:P625 ?coord .
  OPTIONAL { ?line wdt:P465 ?color . }
  ?station rdfs:label ?stationLabel . FILTER(LANG(?stationLabel)="ru")
  ?line rdfs:label ?lineLabel . FILTER(LANG(?lineLabel)="ru")
}
"""


def _wdqs(query: str) -> list[dict]:
    with httpx.Client(timeout=60, headers=_HEADERS) as client:
        resp = client.get(_WDQS, params={"format": "json", "query": query})
        resp.raise_for_status()
        return resp.json()["results"]["bindings"]


def _coord(binding: dict) -> tuple[float, float] | None:
    m = _POINT_RE.search(binding["coord"]["value"])
    if not m:
        return None
    return float(m.group(2)), float(m.group(1))  # (lat, lon)


def _seed_metro(db, city_id: int) -> int:
    seen: set[str] = set()
    count = 0
    for r in _wdqs(_METRO_QUERY):
        qid = r["station"]["value"].rsplit("/", 1)[-1]
        if qid in seen:
            continue
        seen.add(qid)
        coord = _coord(r)
        if not coord:
            continue
        color = ("#" + r["color"]["value"]) if r.get("color") else "#9aa6bd"
        upsert_map_place(
            db, kind="metro", city_id=city_id, name=r["stationLabel"]["value"],
            lat=coord[0], lon=coord[1], color=color, source="wikidata",
        )
        count += 1
    return count


def _seed_parks(db, city_id: int) -> int:
    # name_key -> (name, lat, lon, minzoom). Label point = bbox centre; minzoom by size.
    merged: dict[str, tuple[str, float, float, int]] = {}
    with httpx.Client(timeout=200, headers=_HEADERS) as client:
        resp = client.post(_OVERPASS, content=_PARKS_OVERPASS_QUERY.encode("utf-8"))
        resp.raise_for_status()
        for e in resp.json().get("elements", []):
            name = (e.get("tags", {}).get("name") or "").strip()
            bbox = _bbox(e)
            if not name or not bbox:
                continue
            # A point guaranteed INSIDE the park (bbox centre lands on roads for
            # elongated/L-shaped parks); fall back to bbox centre if it fails.
            lat = (bbox[0] + bbox[2]) / 2
            lon = (bbox[1] + bbox[3]) / 2
            wkt = _polygon_wkt(e)
            if wkt:
                try:
                    row = db.execute(
                        text("SELECT ST_Y(p) AS lat, ST_X(p) AS lon FROM "
                             "(SELECT ST_PointOnSurface(ST_Buffer(ST_GeomFromText(:wkt, 4326), 0)) AS p) s"),
                        {"wkt": wkt},
                    ).first()
                    if row and row.lat is not None:
                        lat, lon = float(row.lat), float(row.lon)
                except Exception:
                    db.rollback()
            if not (55.0 <= lat <= 56.2 and 36.7 <= lon <= 38.4):
                continue
            merged[name.casefold()] = (name, lat, lon, _minzoom_for(bbox))

    for name, lat, lon, minzoom in _MANUAL_PARKS:
        merged[name.casefold()] = (name, lat, lon, minzoom)

    for name, lat, lon, minzoom in merged.values():
        upsert_map_place(
            db, kind="park", city_id=city_id, name=name,
            lat=lat, lon=lon, source="osm", meta={"minzoom": minzoom},
        )
    return len(merged)


@celery_app.task(bind=True, max_retries=2)
def seed_map_places(self, city: str = "Moscow"):
    """Populate ref.map_places (metro + parks) from Wikidata. Idempotent (upsert)."""
    db = SessionLocal()
    try:
        city_row = get_or_create_city(db, city)
        metro = _seed_metro(db, city_row.city_id)
        parks = _seed_parks(db, city_row.city_id)
        logger.info("seed_map_places", extra={"metro": metro, "parks": parks})
        return {"metro": metro, "parks": parks}
    except Exception as exc:
        raise self.retry(exc=exc)
    finally:
        db.close()
