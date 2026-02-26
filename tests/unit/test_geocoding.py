import pytest
import os

from pipeline.geocoding.providers.yandex import GeoResult
from pipeline.geocoding.service import GeocodingService


class DummyYandex:
    def __init__(self, result: GeoResult | None = None):
        self.result = result
        self.calls: list[tuple[str, str | None]] = []

    async def geocode(self, address: str, city_hint: str | None = None):
        self.calls.append((address, city_hint))
        return self.result


class DummyNominatim:
    def __init__(self):
        self.calls: list[tuple[str, str | None]] = []

    async def geocode(self, address: str, city_hint: str | None = None):
        self.calls.append((address, city_hint))
        return GeoResult(lat=55.7, lon=37.6, provider="nominatim", confidence=0.6)


@pytest.mark.asyncio
async def test_fallback_to_nominatim() -> None:
    svc = GeocodingService()
    yandex = DummyYandex()
    nominatim = DummyNominatim()
    svc.yandex = yandex
    svc.nominatim = nominatim

    result = await svc.geocode("Тверская 1", "Москва")
    assert result is not None
    assert result.provider == "nominatim"
    assert yandex.calls
    assert nominatim.calls


@pytest.mark.asyncio
async def test_yandex_has_priority_and_uses_default_city_hint() -> None:
    svc = GeocodingService()
    svc.default_city = "Москва"
    yandex = DummyYandex(GeoResult(lat=55.75, lon=37.61, provider="yandex", confidence=0.9))
    nominatim = DummyNominatim()
    svc.yandex = yandex
    svc.nominatim = nominatim

    result = await svc.geocode("Тверская 1")
    assert result is not None
    assert result.provider == "yandex"
    assert yandex.calls == [("Тверская 1", "Москва")]
    assert not nominatim.calls


class DummyYandexMapsScraper:
    def __init__(self, result: str | None = None):
        self.result = result
        self.calls: list[tuple[str, str | None]] = []

    async def find_address_by_place(self, venue_name: str, city_hint: str | None = None) -> str | None:
        self.calls.append((venue_name, city_hint))
        return self.result


@pytest.mark.asyncio
async def test_venue_osm_first_uses_nominatim_and_caches() -> None:
    svc = GeocodingService()
    svc.default_city = "Москва"
    svc.yandex_maps_scraper = DummyYandexMapsScraper(None)  # scraper returns no address
    yandex = DummyYandex(GeoResult(lat=55.75, lon=37.61, provider="yandex", confidence=0.9))
    nominatim = DummyNominatim()
    svc.yandex = yandex
    svc.nominatim = nominatim

    first = await svc.geocode_venue_osm_first("Крокус Сити Холл")
    second = await svc.geocode_venue_osm_first("Крокус Сити Холл")

    assert first is not None
    assert second is not None
    assert first.provider == "nominatim"
    assert second.provider == "nominatim"
    assert nominatim.calls == [("Крокус Сити Холл", "Москва")]
    assert not yandex.calls


@pytest.mark.asyncio
async def test_venue_osm_first_uses_yandex_maps_scraper_before_nominatim() -> None:
    svc = GeocodingService()
    svc.default_city = "Москва"
    svc.yandex_maps_scraper = DummyYandexMapsScraper("ул. Сретенка, 16/2, Москва")
    yandex = DummyYandex(GeoResult(lat=55.77, lon=37.63, provider="yandex", confidence=0.9))
    nominatim = DummyNominatim()
    svc.yandex = yandex
    svc.nominatim = nominatim

    result = await svc.geocode_venue_osm_first("Рислинг Бойз")

    assert result is not None
    assert result.provider == "yandex_maps"
    assert result.normalized_address == "ул. Сретенка, 16/2, Москва"
    assert result.lat == 55.77 and result.lon == 37.63
    assert svc.yandex_maps_scraper.calls == [("Рислинг Бойз", "Москва")]
    assert yandex.calls == [("ул. Сретенка, 16/2, Москва", "Москва")]
    assert not nominatim.calls


@pytest.mark.asyncio
async def test_venue_osm_first_tries_normalized_name_variant() -> None:
    class VariantAwareNominatim:
        def __init__(self):
            self.calls: list[tuple[str, str | None]] = []

        async def geocode(self, address: str, city_hint: str | None = None):
            self.calls.append((address, city_hint))
            if address == "16 Тонн":
                return GeoResult(lat=55.765, lon=37.56, provider="nominatim", confidence=0.65)
            return None

    svc = GeocodingService()
    svc.default_city = "Москва"
    svc.yandex_maps_scraper = DummyYandexMapsScraper(None)
    svc.nominatim = VariantAwareNominatim()
    svc.yandex = DummyYandex(GeoResult(lat=55.75, lon=37.61, provider="yandex", confidence=0.9))

    result = await svc.geocode_venue_osm_first("Клуб 16 Тонн")

    assert result is not None
    assert result.provider == "nominatim"
    assert svc.nominatim.calls == [("Клуб 16 Тонн", "Москва"), ("16 Тонн", "Москва")]


MOSCOW_VENUES_FOR_LIVE_CHECKS = [
    "Театр.doc на Лесной",
    "Центр Вознесенского",
    "Культурный центр Хитровка",
    "Центр Гиляровского",
    "Электротеатр Станиславский",
    "Театр Практика",
    "Центр драматургии и режиссуры",
    "Дом Гоголя",
    "Ресторан Sapiens",
    "Театр МОСТ",
]


def _is_roughly_moscow(lat: float, lon: float) -> bool:
    return 55.2 <= lat <= 56.1 and 36.7 <= lon <= 38.2


@pytest.mark.asyncio
@pytest.mark.skipif(
    os.getenv("RUN_LIVE_GEOCODING_TESTS") != "1",
    reason="live geocoding tests are disabled by default",
)
@pytest.mark.parametrize("venue_name", MOSCOW_VENUES_FOR_LIVE_CHECKS)
async def test_live_moscow_venues_osm_first(venue_name: str) -> None:
    svc = GeocodingService()
    svc.default_city = "Москва"
    result = await svc.geocode_venue_osm_first(venue_name)
    assert result is not None
    assert result.provider == "nominatim"
    assert _is_roughly_moscow(result.lat, result.lon)
