"""City registry — the single place that makes the pipeline multi-city.

Adding a city is a data change here (+ flipping `active` and adding its beat tasks),
not a code change scattered across connectors/tasks/enrich. The DB `ref.cities` table
holds display/geo data; this registry holds the per-source connector parameters
(KudaGo location slug, Yandex city slug) that the connectors and enrich need.
"""
from dataclasses import dataclass


@dataclass(frozen=True)
class CityConfig:
    slug: str  # internal key, e.g. "moscow"
    name: str  # display / venue city, e.g. "Москва"
    country: str  # ISO, e.g. "RU"
    timezone: str  # IANA tz
    kudago_location: str  # KudaGo location slug
    yandex_city: str  # Yandex Afisha city slug (afisha.yandex.ru/<slug>)
    afisha_city: str  # afisha.ru city slug (afisha.ru/<slug>/schedule_*)
    active: bool  # whether the pipeline currently ingests this city
    center: tuple[float, float]  # (lat, lon) city centre — anchors geo heuristics
    # How far the city's region reaches (day-trip oblast venues + far festivals). Used
    # both to keep events on the map and to bound venue relocation. Wide enough for a
    # cross-oblast festival (~330 km) yet far short of another city (SPb 635 km) or
    # transposed/foreign coords (Caspian/Almaty >1000 km).
    region_radius_km: float = 350.0


CITIES: dict[str, CityConfig] = {
    "moscow": CityConfig(
        slug="moscow",
        name="Москва",
        country="RU",
        timezone="Europe/Moscow",
        kudago_location="msk",
        yandex_city="moscow",
        afisha_city="msk",
        active=True,
        center=(55.75582, 37.61764),
    ),
    # ACTIVE (Phase 1): ingested via the per-city kudago + yandex fetch flows that loop
    # active_cities(). Telegram channels, afisha.ru (needs the SPb GraphQL city id) and
    # Timepad stay Moscow-only for now (Phase 2).
    "spb": CityConfig(
        slug="spb",
        name="Санкт-Петербург",
        country="RU",
        timezone="Europe/Moscow",
        kudago_location="spb",
        yandex_city="saint-petersburg",
        afisha_city="spb",
        active=True,
        center=(59.93863, 30.31413),
    ),
}

DEFAULT_CITY = CITIES["moscow"]
# Resolvable by display name ("Москва") OR slug ("moscow"). The slug keys also catch
# the Latin default hint settings.default_city="Moscow" (== the moscow slug), which
# would otherwise miss the Cyrillic name and silently disable geo guards keyed on it.
_BY_NAME = {}
for _c in CITIES.values():
    _BY_NAME[_c.name.strip().lower()] = _c
    _BY_NAME[_c.slug.strip().lower()] = _c


def active_cities() -> list[CityConfig]:
    return [c for c in CITIES.values() if c.active]


def region_predicate_sql(city: "CityConfig | None" = None) -> str:
    """The 'venues.geom within a city's region radius' SQL predicate, OR-ed over the given
    city (or all active cities when None). Single source for the map/list/search/recs region
    guard, so a change to region semantics happens in one place. Coordinates come from this
    trusted registry — not user input — so the f-string interpolation is not an injection vector."""
    cities = [city] if city is not None else active_cities()
    parts = [
        f"ST_DWithin(venues.geom, ST_SetSRID(ST_MakePoint({c.center[1]}, {c.center[0]}), 4326)::geography, {c.region_radius_km * 1000})"
        for c in cities
    ]
    return "(" + " OR ".join(parts) + ")" if parts else "true"


def city_by_slug(slug: str | None) -> CityConfig:
    return CITIES.get(slug or "", DEFAULT_CITY)


def city_by_name(name: str | None) -> CityConfig | None:
    """The city whose display name matches (e.g. a venue's stored city), or None."""
    return _BY_NAME.get((name or "").strip().lower())


def city_for_source_config(config: dict | None) -> CityConfig:
    """Resolve a city from a source's config_json (it stores a Yandex `city` or
    KudaGo `location` slug). Falls back to the default city."""
    if isinstance(config, dict):
        token = config.get("city") or config.get("location")
        if token:
            for city in CITIES.values():
                if token in (city.slug, city.kudago_location, city.yandex_city):
                    return city
    return DEFAULT_CITY
