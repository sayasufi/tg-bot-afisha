from dataclasses import dataclass

import httpx


@dataclass
class GeoResult:
    lat: float
    lon: float
    provider: str
    confidence: float
    normalized_address: str = ""


class YandexGeocoder:
    def __init__(self, api_key: str) -> None:
        self.api_key = api_key

    async def geocode(self, address: str, city_hint: str | None = None) -> GeoResult | None:
        if not self.api_key or not address:
            return None
        query = f"{city_hint}, {address}" if city_hint else address
        params = {"apikey": self.api_key, "format": "json", "geocode": query}
        async with httpx.AsyncClient(timeout=8) as client:
            response = await client.get("https://geocode-maps.yandex.ru/1.x/", params=params)
            if response.status_code >= 400:
                return None
            data = response.json()

        members = (
            data.get("response", {})
            .get("GeoObjectCollection", {})
            .get("featureMember", [])
        )
        if not members:
            return None
        first = members[0]["GeoObject"]
        pos = first["Point"]["pos"]
        lon, lat = [float(x) for x in pos.split(" ")]
        normalized_address = (
            first.get("metaDataProperty", {})
            .get("GeocoderMetaData", {})
            .get("text", "")
        )
        return GeoResult(lat=lat, lon=lon, provider="yandex", confidence=0.9, normalized_address=normalized_address)
