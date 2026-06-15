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
    active: bool  # whether the pipeline currently ingests this city


CITIES: dict[str, CityConfig] = {
    "moscow": CityConfig(
        slug="moscow",
        name="Москва",
        country="RU",
        timezone="Europe/Moscow",
        kudago_location="msk",
        yandex_city="moscow",
        active=True,
    ),
    # Defined and ready — flip active=True and add beat tasks for it to ingest SPb.
    "spb": CityConfig(
        slug="spb",
        name="Санкт-Петербург",
        country="RU",
        timezone="Europe/Moscow",
        kudago_location="spb",
        yandex_city="saint-petersburg",
        active=False,
    ),
}

DEFAULT_CITY = CITIES["moscow"]


def active_cities() -> list[CityConfig]:
    return [c for c in CITIES.values() if c.active]


def city_by_slug(slug: str | None) -> CityConfig:
    return CITIES.get(slug or "", DEFAULT_CITY)


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
