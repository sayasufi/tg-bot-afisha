import hashlib
import re

from core.domain.cities import city_by_name
from core.config.settings import get_settings
from pipeline.geocoding.providers.nominatim import NominatimGeocoder
from pipeline.geocoding.providers.yandex import GeoResult, YandexGeocoder
from pipeline.geocoding.providers.yandex_maps import YandexMapsScraper


def _is_city_centroid(result: "GeoResult", city: str | None) -> bool:
    """A provider falls back to the CITY CENTRE when it can't resolve a query; accepting
    it pins every unresolved venue on one spot. So a result within ~30 m of the city's
    own centre (from core.domain.cities — city-agnostic, not just Moscow) is treated as no match."""
    cc = city_by_name(city)
    if not cc:
        return False
    lat, lon = cc.center
    return abs(result.lat - lat) < 3.0e-4 and abs(result.lon - lon) < 5.0e-4


class GeocodingService:
    def __init__(self) -> None:
        settings = get_settings()
        self.default_city = settings.default_city
        self.yandex = YandexGeocoder(settings.yandex_geocoder_key)
        self.yandex_maps = YandexMapsScraper()
        self.nominatim = NominatimGeocoder(settings.nominatim_base_url)
        self._cache: dict[str, GeoResult] = {}

    async def _yandex_maps_result(self, query: str, city_hint: str | None) -> GeoResult | None:
        coords = await self.yandex_maps.geocode(query, city_hint)
        if not coords:
            return None
        lat, lon, address = coords
        return GeoResult(lat=lat, lon=lon, provider="yandex_maps", confidence=0.85, normalized_address=address)

    async def geocode(self, address: str, city_hint: str | None = None) -> GeoResult | None:
        effective_city_hint = city_hint or self.default_city or None
        cache_key = hashlib.sha256(f"{effective_city_hint}:{address}".encode()).hexdigest()
        if cache_key in self._cache:
            return self._cache[cache_key]

        # Accuracy order for RU: Yandex Geocoder API (needs key) → Yandex Maps
        # (keyless) → Nominatim (last resort; weak/erratic for RU addresses).
        result = await self.yandex.geocode(address, effective_city_hint)
        if not result:
            result = await self._yandex_maps_result(address, effective_city_hint)
        if not result:
            result = await self.nominatim.geocode(address, effective_city_hint)
        if result and _is_city_centroid(result, effective_city_hint):
            result = None  # city-centroid fallback — not a real location
        if result:
            self._cache[cache_key] = result
        return result

    async def geocode_venue_osm_first(self, venue_name: str, city_hint: str | None = None) -> GeoResult | None:
        effective_city_hint = city_hint or self.default_city or None
        cache_key = hashlib.sha256(f"venue:{effective_city_hint}:{venue_name}".encode()).hexdigest()
        if cache_key in self._cache:
            return self._cache[cache_key]

        # Venue-name search: Yandex (API → Maps) understands place names best; OSM last.
        result = await self.yandex.geocode(venue_name, effective_city_hint)
        if not result:
            result = await self._yandex_maps_result(venue_name, effective_city_hint)
        if not result:
            for query in self._build_venue_queries(venue_name):
                result = await self.nominatim.geocode(query, effective_city_hint)
                if result:
                    break
        if result and _is_city_centroid(result, effective_city_hint):
            result = None  # city-centroid fallback — not a real venue location
        if result:
            self._cache[cache_key] = result
        return result

    @staticmethod
    def _build_venue_queries(venue_name: str) -> list[str]:
        raw = (venue_name or "").strip()
        if not raw:
            return []

        prefixes = ("клуб", "театр", "бар", "ресторан", "кафе", "паб", "центр")
        normalized = re.sub(r"\s+", " ", raw).strip()
        lowered = normalized.casefold()
        for prefix in prefixes:
            prefix_with_space = f"{prefix} "
            if lowered.startswith(prefix_with_space):
                normalized = normalized[len(prefix_with_space) :].strip()
                break

        queries = [raw]
        if normalized and normalized.casefold() != raw.casefold():
            queries.append(normalized)
        return queries
