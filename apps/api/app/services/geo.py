"""Reverse-geocode coordinates to a city name (for saving the user's home city)."""
import logging

import httpx

from core.config.settings import get_settings

logger = logging.getLogger(__name__)

# Greater Moscow bounding box (lat_min, lat_max, lon_min, lon_max). Moscow is the
# only city we serve today, so we resolve it locally and skip the Nominatim call
# (and its rate limit) for the overwhelmingly common case.
_MOSCOW = (55.05, 56.10, 36.70, 38.30)


def reverse_city(lat: float, lon: float) -> str | None:
    """Best-effort city name in Russian; returns None if it cannot be resolved."""
    if _MOSCOW[0] <= lat <= _MOSCOW[1] and _MOSCOW[2] <= lon <= _MOSCOW[3]:
        return "Москва"

    settings = get_settings()
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
                return address[key]
    except Exception:
        logger.warning("reverse geocode failed for %s,%s", lat, lon, exc_info=True)
    return None
