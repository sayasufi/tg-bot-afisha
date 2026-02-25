import pytest

from pipeline.geocoding.providers.yandex import GeoResult
from pipeline.geocoding.service import GeocodingService


class DummyYandex:
    async def geocode(self, address: str, city_hint: str | None = None):
        return None


class DummyNominatim:
    async def geocode(self, address: str, city_hint: str | None = None):
        return GeoResult(lat=55.7, lon=37.6, provider="nominatim", confidence=0.6)


@pytest.mark.asyncio
async def test_fallback_to_nominatim() -> None:
    svc = GeocodingService()
    svc.yandex = DummyYandex()
    svc.nominatim = DummyNominatim()

    result = await svc.geocode("Tverskaya 1", "Moscow")
    assert result is not None
    assert result.provider == "nominatim"
