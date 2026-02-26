import json
import re
from typing import Final

import httpx


class YandexMapsScraper:
    SEARCH_URLS: Final[tuple[str, ...]] = ("https://yandex.com/maps/", "https://yandex.ru/maps/")
    USER_AGENT: Final[str] = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    )

    async def find_address_by_place(self, venue_name: str, city_hint: str | None = None) -> str | None:
        addresses = await self.find_addresses_by_place(venue_name=venue_name, city_hint=city_hint, limit=1)
        return addresses[0] if addresses else None

    async def find_addresses_by_place(
        self,
        venue_name: str,
        city_hint: str | None = None,
        limit: int = 5,
    ) -> list[str]:
        place = (venue_name or "").strip()
        if not place:
            return []

        query = f"{place} {city_hint}".strip() if city_hint else place
        params = {"text": query}
        headers = {"User-Agent": self.USER_AGENT, "Accept-Language": "ru,en;q=0.9"}

        try:
            async with httpx.AsyncClient(timeout=8, follow_redirects=True) as client:
                for url in self.SEARCH_URLS:
                    response = await client.get(url, params=params, headers=headers)
                    if response.status_code >= 400 or not response.text or self._is_captcha_page(response.text):
                        continue
                    addresses = self.extract_business_addresses(response.text, limit=limit)
                    if addresses:
                        return addresses
        except httpx.HTTPError:
            return []
        return []

    @staticmethod
    def extract_first_business_address(html: str) -> str | None:
        addresses = YandexMapsScraper.extract_business_addresses(html, limit=1)
        return addresses[0] if addresses else None

    @staticmethod
    def extract_business_addresses(html: str, limit: int = 5) -> list[str]:
        if not html:
            return []

        pattern = re.compile(
            r'"type":"business".{0,2000}?"address":"(?P<address>(?:\\.|[^"\\]){4,500})"',
            flags=re.DOTALL,
        )
        addresses: list[str] = []
        seen: set[str] = set()
        safe_limit = max(1, limit)
        for match in pattern.finditer(html):
            raw_address = match.group("address")
            try:
                address = json.loads(f'"{raw_address}"')
            except json.JSONDecodeError:
                continue
            normalized = str(address).strip()
            if not normalized or normalized in seen:
                continue
            addresses.append(normalized)
            seen.add(normalized)
            if len(addresses) >= safe_limit:
                break
        return addresses

    @staticmethod
    def _is_captcha_page(html: str) -> bool:
        lowered = html.casefold()
        return "are you not a robot?" in lowered or "checkcaptcha" in lowered or "smartcaptcha" in lowered
