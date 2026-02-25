from dataclasses import dataclass

import httpx

from pipeline.geocoding.providers.yandex import GeoResult


class NominatimGeocoder:
    def __init__(self, base_url: str) -> None:
        self.base_url = base_url.rstrip("/")

    async def geocode(self, address: str, city_hint: str | None = None) -> GeoResult | None:
        if not address:
            return None
        query = f"{city_hint}, {address}" if city_hint else address
        params = {"q": query, "format": "json", "limit": 1}
        headers = {"User-Agent": "tg-bot-afisha/0.1"}
        async with httpx.AsyncClient(timeout=8) as client:
            response = await client.get(f"{self.base_url}/search", params=params, headers=headers)
            if response.status_code >= 400:
                return None
            rows = response.json()
        if not rows:
            return None
        first = rows[0]
        return GeoResult(lat=float(first["lat"]), lon=float(first["lon"]), provider="nominatim", confidence=0.65)
