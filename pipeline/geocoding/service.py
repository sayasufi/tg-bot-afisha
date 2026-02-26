import hashlib
import re

from core.config.settings import get_settings
from pipeline.geocoding.providers.nominatim import NominatimGeocoder
from pipeline.geocoding.providers.yandex import GeoResult, YandexGeocoder


class GeocodingService:
    def __init__(self) -> None:
        settings = get_settings()
        self.default_city = settings.default_city
        self.yandex = YandexGeocoder(settings.yandex_geocoder_key)
        self.nominatim = NominatimGeocoder(settings.nominatim_base_url)
        self._cache: dict[str, GeoResult] = {}

    async def geocode(self, address: str, city_hint: str | None = None) -> GeoResult | None:
        effective_city_hint = city_hint or self.default_city or None
        cache_key = hashlib.sha256(f"{effective_city_hint}:{address}".encode()).hexdigest()
        if cache_key in self._cache:
            return self._cache[cache_key]

        result = await self.yandex.geocode(address, effective_city_hint)
        if not result:
            result = await self.nominatim.geocode(address, effective_city_hint)
        if result:
            self._cache[cache_key] = result
        return result

    async def geocode_venue_osm_first(self, venue_name: str, city_hint: str | None = None) -> GeoResult | None:
        effective_city_hint = city_hint or self.default_city or None
        cache_key = hashlib.sha256(f"venue:{effective_city_hint}:{venue_name}".encode()).hexdigest()
        if cache_key in self._cache:
            return self._cache[cache_key]

        # For venue names OSM is more stable than strict address geocoders.
        for query in self._build_venue_queries(venue_name):
            result = await self.nominatim.geocode(query, effective_city_hint)
            if result:
                self._cache[cache_key] = result
                return result
        return None

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
