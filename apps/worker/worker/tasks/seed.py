import logging
import re

import httpx

from core.db.repositories.places import upsert_map_place
from core.db.repositories.users import get_or_create_city
from core.db.session import SessionLocal

from apps.worker.worker.celery_app import celery_app

logger = logging.getLogger(__name__)

_WDQS = "https://query.wikidata.org/sparql"
_HEADERS = {"User-Agent": "tg-bot-afisha/1.0 (map places seeder)"}
_POINT_RE = re.compile(r"Point\(([-0-9.]+) ([-0-9.]+)\)")

# Metro line colours missing from Wikidata P465.
_LINE_COLOR_FALLBACK = {"Рублёво-Архангельская линия": "#6BC4C9"}

# Shorten a few official park names to what people actually call them.
_PARK_NAME_OVERRIDES = {
    "Выставка достижений народного хозяйства": "ВДНХ",
    "Центральный парк культуры и отдыха им. Горького": "Парк Горького",
    "Царицыно (дворцово-парковый ансамбль)": "Царицыно",
    "Главный ботанический сад имени Н. В. Цицина РАН": "Ботанический сад",
    "Парк Победы (Москва)": "Парк Победы",
    "Парк искусств": "Музеон",
}

_METRO_QUERY = """
SELECT ?station ?stationLabel ?coord ?color WHERE {
  ?station wdt:P81 ?line . ?line wdt:P16 wd:Q5499 .
  ?station wdt:P625 ?coord .
  OPTIONAL { ?line wdt:P465 ?color . }
  ?station rdfs:label ?stationLabel . FILTER(LANG(?stationLabel)="ru")
  ?line rdfs:label ?lineLabel . FILTER(LANG(?lineLabel)="ru")
}
"""

_PARKS_QUERY = """
SELECT ?item ?itemLabel ?coord (COUNT(DISTINCT ?sl) AS ?links) WHERE {
  ?item wdt:P31 ?type . VALUES ?type { wd:Q22698 wd:Q22746 wd:Q167346 wd:Q1107656 wd:Q194195 wd:Q2416723 }
  ?item wdt:P131* wd:Q649 .
  ?item wdt:P625 ?coord .
  ?item rdfs:label ?itemLabel . FILTER(LANG(?itemLabel)="ru")
  OPTIONAL { ?sl schema:about ?item . }
} GROUP BY ?item ?itemLabel ?coord HAVING(COUNT(DISTINCT ?sl) >= 6)
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
    count = 0
    for r in _wdqs(_PARKS_QUERY):
        coord = _coord(r)
        if not coord:
            continue
        raw_name = r["itemLabel"]["value"]
        name = _PARK_NAME_OVERRIDES.get(raw_name, raw_name)
        upsert_map_place(
            db, kind="park", city_id=city_id, name=name,
            lat=coord[0], lon=coord[1], source="wikidata",
        )
        count += 1
    return count


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
