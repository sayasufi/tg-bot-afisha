"""Reverse-geocode coordinates to a city name (for saving the user's home city)."""
import logging
import re

import httpx

from core.config.settings import get_settings
from core.domain.cities import nearest_city

logger = logging.getLogger(__name__)

# Greater Moscow bounding box (lat_min, lat_max, lon_min, lon_max). We resolve it locally
# and skip the Nominatim call (and its rate limit) for the overwhelmingly common case.
_MOSCOW = (55.05, 56.10, 36.70, 38.30)

# Russian administrative prefixes Nominatim prepends to municipality/county names
# ("городской округ Самара", "муниципальное образование …"). They must be stripped, else
# the raw name never round-trips through city_by_name and the city_slug stays NULL.
_ADMIN_PREFIX_RE = re.compile(
    r"^(?:городской округ|муниципальное образование|муниципальный округ|"
    r"городское поселение|сельское поселение|го|мо)\s+",
    re.IGNORECASE,
)

# Cache resolved city names by a ~1km coordinate bucket, so repeated location fixes (and
# any abuse) don't re-hit the public Nominatim per call (it has a strict usage policy).
_cache: dict[tuple[float, float], str | None] = {}


def _strip_admin_prefix(name: str) -> str:
    """Drop a leading Russian admin-unit prefix so the bare city name can match the registry."""
    return _ADMIN_PREFIX_RE.sub("", name).strip()


def reverse_city(lat: float, lon: float) -> str | None:
    """Best-effort city name in Russian; returns None if it cannot be resolved.

    Primary resolver is nearest_city() from the city registry: coordinates are unambiguous,
    and returning the registry's CANONICAL display name guarantees a round-trip through
    city_by_name → city_slug for all 16 cities (raw Nominatim names — "городской округ
    Самара", oblast labels, English transliterations — silently fail that exact match).
    Nominatim is only a display/fallback for points outside every city region."""
    if _MOSCOW[0] <= lat <= _MOSCOW[1] and _MOSCOW[2] <= lon <= _MOSCOW[3]:
        return "Москва"

    # Coordinates → nearest active city (only within its region radius). This is the path
    # that unblocks the non-Moscow cities: its name matches the registry exactly.
    city = nearest_city(lat, lon)
    if city is not None:
        return city.name

    ckey = (round(lat, 2), round(lon, 2))
    if ckey in _cache:
        return _cache[ckey]
    if len(_cache) > 5000:  # bound it — coordinate buckets are limited but not infinite
        _cache.clear()

    settings = get_settings()
    result: str | None = None
    try:
        response = httpx.get(
            f"{settings.nominatim_base_url}/reverse",
            params={"lat": lat, "lon": lon, "format": "jsonv2", "accept-language": "ru", "zoom": 10},
            headers={"User-Agent": "tg-bot-afisha/1.0 (okrest reverse geocode)"},
            timeout=6.0,
        )
        response.raise_for_status()
        address = response.json().get("address", {})
        for key in ("city", "town", "village", "municipality", "county", "state"):
            if address.get(key):
                result = _strip_admin_prefix(address[key])
                break
    except Exception:
        logger.warning("reverse geocode failed for %s,%s", lat, lon, exc_info=True)
    _cache[ckey] = result
    return result
