"""Reverse-geocode coordinates to a city name (for saving the user's home city)."""
import logging

import httpx

from core.config.settings import get_settings

logger = logging.getLogger(__name__)

# Greater Moscow bounding box (lat_min, lat_max, lon_min, lon_max). Moscow is the
# only city we serve today, so we resolve it locally and skip the Nominatim call
# (and its rate limit) for the overwhelmingly common case.
_MOSCOW = (55.05, 56.10, 36.70, 38.30)

# Cache resolved city names by a ~1km coordinate bucket, so repeated location fixes (and
# any abuse) don't re-hit the public Nominatim per call (it has a strict usage policy).
_cache: dict[tuple[float, float], str | None] = {}


def reverse_city(lat: float, lon: float) -> str | None:
    """Best-effort city name in Russian; returns None if it cannot be resolved."""
    if _MOSCOW[0] <= lat <= _MOSCOW[1] and _MOSCOW[2] <= lon <= _MOSCOW[3]:
        return "Москва"

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
                result = address[key]
                break
    except Exception:
        logger.warning("reverse geocode failed for %s,%s", lat, lon, exc_info=True)
    _cache[ckey] = result
    return result
