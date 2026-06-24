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
    kudago_location: str | None  # KudaGo location slug, or None if KudaGo doesn't cover the city
    yandex_city: str  # Yandex Afisha city slug (afisha.yandex.ru/<slug>) — the backbone, covers every city
    afisha_city: str | None  # afisha.ru city slug (afisha.ru/<slug>/schedule_*), or None if not covered
    active: bool  # whether the pipeline currently ingests this city
    center: tuple[float, float]  # (lat, lon) city centre — anchors geo heuristics
    # How far the city's region reaches (day-trip oblast venues + far festivals). Used
    # both to keep events on the map and to bound venue relocation. Wide enough for a
    # cross-oblast festival (~330 km) yet far short of another city (SPb 635 km) or
    # transposed/foreign coords (Caspian/Almaty >1000 km).
    region_radius_km: float = 350.0
    utc_offset_hours: int = 3  # fixed UTC offset (Russia has no DST) — drives per-city wall-clock display
    city_id: int | None = None  # ref.cities.city_id — bridges DB-keyed sources (Telegram channels) to this registry


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
        city_id=1,
    ),
    # ACTIVE: ingested via the per-city kudago/yandex/timepad/afisha fetch flows AND its own
    # Telegram venue channels (ref.cities city_id=3). afisha date-RESOLUTION stays Moscow-only
    # (its GraphQL schedule filter uses Moscow's City_2), so SPb afisha keeps listing spans for now.
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
        city_id=3,
    ),
}

# The million-plus cities (added 2026-06-24). Yandex.Afisha is the backbone (covers every one);
# KudaGo only has ekb/kzn/nnv (None elsewhere); afisha.ru covers all; Timepad filters by name.
# All slugs verified live. Russia has no DST, so utc_offset is a fixed, exact value used for the
# per-city wall-clock display. No ref.cities.city_id yet — those are only needed once a city gets
# its own Telegram venue channels.
_MILLIONNIKI = [
    # slug, name, tz, utc_offset, lat, lon, yandex_city, kudago_location, afisha_city
    ("novosibirsk", "Новосибирск", "Asia/Novosibirsk", 7, 55.03977, 82.89163, "novosibirsk", None, "novosibirsk"),
    ("ekaterinburg", "Екатеринбург", "Asia/Yekaterinburg", 5, 56.83894, 60.60570, "yekaterinburg", "ekb", "ekaterinburg"),
    ("kazan", "Казань", "Europe/Moscow", 3, 55.79636, 49.10889, "kazan", "kzn", "kazan"),
    ("krasnoyarsk", "Красноярск", "Asia/Krasnoyarsk", 7, 56.01083, 92.85237, "krasnoyarsk", None, "krasnoyarsk"),
    ("nizhny-novgorod", "Нижний Новгород", "Europe/Moscow", 3, 56.32867, 44.00205, "nizhny-novgorod", "nnv", "nnovgorod"),
    ("chelyabinsk", "Челябинск", "Asia/Yekaterinburg", 5, 55.15402, 61.42915, "chelyabinsk", None, "chelyabinsk"),
    ("ufa", "Уфа", "Asia/Yekaterinburg", 5, 54.73479, 55.95790, "ufa", None, "ufa"),
    ("krasnodar", "Краснодар", "Europe/Moscow", 3, 45.03547, 38.97532, "krasnodar", None, "krasnodar"),
    ("samara", "Самара", "Europe/Samara", 4, 53.19506, 50.10199, "samara", None, "samara"),
    ("rostov-on-don", "Ростов-на-Дону", "Europe/Moscow", 3, 47.22209, 39.71889, "rostov-na-donu", None, "rostov-na-donu"),
    ("omsk", "Омск", "Asia/Omsk", 6, 54.98855, 73.32426, "omsk", None, "omsk"),
    ("voronezh", "Воронеж", "Europe/Moscow", 3, 51.66078, 39.20029, "voronezh", None, "voronezh"),
    ("perm", "Пермь", "Asia/Yekaterinburg", 5, 58.01046, 56.25017, "perm", None, "prm"),
    ("volgograd", "Волгоград", "Europe/Volgograd", 3, 48.70708, 44.51683, "volgograd", None, "volgograd"),
]
for _s, _n, _tz, _off, _lat, _lon, _y, _k, _a in _MILLIONNIKI:
    CITIES[_s] = CityConfig(
        slug=_s, name=_n, country="RU", timezone=_tz, kudago_location=_k, yandex_city=_y,
        afisha_city=_a, active=True, center=(_lat, _lon), utc_offset_hours=_off,
    )

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
    """Resolve a city from a source's config_json — a Yandex `city` / KudaGo `location`
    slug, or a Telegram channel's numeric `city_id` (ref.cities PK). Falls back to default."""
    if isinstance(config, dict):
        token = config.get("city") or config.get("location")
        if token:
            for city in CITIES.values():
                if token in (city.slug, city.kudago_location, city.yandex_city):
                    return city
        cid = config.get("city_id")
        if cid is not None:
            for city in CITIES.values():
                if city.city_id == cid:
                    return city
    return DEFAULT_CITY
