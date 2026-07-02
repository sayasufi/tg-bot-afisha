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
    # How far the city's region reaches. Tight enough to SEPARATE adjacent cities so an event
    # belongs to ONE city (the closest pair, Екатеринбург–Челябинск, is ~194 km apart), yet wide
    # enough to cover a metro + its near suburbs. Also bounds venue relocation. Was 350 km, which
    # badly over-overlapped once the Volga/Ural million-plus cities were added (Казань–Самара ~296 km).
    region_radius_km: float = 100.0
    utc_offset_hours: int = 3  # fixed UTC offset (Russia has no DST) — drives per-city wall-clock display
    city_id: int | None = None  # ref.cities.city_id — bridges DB-keyed sources (Telegram channels) to this registry
    code: str = "MSK"  # airport-style public code for event codes ("MSK-04PN"); the ONE source of truth
    # for core.domain.codes (no stale parallel dict). Kept short/Latin/URL-safe. Defaults to MSK so a
    # city added without one still yields a valid (if unspecific) code rather than crashing.


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
        code="MSK",
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
        code="SPB",
    ),
}

# The million-plus cities (added 2026-06-24). Yandex.Afisha is the backbone (covers every one);
# KudaGo only has ekb/kzn/nnv (None elsewhere); afisha.ru covers all; Timepad filters by name.
# All slugs verified live. Russia has no DST, so utc_offset is a fixed, exact value used for the
# per-city wall-clock display. No ref.cities.city_id yet — those are only needed once a city gets
# its own Telegram venue channels.
_MILLIONNIKI = [
    # slug, name, tz, utc_offset, lat, lon, yandex_city, kudago_location, afisha_city, code
    # `code` = airport-style public event-code prefix ("NSK-04PN"); the registry is the ONE source
    # of truth for core.domain.codes (which previously had a stale parallel dict covering only 6/16).
    ("novosibirsk", "Новосибирск", "Asia/Novosibirsk", 7, 55.03977, 82.89163, "novosibirsk", None, "novosibirsk", "NSK"),
    ("ekaterinburg", "Екатеринбург", "Asia/Yekaterinburg", 5, 56.83894, 60.60570, "yekaterinburg", "ekb", "ekaterinburg", "EKB"),
    ("kazan", "Казань", "Europe/Moscow", 3, 55.79636, 49.10889, "kazan", "kzn", "kazan", "KZN"),
    ("krasnoyarsk", "Красноярск", "Asia/Krasnoyarsk", 7, 56.01083, 92.85237, "krasnoyarsk", None, "krasnoyarsk", "KJA"),
    ("nizhny-novgorod", "Нижний Новгород", "Europe/Moscow", 3, 56.32867, 44.00205, "nizhny-novgorod", "nnv", "nnovgorod", "NIN"),
    ("chelyabinsk", "Челябинск", "Asia/Yekaterinburg", 5, 55.15402, 61.42915, "chelyabinsk", None, "chelyabinsk", "CEK"),
    ("ufa", "Уфа", "Asia/Yekaterinburg", 5, 54.73479, 55.95790, "ufa", None, "ufa", "UFA"),
    ("krasnodar", "Краснодар", "Europe/Moscow", 3, 45.03547, 38.97532, "krasnodar", None, "krasnodar", "KRR"),
    ("samara", "Самара", "Europe/Samara", 4, 53.19506, 50.10199, "samara", None, "samara", "KUF"),
    ("rostov-on-don", "Ростов-на-Дону", "Europe/Moscow", 3, 47.22209, 39.71889, "rostov-na-donu", None, "rostov-na-donu", "ROV"),
    ("omsk", "Омск", "Asia/Omsk", 6, 54.98855, 73.32426, "omsk", None, "omsk", "OMS"),
    ("voronezh", "Воронеж", "Europe/Moscow", 3, 51.66078, 39.20029, "voronezh", None, "voronezh", "VOZ"),
    ("perm", "Пермь", "Asia/Yekaterinburg", 5, 58.01046, 56.25017, "perm", None, "prm", "PEE"),
    ("volgograd", "Волгоград", "Europe/Volgograd", 3, 48.70708, 44.51683, "volgograd", None, "volgograd", "VOG"),
]
# ref.cities.city_id per million-city — bridges DB-keyed Telegram venue channels
# (ref.telegram_channels.city_id) back to this registry so a channel's posts geocode in the right city.
# Moscow (1/2) and SPb (3) already exist; these rows are added in ref.cities for the million-plus cities.
_CITY_IDS = {
    "novosibirsk": 4, "ekaterinburg": 5, "kazan": 6, "krasnoyarsk": 7, "nizhny-novgorod": 8,
    "chelyabinsk": 9, "ufa": 10, "krasnodar": 11, "samara": 12, "rostov-on-don": 13,
    "omsk": 14, "voronezh": 15, "perm": 16, "volgograd": 17,
}
for _s, _n, _tz, _off, _lat, _lon, _y, _k, _a, _code in _MILLIONNIKI:
    CITIES[_s] = CityConfig(
        slug=_s, name=_n, country="RU", timezone=_tz, kudago_location=_k, yandex_city=_y,
        afisha_city=_a, active=True, center=(_lat, _lon), utc_offset_hours=_off,
        city_id=_CITY_IDS.get(_s), code=_code,
    )

DEFAULT_CITY = CITIES["moscow"]
# Resolvable by display name ("Москва") OR slug ("moscow"). Keep the slug alias for
# legacy rows/envs that still spell the default city as "Moscow".
_BY_NAME = {}
for _c in CITIES.values():
    _BY_NAME[_c.name.strip().lower()] = _c
    _BY_NAME[_c.slug.strip().lower()] = _c


def active_cities() -> list[CityConfig]:
    return [c for c in CITIES.values() if c.active]


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    from math import asin, cos, radians, sin, sqrt
    dlat, dlon = radians(lat2 - lat1), radians(lon2 - lon1)
    a = sin(dlat / 2) ** 2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlon / 2) ** 2
    return 2 * 6371.0 * asin(sqrt(a))


def nearest_city(lat: float, lon: float) -> CityConfig | None:
    """Ближайший АКТИВНЫЙ город к координатам (масштабируется на любое число городов — без сетки кнопок).
    Возвращает None, если все города дальше 2× их region_radius (юзер вне покрытия) — лучше ничего, чем
    приписать далёкий город."""
    best: CityConfig | None = None
    best_d = float("inf")
    for c in active_cities():
        d = _haversine_km(lat, lon, c.center[0], c.center[1])
        if d < best_d:
            best, best_d = c, d
    if best is not None and best_d <= best.region_radius_km * 2:
        return best
    return None


def _one_region_clause(c: "CityConfig") -> str:
    return (
        f"ST_DWithin(venues.geom, ST_SetSRID(ST_MakePoint({c.center[1]}, {c.center[0]}), 4326)::geography, "
        f"{c.region_radius_km * 1000})"
    )


def region_predicate_sql(
    city: "CityConfig | None" = None,
    bbox: "tuple[float, float, float, float] | None" = None,
    point: "tuple[float, float] | None" = None,
) -> str:
    """The 'venues.geom within a city's region radius' SQL predicate. Single source for the
    map/list/search/recs region guard, so a change to region semantics happens in one place.
    Coordinates come from this trusted registry — not user input — so the f-string interpolation
    is not an injection vector.

    Scoping, most→least specific:
      * `city` given  -> ONE clause for that city.
      * no `city`, but a `bbox` (min_lon,min_lat,max_lon,max_lat) or `point` (lat,lon) given
        -> resolve the ENCLOSING city (nearest to the bbox centre / the point) and emit ONE clause.
        A bounded request is always inside one city, so ORing all 16 regions was pure waste
        (16 ST_DWithin per row) — collapse it to the single city the viewport actually sits in.
      * no `city`, no bounds -> the true country-wide query: OR over all active cities.
    When a bbox/point falls outside every city's coverage, fall back to the all-cities OR
    (correct, if slower) rather than silently returning no region."""
    if city is None:
        anchor = None
        if bbox is not None:
            min_lon, min_lat, max_lon, max_lat = bbox
            anchor = nearest_city((min_lat + max_lat) / 2.0, (min_lon + max_lon) / 2.0)
        elif point is not None:
            anchor = nearest_city(point[0], point[1])
        if anchor is not None:
            city = anchor  # bounded request -> single enclosing city
    cities = [city] if city is not None else active_cities()
    parts = [_one_region_clause(c) for c in cities]
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
