import hashlib

from core.config.settings import get_settings
from pipeline.geocoding.providers.nominatim import NominatimGeocoder
from pipeline.geocoding.providers.yandex import GeoResult, YandexGeocoder


class GeocodingService:
    def __init__(self) -> None:
        settings = get_settings()
        self.yandex = YandexGeocoder(settings.yandex_geocoder_key)
        self.nominatim = NominatimGeocoder(settings.nominatim_base_url)
        self._cache: dict[str, GeoResult] = {}

    async def geocode(self, address: str, city_hint: str | None = None) -> GeoResult | None:
        cache_key = hashlib.sha256(f"{city_hint}:{address}".encode()).hexdigest()
        if cache_key in self._cache:
            return self._cache[cache_key]

        result = await self.yandex.geocode(address, city_hint)
        if not result:
            result = await self.nominatim.geocode(address, city_hint)
        if result:
            self._cache[cache_key] = result
        return result
